"""Offline test fixtures: sys.path setup, synthetic bars, FakeProvider.

No network, no API key — everything is deterministic.
"""
from __future__ import annotations

import sys
import types
from datetime import date, datetime, timedelta
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def trading_dates(n: int, end: date | None = None) -> list[str]:
    """n ascending weekday dates ending at `end` (weekends skipped, holidays ignored)."""
    end = end or date(2026, 9, 16)
    out, cur = [], end
    while len(out) < n:
        if cur.weekday() < 5:
            out.append(cur.isoformat())
        cur -= timedelta(days=1)
    return list(reversed(out))


def synth_bars(n: int, start_price: float = 10.0, drift: float = 0.001,
               end: date | None = None) -> list[dict]:
    """Deterministic bars: drift + sine wiggle (so swing pivots exist) + fixed wick/volume."""
    dates = trading_dates(n, end)
    bars, price = [], start_price
    for i, d in enumerate(dates):
        import math

        price *= 1 + drift + 0.004 * math.sin(i / 4.0)
        high, low = price * 1.01, price * 0.99
        if i == n // 2:  # plant one deep wick low to exercise pivots
            low = price * 0.94
        bars.append({
            "date": d, "open": round(price * 0.998, 3), "high": round(high, 3),
            "low": round(low, 3), "close": round(price, 3),
            "volume": 1_000_000 + (i % 5) * 100_000,
            "turnover": (1_000_000 + (i % 5) * 100_000) * price,
        })
    return bars


