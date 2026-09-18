#!/usr/bin/env python3
"""SEC EDGAR provider (official, KEYLESS) — US fundamentals for the skill.

  https://www.sec.gov/files/company_tickers.json     symbol -> CIK map (cached 1d)
  https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json   XBRL facts

SEC policy: declare a User-Agent with contact info; <= 10 req/s. We stay at
<= 2 req per analysis (map + facts), cached on disk.

Normalized output (USD, fiscal-year granularity; V1 uses latest annual figures
so valuation is FY-based, labelled as such downstream):
  {symbol, cik, shares_outstanding,
   income_annual: [{fiscal_year, end, revenue, net_income, eps_diluted}],
   balance_latest: {assets, liabilities, cash, long_term_debt, end},
   flows_latest: {operating_cf, capex, end}}
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from ash_common import CACHE_DIR, now_cst
from providers.base import ERR_NOT_FOUND, ERR_UPSTREAM, ProviderError

BASE = "https://data.sec.gov"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
# SEC WAF accepts "name email" format (parens / URL-style UAs get 403)
UA = "a-shares-analysis-skill admin@owentrader.dev"
TICKER_CACHE = CACHE_DIR / "sec_tickers.json"
CACHE_TTL_H = 24


def _http_get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept-Encoding": "gzip, deflate", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as resp:
            data = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                import gzip
                data = gzip.decompress(data)
            return data
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise ProviderError(ERR_NOT_FOUND, f"SEC 404: {url}") from exc
        raise ProviderError(ERR_UPSTREAM, f"SEC HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ProviderError(ERR_UPSTREAM, f"SEC network error: {exc.reason}") from exc


class SecProvider:
    name = "sec"
    capabilities = {"sec_fundamentals"}

    def __init__(self, getter=_http_get, sleep=time.sleep):
        self._get = getter
        self._sleep = sleep

    def has(self, capability: str) -> bool:
        return capability in self.capabilities

    # ------------------------------------------------------------------ cik map
    def _cik_map(self) -> dict[str, dict]:
        fresh = False
        if TICKER_CACHE.is_file():
            age_h = (time.time() - TICKER_CACHE.stat().st_mtime) / 3600
            fresh = age_h < CACHE_TTL_H
        if fresh:
            return json.loads(TICKER_CACHE.read_text(encoding="utf-8"))
        data = json.loads(self._get(TICKERS_URL).decode("utf-8"))
        mapping = {v["ticker"].upper(): {"cik": int(v["cik_str"]), "title": v["title"]}
                   for v in data.values()}
        TICKER_CACHE.parent.mkdir(parents=True, exist_ok=True)
        TICKER_CACHE.write_text(json.dumps(mapping), encoding="utf-8")
        return mapping

    def resolve_cik(self, symbol: str) -> int:
        hit = self._cik_map().get(symbol.upper())
        if not hit:
            raise ProviderError(ERR_NOT_FOUND, f"symbol {symbol} not in SEC ticker map")
        return hit["cik"]

    # ------------------------------------------------------------------ facts
    def fundamentals(self, symbol: str) -> dict:
        cik = self.resolve_cik(symbol)
        url = f"{BASE}/api/xbrl/companyfacts/CIK{cik:010d}.json"
        facts = json.loads(self._get(url).decode("utf-8"))
        gaap = (facts.get("facts") or {}).get("us-gaap") or {}
        dei = (facts.get("facts") or {}).get("dei") or {}

        def series(tag: str, unit: str = "USD"):
            node = gaap.get(tag) or {}
            units = node.get("units") or {}
            if unit in units:
                return units[unit]
            if unit == "USD":  # tolerate "USD/shares"-style aliases for the tag
                return next((v for k, v in units.items() if k.startswith("USD")), [])
            return []

        def fy_entries(entries: list[dict]) -> list[dict]:
            """Annual (10-K) entries, one per fiscal year (latest filing wins).

            Both duration (revenue) and instant (assets) facts are accepted:
            10-K/FY filtering plus filed-date preference keeps one per year.
            """
            by_year: dict[int, dict] = {}
            from datetime import date

            def full_year(e: dict) -> bool:
                start = e.get("start")
                if not start:
                    return True  # instant fact (assets/liabilities/...)
                days = (date.fromisoformat(e["end"]) - date.fromisoformat(start)).days
                return 300 <= days <= 400

            for e in entries:
                if e.get("form") != "10-K" or e.get("fp") != "FY":
                    continue
                if not full_year(e):
                    continue
                year = int(e.get("fy") or e["end"][:4])
                cur = by_year.get(year)
                if cur is None or (e.get("filed") or "") >= (cur.get("filed") or ""):
                    by_year[year] = e
            return [by_year[y] for y in sorted(by_year)]

        # revenue: newer filers use the contract-revenue tag; merge both and dedupe
        rev = fy_entries(series("Revenues") + series(
            "RevenueFromContractWithCustomerExcludingAssessedTax"))
        ni = fy_entries(series("NetIncomeLoss"))
        eps = fy_entries(series("EarningsPerShareDiluted", "USD/shares"))
        income = []
        eps_by_year = {int(e.get("fy") or e["end"][:4]): e.get("val") for e in eps}
        for r in rev[-6:]:
            year = int(r.get("fy") or r["end"][:4])
            income.append({
                "fiscal_year": year, "end": r["end"],
                "revenue": r.get("val"),
                "net_income": next((n.get("val") for n in ni
                                    if int(n.get("fy") or n["end"][:4]) == year), None),
                "eps_diluted": eps_by_year.get(year),
            })

        def latest_annual(tag):
            ents = fy_entries(series(tag))
            return ents[-1] if ents else None

        shares_entries = ((dei.get("EntityCommonStockSharesOutstanding") or {})
                          .get("units", {}).get("shares") or [])
        shares = next((e["val"] for e in reversed(shares_entries)), None)

        assets = latest_annual("Assets")
        liab = latest_annual("Liabilities")
        cash = latest_annual("CashAndCashEquivalentsAtCarryingValue")
        debt = latest_annual("LongTermDebtNoncurrent") or latest_annual("LongTermDebt")
        ocf = latest_annual("NetCashProvidedByUsedInOperatingActivities")
        capex = latest_annual("PaymentsToAcquirePropertyPlantAndEquipment")

        return {
            "symbol": symbol.upper(), "cik": cik,
            "shares_outstanding": shares,
            "income_annual": income,
            "balance_latest": {
                "end": (assets or {}).get("end"),
                "assets": (assets or {}).get("val"),
                "liabilities": (liab or {}).get("val"),
                "cash": (cash or {}).get("val"),
                "long_term_debt": (debt or {}).get("val"),
            },
            "flows_latest": {
                "end": (ocf or {}).get("end"),
                "operating_cf": (ocf or {}).get("val"),
                "capex": (capex or {}).get("val"),
            },
        }

    # kept off the generic protocol: US-only capability accessed explicitly
    def __getattr__(self, item):  # unsupported generic calls -> explicit error
        if item in ("search", "daily_kline", "quote", "index_kline", "index_quote"):
            def _unsupported(*_a, **_k):
                raise ProviderError("param", f"sec provider does not provide '{item}'")
            return _unsupported
        raise AttributeError(item)
