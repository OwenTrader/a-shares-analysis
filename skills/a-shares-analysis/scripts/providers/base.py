#!/usr/bin/env python3
"""Data-provider abstraction layer.

Every downstream script (resolve_ticker / fetch_snapshot / journal) talks to this
interface only — never to a vendor SDK or HTTP endpoint directly. Adding a new
data source (tushare / baostock / akshare / a paid intraday feed ...) means
writing one module that implements `DataProvider` and registering it in
`providers/__init__.py`; nothing else changes. See references/providers.md.

Normalized schemas (all providers must return these shapes):

  Ticker      {thscode, ticker, name, exchange, asset_type, list_date, end_date}
  Bar         {date: "YYYY-MM-DD", open, high, low, close, volume, turnover}
  Quote       {thscode, ticker, name, last, chg, chg_pct, open, high, low, prev, volume, turnover}
  Valuation   {thscode, name, pe_ttm, pe_mrq, pb_mrq, ps_ttm, pcf_ttm}
  FinInds     {report: "YYYY-Q", abilities: [{ability, indicators: [{index_id, value}]}]}
  Statement   {report: "YYYY-MM-DD" | "YYYY-Q", items: {field: value}}   # sparse, provider-dependent
  CorpAction  {ex_date: "YYYY-MM-DD", dividend_per_share, per_share_bonus}
  HotRank     {date: "YYYY-MM-DD", rank: int}
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

# Canonical capability names. A provider declares which ones it supports;
# fetch_snapshot degrades gracefully (records section error) for missing ones.
CAPABILITIES = {
    "search",            # q -> [Ticker]
    "daily_kline",       # stock daily bars (adjusted)
    "quote",             # real-time-ish snapshot quote
    "valuation",         # PE/PB/PS/PCF
    "fin_indicators",    # 5-ability financial indicator set per report period
    "income_statements", # multi-period income statements
    "balance_sheets",
    "cash_flow_statements",
    "corp_actions",      # dividend / bonus event stream
    "calendar",          # trading days (~1 year)
    "index_kline",       # index daily bars
    "index_quote",       # index snapshot
    "index_constituents",
    "hot_rank_trend",    # per-stock heat-rank daily series
}

# Error codes shared across providers (kept aligned with fuyao's envelope).
ERR_AUTH = "auth"            # 2001/2003 — key invalid or lacks capability
ERR_RATE_LIMIT = "rate"      # 4001 / HTTP 429 — retry later
ERR_NOT_FOUND = "not_found"  # 3001
ERR_NO_DATA = "no_data"      # 3002 — exists but nothing published yet
ERR_UPSTREAM = "upstream"    # 5001-5003 — transient, retryable
ERR_PARAM = "param"          # 1001-1004 — caller bug


class ProviderError(RuntimeError):
    """Raised by providers; `kind` maps to one of the ERR_* constants above."""

    def __init__(self, kind: str, message: str, code: Any = None):
        super().__init__(f"[{kind}] {message}")
        self.kind = kind
        self.code = code
        self.message = message


@runtime_checkable
class DataProvider(Protocol):
    """Interface every data source must implement."""

    name: str
    capabilities: set[str]

    # --- identity -----------------------------------------------------------
    def search(self, q: str, asset_type: str | None = None, limit: int = 10) -> list[dict]:
        ...

    # --- market data --------------------------------------------------------
    def daily_kline(self, thscode: str, start_ms: int, end_ms: int,
                    adjust: str = "forward") -> list[dict]:
        ...

    def quote(self, thscodes: list[str]) -> list[dict]:
        ...

    # --- fundamentals -------------------------------------------------------
    def valuation(self, thscodes: list[str]) -> list[dict]:
        ...

    def fin_indicators(self, thscode: str, report: str) -> dict:
        ...

    def income_statements(self, thscode: str, period: str = "annual",
                          limit: int = 5) -> list[dict]:
        ...

    def balance_sheets(self, thscode: str, period: str = "annual",
                       limit: int = 3) -> list[dict]:
        ...

    def cash_flow_statements(self, thscode: str, period: str = "annual",
                             limit: int = 3) -> list[dict]:
        ...

    def corp_actions(self, thscode: str) -> list[dict]:
        ...

    # --- market context -----------------------------------------------------
    def calendar(self) -> list[str]:
        """Trading days (YYYY-MM-DD), ascending, most recent last."""
        ...

    def index_kline(self, thscode: str, start_ms: int, end_ms: int) -> list[dict]:
        ...

    def index_quote(self, thscodes: list[str]) -> list[dict]:
        ...

    def index_constituents(self, index_thscode: str) -> list[dict]:
        ...

    def hot_rank_trend(self, thscode: str, start_date: str, end_date: str) -> list[dict]:
        ...

    # --- meta ---------------------------------------------------------------
    def has(self, capability: str) -> bool:
        ...


def require(provider: DataProvider, capability: str) -> None:
    if capability not in provider.capabilities:
        raise ProviderError("param", f"provider '{provider.name}' lacks capability '{capability}'")