class FakeProvider:
    """Deterministic in-memory DataProvider used by pipeline tests."""

    name = "fake"
    capabilities = {
        "search", "daily_kline", "quote", "fund_kline", "fund_quote",
        "valuation", "fin_indicators",
        "income_statements", "balance_sheets", "cash_flow_statements",
        "corp_actions", "calendar", "index_kline", "index_quote",
        "index_constituents", "hot_rank_trend",
    }

    # fund universe entries surfaced when asset_type is a fund-*
    FUND_DB = [
        {"thscode": "512690.SH", "ticker": "512690", "name": "酒ETF",
         "exchange": "SH", "asset_type": "fund-etf", "list_date": "2019-05-29", "end_date": None},
        {"thscode": "510300.SH", "ticker": "510300", "name": "沪深300ETF",
         "exchange": "SH", "asset_type": "fund-etf", "list_date": "2012-05-28", "end_date": None},
    ]
    # stock/index universe
    db = [
        {"thscode": "600519.SH", "ticker": "600519", "name": "贵州茅台",
         "exchange": "SH", "asset_type": "a-share", "list_date": "2001-08-27", "end_date": None},
        {"thscode": "000001.SZ", "ticker": "000001", "name": "平安银行",
         "exchange": "SZ", "asset_type": "a-share", "list_date": "1991-04-03", "end_date": None},
        {"thscode": "601318.SH", "ticker": "601318", "name": "中国平安",
         "exchange": "SH", "asset_type": "a-share", "list_date": "2007-03-01", "end_date": None},
        {"thscode": "000001.SH", "ticker": "000001", "name": "上证指数",
         "exchange": "SH", "asset_type": "a-share-index", "list_date": "1990-12-19", "end_date": None},
    ]

    def __init__(self, bars: list[dict] | None = None, benchmark_bars: list[dict] | None = None):
        self.bars = bars or synth_bars(300, drift=0.002)  # clear uptrend
        self.benchmark_bars = benchmark_bars or synth_bars(300, start_price=4000, drift=0.0004)
        self.last_bars = self.bars
        self.calls: list[str] = []

    def has(self, capability: str) -> bool:
        return capability in self.capabilities

    def search(self, q, asset_type=None, limit=10):
        self.calls.append(f"search:{q}")
        q = q.upper()
        hits = [c for c in self.db if q in c["thscode"].upper() or q in (c["name"] or "")
                or q == c["ticker"]]
        if asset_type:
            fund_types = {"fund-etf", "fund-lof", "fund-otc", "fund-reits"}
            if asset_type in fund_types:
                hits = [c for c in self.FUND_DB
                        if q in c["thscode"].upper() or q in (c["name"] or "") or q == c["ticker"]]
            else:
                hits = [c for c in hits if c["asset_type"] == asset_type]
        return hits[:limit]

    def daily_kline(self, thscode, start_ms, end_ms, adjust="forward"):
        self.calls.append(f"daily_kline:{thscode}")
        self.last_bars = self.bars
        return self.bars

    def fund_kline(self, thscode, start_ms, end_ms):
        self.calls.append(f"fund_kline:{thscode}")
        self.last_bars = self.bars
        return self.bars

    def fund_quote(self, thscode):
        self.calls.append("fund_quote")
        last, prev = self.bars[-1], self.bars[-2]
        return {"thscode": thscode, "ticker": thscode.split(".")[0],
                "last": last["close"], "chg": round(last["close"] - prev["close"], 3),
                "chg_pct": round((last["close"] / prev["close"] - 1) * 100, 2),
                "open": last["open"], "high": last["high"], "low": last["low"],
                "prev": prev["close"], "volume": last["volume"], "turnover": last["turnover"]}

    def quote(self, thscodes):
        self.calls.append("quote")
        last = self.bars[-1]
        prev = self.bars[-2]
        return [{"thscode": thscodes[0], "ticker": thscodes[0].split(".")[0],
                 "last": last["close"], "chg": round(last["close"] - prev["close"], 3),
                 "chg_pct": round((last["close"] / prev["close"] - 1) * 100, 2),
                 "open": last["open"], "high": last["high"], "low": last["low"],
                 "prev": prev["close"], "volume": last["volume"], "turnover": last["turnover"]}]

    def valuation(self, thscodes):
        self.calls.append("valuation")
        return [{"thscode": thscodes[0], "name": "贵州茅台", "pe_ttm": 21.4, "pe_mrq": 20.9,
                 "pb_mrq": 7.2, "ps_ttm": 10.3, "pcf_ttm": 19.8}]

    def fin_indicators(self, thscode, report):
        self.calls.append(f"fin_indicators:{report}")
        if report == "2026-2":
            raise_error("no_data", "not disclosed")
        return {"report": report, "abilities": [
            {"ability": "growth", "indicators": [
                {"index_id": "net_profit_yoy_growth_ratio", "value": "15.20"},
                {"index_id": "operating_income_yoy_growth_ratio", "value": "12.10"}]},
            {"ability": "profitability", "indicators": [
                {"index_id": "index_weighted_avg_roe", "value": "30.50"},
                {"index_id": "sale_gross_margin", "value": "91.50"}]},
        ]}

    def income_statements(self, thscode, period="annual", limit=5):
        self.calls.append(f"income:{period}")
        years = range(2022, 2027) if period == "annual" else range(24, 32)
        items = []
        for i, y in enumerate(list(years)[-limit:]):
            items.append({
                "fiscal_year": y if period == "annual" else None,
                "period_end_ms": 1735660800000 if period == "annual" else int(datetime(2026, 9, 30).timestamp() * 1000),
                "operating_income": 100e8 * (1.1 ** i),
                "parent_holder_net_profit": 50e8 * (1.15 ** i),
                "basic_eps": 30 + i,
            })
        return items

    def balance_sheets(self, thscode, period="annual", limit=3):
        self.calls.append("balance")
        return [{"fiscal_year": 2025, "assets_total": 2000e8, "total_debt": 300e8,
                 "holder_equity_total": 1700e8, "cash": 600e8}]

    def cash_flow_statements(self, thscode, period="annual", limit=3):
        self.calls.append("cashflow")
        return [{"fiscal_year": 2025, "act_cash_flow_net": 90e8,
                 "invest_cf_net": -30e8, "financing_cf_net": -40e8,
                 "pay_dividends_profits_interest_cash": 60e8}]

    def corp_actions(self, thscode):
        self.calls.append("corp_actions")
        return [{"ex_date": "2026-06-20", "dividend_per_share": 27.0, "per_share_bonus": 0},
                {"ex_date": "2025-06-20", "dividend_per_share": 25.0, "per_share_bonus": 0}]

    def calendar(self):
        self.calls.append("calendar")
        return trading_dates(250)  # ascending weekdays, last = 2026-09-16

    def index_kline(self, thscode, start_ms, end_ms):
        self.calls.append(f"index_kline:{thscode}")
        return self.benchmark_bars

    def index_quote(self, thscodes):
        return self.quote(thscodes)

    def index_constituents(self, index_thscode):
        return [{"thscode": "600519.SH", "ticker": "600519", "name": "贵州茅台"}]

    def hot_rank_trend(self, thscode, start_date, end_date):
        self.calls.append("hot")
        dates = trading_dates(40)
        return [{"date": d, "rank": 500 + (i % 7) * 10} for i, d in enumerate(dates)]


def raise_error(kind: str, message: str):
    from providers.base import ProviderError

    raise ProviderError(kind, message)
