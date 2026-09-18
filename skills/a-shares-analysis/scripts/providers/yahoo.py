#!/usr/bin/env python3
"""Yahoo Finance provider (unofficial, KEYLESS) — US & HK equities + global indices.

Endpoints used (browser UA required, no crumb/cookie needed for these):
  GET /v1/finance/search?q=<ascii>          -> symbol lookup (CJK rejected; the
        calling agent must translate Chinese names to English/ticker first)
  GET /v8/finance/chart/<symbol>?period1&period2&interval=1d&events=history
        -> OHLCV + adjclose + exchange timezone metadata (quote derives from meta)

Design notes:
- dates are normalized to the EXCHANGE timezone (meta.exchangeTimezoneName),
  not Asia/Shanghai — US bars keep their ET dates so freshness checks work
- adjclose (split+dividend adjusted) is used as `close` for adjust="forward";
  raw close is kept when adjust="none"
- politeness 0.6s + bounded backoff on 429/999 (unofficial API etiquette)
HTTP layer injectable (`send=`) for offline tests, same as FuyaoProvider.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

from providers.base import (
    ERR_AUTH,
    ERR_NOT_FOUND,
    ERR_PARAM,
    ERR_RATE_LIMIT,
    ERR_UPSTREAM,
    ProviderError,
)

BASE = "https://query1.finance.yahoo.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

_US_EXCHANGES = {"NMS", "NYQ", "ASE", "PCX", "BTS", "PNK", "NGM", "NCM", "NGQ"}
_RETRYABLE = {ERR_RATE_LIMIT, ERR_UPSTREAM}


class YahooProvider:
    name = "yahoo"
    capabilities = {
        "search", "daily_kline", "quote", "index_kline", "index_quote",
    }

    def __init__(self, send: Callable[..., str] | None = None,
                 politeness_s: float = 0.6, max_retries: int = 3):
        self._send = send or self._http_get
        self.politeness_s = politeness_s
        self.max_retries = max_retries
        self._last_call = 0.0
        self._meta_cache: dict[str, dict] = {}  # symbol -> chart meta

    # ------------------------------------------------------------------ http
    def _http_get(self, path: str, params: dict) -> str:
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        url = f"{BASE}{path}?{query}"
        request = urllib.request.Request(url, headers={
            "User-Agent": UA, "Accept": "application/json",
        })
        try:
            with urllib.request.urlopen(request, timeout=30) as resp:
                return resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", "ignore")
            except Exception:
                pass
            if exc.code in (429, 999) or '"code":"Too Many Requests"' in body:
                return json.dumps({"finance": {"error": {"code": "Too Many Requests"}}})
            if exc.code == 404:
                raise ProviderError(ERR_NOT_FOUND, f"unknown symbol on yahoo: {path}") from exc
            raise ProviderError(ERR_UPSTREAM, f"HTTP {exc.code} on {path}") from exc
        except urllib.error.URLError as exc:
            raise ProviderError(ERR_UPSTREAM, f"network error on {path}: {exc.reason}") from exc

    def _get(self, path: str, params: dict):
        """GET with politeness + bounded retry; returns parsed JSON body."""
        last: ProviderError | None = None
        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                body = self._send(path, params)
                data = json.loads(body)
            except (ValueError, TypeError) as exc:
                raise ProviderError(ERR_UPSTREAM, f"non-JSON from yahoo {path}: {exc}") from exc
            err = (data.get("finance") or {}).get("error")
            chart_err = (data.get("chart") or {}).get("error")
            if not err and not chart_err:
                return data
            code = (err or chart_err or {}).get("code", "")
            message = f"yahoo {path}: {code or 'error'}"
            last = ProviderError(
                ERR_RATE_LIMIT if code == "Too Many Requests" else ERR_UPSTREAM, message)
            if last.kind in _RETRYABLE and attempt < self.max_retries:
                time.sleep(1.0 * (attempt + 1) + 0.5)
                continue
            raise last
        raise last or ProviderError(ERR_UPSTREAM, "retries exhausted")

    def _throttle(self) -> None:
        wait = self.politeness_s - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def has(self, capability: str) -> bool:
        return capability in self.capabilities

    # ---------------------------------------------------------------- search
    def search(self, q: str, asset_type: str | None = None, limit: int = 10) -> list[dict]:
        data = self._get("/v1/finance/search", {"q": q, "quotesCount": min(limit, 20),
                                                 "newsCount": 0})
        out = []
        for it in (data.get("quotes") or [])[:limit]:
            symbol = it.get("symbol") or ""
            if not symbol:
                continue
            exch = it.get("exchange") or ""
            kind = it.get("quoteType") or ""
            if symbol.endswith(".HK"):
                mapped = "hk-stock"
            elif exch in _US_EXCHANGES:
                mapped = "us-stock"
            elif symbol.startswith("^"):
                mapped = "a-share-index"      # global index; type-agnostic bucket
            else:
                mapped = "other"
            if kind != "EQUITY" and not symbol.startswith("^"):
                continue  # skip ETFs/currencies/crypto in this equity skill
            if asset_type and mapped != asset_type:
                continue
            out.append({"thscode": symbol, "ticker": symbol.split(".")[0],
                        "name": it.get("longname") or it.get("shortname") or symbol,
                        "exchange": exch, "asset_type": mapped,
                        "list_date": None, "end_date": None})
        # HK numeric codes: "00700" style -> direct 0700.HK probe via chart meta
        if not out and q.isdigit() and 1 <= len(q) <= 5:
            cand = f"{int(q):04d}.HK"
            if self._probe_symbol(cand):
                out = [{"thscode": cand, "ticker": cand.split(".")[0],
                        "name": cand, "exchange": "HKG", "asset_type": "hk-stock",
                        "list_date": None, "end_date": None}]
            if asset_type and out and asset_type != "hk-stock":
                out = []
        return out

    def _probe_symbol(self, symbol: str) -> bool:
        try:
            data = self._get("/v8/finance/chart/" + urllib.parse.quote(symbol),
                             {"range": "1d", "interval": "1d"})
            return bool((data.get("chart") or {}).get("result"))
        except ProviderError:
            return False

    # ---------------------------------------------------------------- chart
    def _chart(self, symbol: str, start_ms: int | None = None, end_ms: int | None = None,
               adjust: str = "forward") -> dict:
        params = {"interval": "1d", "events": "history", "includePrePost": "false"}
        if end_ms:  # ranged history call (quote path passes end_ms=None)
            params["period1"] = int(max(start_ms or 0, 0) // 1000)
            params["period2"] = int(end_ms // 1000)
        else:
            params["range"] = "1d"
        data = self._get("/v8/finance/chart/" + urllib.parse.quote(symbol), params)
        result = ((data.get("chart") or {}).get("result") or [None])[0]
        if not result:
            raise ProviderError(ERR_NOT_FOUND, f"no chart data for {symbol}")
        if end_ms:
            self._meta_cache[symbol] = result.get("meta") or {}
        return result

    def _bars_from_chart(self, result: dict, adjust: str) -> list[dict]:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        meta = result.get("meta") or {}
        tz = ZoneInfo(meta.get("exchangeTimezoneName") or "America/New_York")
        ts = (result.get("timestamp") or [])
        quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
        adj = ((result.get("indicators") or {}).get("adjclose") or [{}])[0].get("adjclose")
        opens, highs = quote.get("open") or [], quote.get("high") or []
        lows, closes = quote.get("low") or [], quote.get("close") or []
        volumes = quote.get("volume") or []
        bars = []
        for i, t in enumerate(ts):
            close = closes[i] if i < len(closes) else None
            if close is None:
                continue
            if adjust != "none" and adj and i < len(adj) and adj[i] is not None:
                close = adj[i]  # split+dividend adjusted series for TA
            bars.append({
                "date": datetime.fromtimestamp(t, tz).strftime("%Y-%m-%d"),
                "open": opens[i] if i < len(opens) else None,
                "high": highs[i] if i < len(highs) else None,
                "low": lows[i] if i < len(lows) else None,
                "close": close,
                "volume": volumes[i] if i < len(volumes) else None,
                "turnover": None,
            })
        return bars

    # ------------------------------------------------------------ market data
    def daily_kline(self, thscode: str, start_ms: int, end_ms: int,
                    adjust: str = "forward") -> list[dict]:
        return self._bars_from_chart(self._chart(thscode, start_ms, end_ms, adjust), adjust)

    def index_kline(self, thscode: str, start_ms: int, end_ms: int) -> list[dict]:
        return self._bars_from_chart(self._chart(thscode, start_ms, end_ms, "none"), "none")

    def quote(self, thscodes: list[str]) -> list[dict]:
        out = []
        for symbol in thscodes:
            meta = self._chart(symbol).get("meta") or {}
            last = meta.get("regularMarketPrice")
            prev = meta.get("chartPreviousClose") or meta.get("previousClose")
            tz = meta.get("exchangeTimezoneName") or "America/New_York"
            t = meta.get("regularMarketTime")
            from datetime import datetime
            from zoneinfo import ZoneInfo

            as_of = (datetime.fromtimestamp(t, ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M %Z")
                     if t else None)
            out.append({
                "thscode": symbol, "ticker": symbol.split(".")[0],
                "last": last, "prev": prev,
                "chg": round(last - prev, 4) if (last is not None and prev) else None,
                "chg_pct": round((last / prev - 1) * 100, 2) if (last and prev) else None,
                "currency": meta.get("currency"),
                "as_of": as_of, "market_tz": tz,
            })
        return out

    def index_quote(self, thscodes: list[str]) -> list[dict]:
        return self.quote(thscodes)

    # ------------------------------------------------------------ extras
    def market_meta(self, symbol: str) -> dict:
        """Cached chart meta (currency/exchange tz) from the last kline call."""
        return self._meta_cache.get(symbol) or {}
