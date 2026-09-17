#!/usr/bin/env python3
"""Fuyao (同花顺金融数据, https://fuyao.aicubes.cn) REST provider.

Default data source for the skill. Free tier constraints baked into design:
- daily bars only (`interval=1d`); no intraday — the skill is 中长线 oriented
- capital-flow & high-frequency endpoints exist but are NOT open externally,
  so those capabilities are intentionally absent here

Uses stdlib urllib only. The HTTP layer is injectable (`send=`) for offline tests.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

from providers.base import (
    ERR_AUTH,
    ERR_NO_DATA,
    ERR_NOT_FOUND,
    ERR_PARAM,
    ERR_RATE_LIMIT,
    ERR_UPSTREAM,
    ProviderError,
)

BASE_URL = "https://fuyao.aicubes.cn"

# envelope code -> our error kind
_CODE_KIND = {
    1001: ERR_PARAM, 1002: ERR_PARAM, 1003: ERR_PARAM, 1004: ERR_PARAM,
    2001: ERR_AUTH, 2003: ERR_AUTH,
    3001: ERR_NOT_FOUND, 3002: ERR_NO_DATA, 3004: ERR_PARAM,
    4001: ERR_RATE_LIMIT,
    5001: ERR_UPSTREAM, 5002: ERR_UPSTREAM, 5003: ERR_UPSTREAM,
}
_RETRYABLE = {ERR_RATE_LIMIT, ERR_UPSTREAM}


class FuyaoProvider:
    name = "fuyao"

    # capital-flow / high-frequency intentionally excluded (not open externally)
    capabilities = {
        "search", "daily_kline", "quote", "valuation", "fin_indicators",
        "income_statements", "balance_sheets", "cash_flow_statements",
        "corp_actions", "calendar", "index_kline", "index_quote",
        "index_constituents", "hot_rank_trend",
    }

    def __init__(self, api_key: str, send: Callable[..., str] | None = None,
                 politeness_s: float = 0.3, max_retries: int = 3):
        if not api_key:
            raise ProviderError(ERR_AUTH, "fuyao provider needs an API key (X-api-key)")
        self.api_key = api_key
        self._send = send or self._http_get
        self.politeness_s = politeness_s
        self.max_retries = max_retries
        self._last_call = 0.0

    # ------------------------------------------------------------------ http
    def _http_get(self, path: str, params: dict) -> str:
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        url = f"{BASE_URL}{path}?{query}"
        request = urllib.request.Request(url, headers={
            "X-api-key": self.api_key,
            "Accept": "application/json",
            "User-Agent": "a-shares-analysis-skill/1.0",
        })
        try:
            with urllib.request.urlopen(request, timeout=30) as resp:
                return resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            # envelope-style API: 429 carries the same JSON body
            if exc.code == 429:
                return exc.read().decode("utf-8")
            raise ProviderError(ERR_UPSTREAM, f"HTTP {exc.code} on {path}") from exc
        except urllib.error.URLError as exc:
            raise ProviderError(ERR_UPSTREAM, f"network error on {path}: {exc.reason}") from exc

    def _get(self, path: str, params: dict) -> Any:
        """One GET with politeness delay + bounded retry on transient errors."""
        last_error: ProviderError | None = None
        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                body = self._send(path, params)
                envelope = json.loads(body)
            except (ValueError, TypeError) as exc:
                raise ProviderError(ERR_UPSTREAM, f"non-JSON response from {path}: {exc}") from exc
            code = envelope.get("code")
            if code == 0:
                return envelope.get("data")
            kind = _CODE_KIND.get(code, ERR_UPSTREAM)
            message = f"{envelope.get('message')} (code={code}, path={path})"
            last_error = ProviderError(kind, message, code)
            if kind in _RETRYABLE and attempt < self.max_retries:
                time.sleep(1.0 * (attempt + 1) + 0.5)  # 1.5s, 2.5s, 3.5s backoff
                continue
            raise last_error
        raise last_error or ProviderError(ERR_UPSTREAM, "retries exhausted")

    def _throttle(self) -> None:
        wait = self.politeness_s - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def has(self, capability: str) -> bool:
        return capability in self.capabilities

    # ------------------------------------------------------------- identity
    def search(self, q: str, asset_type: str | None = None, limit: int = 10) -> list[dict]:
        limit = min(max(limit, 1), 50)
        data = self._get("/api/meta/tickers/search", {"q": q, "asset_type": asset_type, "limit": limit})
        out = []
        for it in (data or {}).get("item", []):
            out.append({
                "thscode": it.get("thscode"),
                "ticker": it.get("ticker"),
                "name": it.get("name"),
                "exchange": it.get("exchange"),
                "asset_type": it.get("asset_type"),
                "list_date": it.get("list_date"),
                "end_date": it.get("end_date"),
            })
        return out

    # ---------------------------------------------------------- market data
    def daily_kline(self, thscode: str, start_ms: int, end_ms: int,
                    adjust: str = "forward") -> list[dict]:
        data = self._get("/api/a-share/prices/historical", {
            "thscode": thscode, "interval": "1d",
            "start": int(start_ms), "end": int(end_ms), "adjust": adjust,
        })
        return [_bar(it) for it in (data or {}).get("item", [])]

    def quote(self, thscodes: list[str]) -> list[dict]:
        data = self._get("/api/a-share/prices/snapshot", {"thscodes": ",".join(thscodes)})
        return [_quote(it) for it in (data or {}).get("item", [])]

    # --------------------------------------------------------- fundamentals
    def valuation(self, thscodes: list[str]) -> list[dict]:
        if len(thscodes) > 100:
            raise ProviderError(ERR_PARAM, "valuation accepts at most 100 thscodes")
        data = self._get("/api/a-share/valuations/snapshot", {"thscodes": ",".join(thscodes)})
        out = []
        for it in (data or {}).get("item", []):
            out.append({
                "thscode": it.get("thscode"), "name": it.get("name"),
                "pe_ttm": it.get("pe_ttm"), "pe_mrq": it.get("pe_mrq"),
                "pb_mrq": it.get("pb_mrq"), "ps_ttm": it.get("ps_ttm"),
                "pcf_ttm": it.get("pcf_ttm"),
            })
        return out

    def fin_indicators(self, thscode: str, report: str) -> dict:
        data = self._get("/api/a-share/financials/indicators",
                         {"thscode": thscode, "report": report})
        return {
            "report": report,
            "abilities": [
                {"ability": ab.get("ability"),
                 "indicators": [{"index_id": ind.get("index_id"), "value": ind.get("value")}
                                for ind in ab.get("indicators", [])]}
                for ab in (data or {}).get("abilities", [])
            ],
        }

    def _statements(self, path: str, thscode: str, period: str, limit: int) -> list[dict]:
        data = self._get(path, {"thscode": thscode, "period": period, "limit": limit})
        items = (data or {}).get("item", [])
        for it in items:  # drop envelope noise; keep raw field dict + period tag
            it.pop("thscode", None), it.pop("ticker", None), it.pop("period", None)
        return items

    def income_statements(self, thscode: str, period: str = "annual", limit: int = 5) -> list[dict]:
        return self._statements("/api/a-share/financials/income-statements", thscode, period, limit)

    def balance_sheets(self, thscode: str, period: str = "annual", limit: int = 3) -> list[dict]:
        return self._statements("/api/a-share/financials/balance-sheets", thscode, period, limit)

    def cash_flow_statements(self, thscode: str, period: str = "annual", limit: int = 3) -> list[dict]:
        return self._statements("/api/a-share/financials/cash-flow-statements", thscode, period, limit)

    def corp_actions(self, thscode: str) -> list[dict]:
        data = self._get("/api/a-share/corporate-actions/adjustment-factors", {"thscode": thscode})
        out = []
        for it in (data or {}).get("item", []):  # newest first
            ex_ms = it.get("ex_date_ms")
            out.append({
                "ex_date": _ms_date(ex_ms) if ex_ms is not None else None,
                "dividend_per_share": it.get("dividend_per_share"),
                "per_share_bonus": it.get("per_share_bonus"),
            })
        return out

    # ------------------------------------------------------- market context
    def calendar(self) -> list[str]:
        data = self._get("/api/a-share/calendar/trading-days", {})
        # upstream `date` is yyyyMMdd; normalized schema wants YYYY-MM-DD
        out = []
        for it in (data or {}).get("item", []):
            raw = str(it.get("date", ""))
            if len(raw) == 8:
                out.append(f"{raw[:4]}-{raw[4:6]}-{raw[6:]}")
        return out

    def index_kline(self, thscode: str, start_ms: int, end_ms: int) -> list[dict]:
        data = self._get("/api/a-share-index/prices/historical", {
            "thscode": thscode, "interval": "1d",
            "start": int(start_ms), "end": int(end_ms),
        })
        return [_bar(it) for it in (data or {}).get("item", [])]

    def index_quote(self, thscodes: list[str]) -> list[dict]:
        data = self._get("/api/a-share-index/prices/snapshot", {"thscodes": ",".join(thscodes)})
        return [_quote(it) for it in (data or {}).get("item", [])]

    def index_constituents(self, index_thscode: str) -> list[dict]:
        data = self._get("/api/a-share-index/constituents/ths-stock-list",
                         {"thscode": index_thscode})
        return [{"thscode": it.get("thscode"), "ticker": it.get("ticker"), "name": it.get("name")}
                for it in (data or {}).get("item", [])]

    def hot_rank_trend(self, thscode: str, start_date: str, end_date: str) -> list[dict]:
        data = self._get("/api/a-share/special-data/hot-stock-rank-trend", {
            "thscode": thscode, "start_date": start_date, "end_date": end_date,
        })
        return [{"date": it.get("date"), "rank": it.get("rank")}
                for it in (data or {}).get("item", [])]


# --------------------------------------------------------------------------
# response -> normalized-schema mappers
# --------------------------------------------------------------------------
def _ms_date(ms: Any) -> str | None:
    if ms is None:
        return None
    from datetime import datetime, timezone, timedelta

    cst = timezone(timedelta(hours=8))
    return datetime.fromtimestamp(int(ms) / 1000, cst).strftime("%Y-%m-%d")


def _bar(it: dict) -> dict:
    return {
        "date": _ms_date(it.get("date_ms")),
        "open": it.get("open_price"), "high": it.get("high_price"),
        "low": it.get("low_price"), "close": it.get("close_price"),
        "volume": it.get("volume"), "turnover": it.get("turnover"),
    }


def _quote(it: dict) -> dict:
    return {
        "thscode": it.get("thscode"), "ticker": it.get("ticker"),
        "last": it.get("last_price"), "chg": it.get("price_change"),
        "chg_pct": it.get("price_change_ratio_pct"),
        "open": it.get("open_price"), "high": it.get("high_price"),
        "low": it.get("low_price"), "prev": it.get("prev_price"),
        "volume": it.get("volume"), "turnover": it.get("turnover"),
    }
