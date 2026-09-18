"""v2.2 US-stock support: yahoo provider, SEC fundamentals, routing, us snapshot."""
from __future__ import annotations

import json
from datetime import datetime

import pytest

from ash_common import CST
from conftest import FakeProvider
from fetch_snapshot import build_snapshot

# ------------------------------------------------------------------ helpers
def yahoo_chart_body(tz="America/New_York", currency="USD", symbol="AAPL"):
    # 3 daily bars (2026-09-15/16/17 in exchange tz), adjclose present
    def ts(day):
        from ash_common import date_to_ms
        return date_to_ms(f"2026-09-{day}") // 1000 + 12 * 3600  # noon CST = midnight ET
    return json.dumps({"chart": {"result": [{
        "meta": {"currency": currency, "symbol": symbol,
                 "exchangeTimezoneName": tz,
                 "regularMarketPrice": 178.5, "chartPreviousClose": 177.0,
                 "regularMarketTime": ts("17") + 61200},
        "timestamp": [ts("15"), ts("16"), ts("17")],
        "indicators": {"quote": [{
            "open": [176.0, 177.0, 177.5], "high": [177.0, 178.0, 179.0],
            "low": [175.5, 176.5, 177.0], "close": [176.5, 177.5, 178.0],
            "volume": [1000, 1100, 1200]}],
            "adjclose": [{"adjclose": [176.5, 177.5, 178.2]}]},
    }], "error": None}})


def search_body():
    return json.dumps({"quotes": [
        {"symbol": "AAPL", "exchange": "NMS", "quoteType": "EQUITY",
         "shortname": "Apple Inc.", "longname": "Apple Inc."},
        {"symbol": "0700.HK", "exchange": "HKG", "quoteType": "EQUITY",
         "longname": "Tencent Holdings Limited"}]})


def make_yahoo(responses):
    from providers.yahoo import YahooProvider

    calls = []
    def send(path, params):
        calls.append((path, params))
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
    return YahooProvider(send=send, politeness_s=0.0), calls


# ------------------------------------------------------------------ yahoo
def test_yahoo_search_maps_us_and_hk():
    y, _ = make_yahoo([search_body()])
    hits = y.search("Apple")
    kinds = {h["thscode"]: h["asset_type"] for h in hits}
    assert kinds["AAPL"] == "us-stock" and kinds["0700.HK"] == "hk-stock"
    assert hits[0]["name"] == "Apple Inc."


def test_yahoo_daily_kline_uses_exchange_tz_and_adjclose():
    y, calls = make_yahoo([yahoo_chart_body()])
    bars = y.daily_kline("AAPL", 0, 9999999999999)
    assert [b["date"] for b in bars] == ["2026-09-15", "2026-09-16", "2026-09-17"]
    assert bars[-1]["close"] == 178.2          # adjclose preferred for TA
    assert bars[-1]["volume"] == 1200
    assert y.market_meta("AAPL")["exchangeTimezoneName"] == "America/New_York"
    assert "chart/AAPL" in calls[0][0]


def test_yahoo_quote_derives_from_chart_meta():
    y, _ = make_yahoo([yahoo_chart_body()])
    q = y.quote(["AAPL"])[0]
    assert q["last"] == 178.5 and q["prev"] == 177.0
    assert q["currency"] == "USD" and q["market_tz"] == "America/New_York"
    assert q["chg_pct"] == pytest.approx(0.85, abs=0.01)
    assert q["as_of"]


def test_yahoo_retries_on_rate_limit(monkeypatch):
    import providers.yahoo as ym
    monkeypatch.setattr(ym.time, "sleep", lambda *_: None)
    limited = json.dumps({"finance": {"error": {"code": "Too Many Requests"}}})
    y, _ = make_yahoo([limited, search_body()])
    assert y.search("Apple")                    # succeeded after one retry


def test_yahoo_index_kline_uses_raw_close():
    y, _ = make_yahoo([yahoo_chart_body(symbol="^GSPC")])
    bars = y.index_kline("^GSPC", 0, 9999999999999)
    assert bars[-1]["close"] == 178.0           # raw close for indices


# ------------------------------------------------------------------ SEC
class FakeSec:
    name = "sec"
    capabilities = {"sec_fundamentals"}

    def has(self, c):
        return c in self.capabilities

    def fundamentals(self, symbol):
        return {"symbol": symbol, "cik": 320193, "shares_outstanding": 15_000_000_000,
                "income_annual": [
                    {"fiscal_year": 2023, "end": "2023-09-30",
                     "revenue": 100e9, "net_income": 25e9, "eps_diluted": 6.1},
                    {"fiscal_year": 2024, "end": "2024-09-30",
                     "revenue": 110e9, "net_income": 28e9, "eps_diluted": 7.0}],
                "balance_latest": {"end": "2024-09-30", "assets": 350e9,
                                   "liabilities": 150e9, "cash": 60e9,
                                   "long_term_debt": 90e9},
                "flows_latest": {"end": "2024-09-30",
                                 "operating_cf": 110e9, "capex": -10e9}}


def test_sec_provider_parses_companyfacts(tmp_path, monkeypatch):
    from providers.sec import SecProvider, TICKER_CACHE

    monkeypatch.setattr("providers.sec.TICKER_CACHE", tmp_path / "tickers.json")
    tickers = json.dumps({"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple"},
                          "1": {"cik_str": 1, "ticker": "MSFT", "title": "Microsoft"}})

    def fy(tag, entries):
        return {"units": {"USD" if tag != "Shares" else "shares": entries}}

    facts = json.dumps({"facts": {"us-gaap": {
        "Revenues": fy("Revenues", [
            {"start": "2022-10-01", "end": "2023-09-30", "val": 100e9,
             "fy": 2023, "fp": "FY", "form": "10-K", "filed": "2023-11-01"},
            {"start": "2023-10-01", "end": "2024-09-30", "val": 110e9,
             "fy": 2024, "fp": "FY", "form": "10-K", "filed": "2024-11-01"}]),
        "NetIncomeLoss": fy("NI", [
            {"start": "2023-10-01", "end": "2024-09-30", "val": 28e9,
             "fy": 2024, "fp": "FY", "form": "10-K", "filed": "2024-11-01"}]),
        "Assets": fy("Assets", [
            {"end": "2024-09-30", "val": 350e9,   # instant fact: no start key
             "fy": 2024, "fp": "FY", "form": "10-K", "filed": "2024-11-01"}]),
    }, "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
        {"end": "2026-07-31", "val": 15_000_000_000, "form": "10-Q"}]}}}}})
    payloads = [tickers, facts]
    sec = SecProvider(getter=lambda url: payloads.pop(0).encode(), sleep=lambda *_: None)
    out = sec.fundamentals("AAPL")
    assert out["cik"] == 320193 and out["shares_outstanding"] == 15e9
    assert out["income_annual"][0]["revenue"] == 100e9
    assert out["balance_latest"]["assets"] == 350e9


# ------------------------------------------------------------------ routing
def test_market_routes():
    from providers import route_market
    assert route_market("us-stock") == ("yahoo", "sec")
    assert route_market("hk-stock") == ("yahoo", None)
    assert route_market("a-share") == ("fuyao", "fuyao")
    assert route_market("fund-etf") == ("fuyao", "fuyao")


# ------------------------------------------------------------------ us snapshot
class FakeYahoo(FakeProvider):
    """FakeProvider body with yahoo-flavoured identity + meta for the us branch."""
    name = "yahoo"
    db = FakeProvider.db + [
        {"thscode": "AAPL", "ticker": "AAPL", "name": "Apple Inc.",
         "exchange": "NMS", "asset_type": "us-stock",
         "list_date": "1980-12-12", "end_date": None},
    ]

    def market_meta(self, symbol):
        return {"exchangeTimezoneName": "America/New_York"}


NOW = datetime(2026, 9, 18, 9, 0, tzinfo=CST)  # 2026-09-17 21:00 ET (Thu)


def test_snapshot_us_stock_full():
    provider = FakeYahoo()
    snap = build_snapshot(provider, "AAPL", "us-stock", 300, "forward",
                          "^GSPC", set(), NOW, fundamentals_provider=FakeSec(),
                          market="US")
    m = snap["meta"]
    assert m["market"] == "US" and m["currency"] == "USD" and m["lot_size"] == 1
    assert m["benchmark_thscode"] == "^GSPC" if False else m["benchmark_thscode"] == "^GSPC"
    assert snap["quote"]["thscode"] == "AAPL"
    # SEC adapted into existing schema
    stmts = snap["statements"]
    assert stmts["income_annual"][-1]["operating_income"] == 110e9
    assert stmts["balance_annual"][0]["assets_total"] == 350e9
    val = snap["valuation"]
    px = snap["quote"]["last"]                       # quote derives from fixture bars
    assert val["pe_fy"] == pytest.approx(px * 15e9 / 28e9, rel=1e-3)
    assert val["ps_fy"] == pytest.approx(px * 15e9 / 110e9, abs=0.01)
    # quote.last comes from FakeProvider bars; freshness uses NY tz weekday rule
    assert snap["quality"]["ok"] is True
    # a-share-only sections absent
    for gone in ("fin_indicators", "corp_actions", "hot_rank"):
        assert gone not in snap


def test_snapshot_us_stale_detection():
    from conftest import synth_bars
    from datetime import date
    provider = FakeYahoo(bars=synth_bars(300, end=date(2026, 9, 8)))
    snap = build_snapshot(provider, "AAPL", "us-stock", 300, "forward",
                          "^GSPC", set(), NOW, fundamentals_provider=None, market="US")
    q = snap["quality"]
    assert q["days_behind"] >= 5 and q["ok"] is False
    assert any("长假日" in n or "滞后" in n for n in q["notes"])


# ------------------------------------------------------------------ sizing
def test_position_plan_us_lot_one():
    from profile import position_plan, DEFAULTS
    out = position_plan(178.0, 170.0, {**DEFAULTS}, lot_size=1)
    assert out["lot_size"] == 1
    # 10万*10%/178 = 56 shares by cap; risk budget larger -> cap binds
    assert out["shares"] == 56
    assert out["binding_constraint"] == "max_position_pct"
    assert out["note"] is None                      # 1-share lot always executable
