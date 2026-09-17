"""Phase 1 fund support: ETF kline/quote provider, resolve fallback, snapshot branch."""
from __future__ import annotations

from datetime import datetime

from conftest import FakeProvider

from ash_common import CST
from fetch_snapshot import build_snapshot
from providers.base import ProviderError
from resolve_ticker import resolve

NOW = datetime(2026, 9, 17, 15, 0, tzinfo=CST)


# ---------------------------------------------------------------- provider layer
def test_fuyao_fund_capabilities_and_endpoints():
    from providers.fuyao import FuyaoProvider

    p = FuyaoProvider("k", send=lambda path, params: (_ for _ in ()).throw(
        ProviderError("param", "unused")))
    assert p.has("fund_kline") and p.has("fund_quote")


def test_fuyao_fund_kline_maps_bars():
    import json

    from providers.fuyao import FuyaoProvider

    body = json.dumps({"code": 0, "message": "success", "request_id": "t", "data": {
        "item": [{"date_ms": 1784131200000, "open_price": 0.751, "high_price": 0.762,
                  "low_price": 0.749, "close_price": 0.758,
                  "volume": 1657822800, "turnover": 1256620000.5}]}})
    p = FuyaoProvider("k", send=lambda path, params: body, politeness_s=0.0)
    bars = p.fund_kline("512690.SH", 0, 9999999999999)
    assert bars[0]["date"] == "2026-07-16" or bars[0]["date"].startswith("2026")
    assert bars[0]["close"] == 0.758


# ---------------------------------------------------------------- resolve fallback
def test_resolve_fund_etf_direct():
    out = resolve(FakeProvider(), "酒ETF", "fund-etf")
    assert out["status"] == "verified"
    assert out["target"]["thscode"] == "512690.SH"
    assert out["target"]["asset_type"] == "fund-etf"


def test_resolve_auto_falls_back_to_fund_when_a_share_misses():
    provider = FakeProvider()
    out = resolve(provider, "沪深300ETF", "a-share")   # no --type given by user
    assert out["status"] in ("verified", "ambiguous")
    assert out["asset_type"] == "fund-etf"             # switched universe
    assert any(c["thscode"] == "510300.SH" for c in out["candidates"])


# ---------------------------------------------------------------- snapshot branch
def test_snapshot_fund_etf_tech_only():
    provider = FakeProvider()
    snap = build_snapshot(provider, "512690.SH", "fund-etf", 300, "forward",
                          "000300.SH", set(), NOW)
    assert snap["meta"]["asset_type"] == "fund-etf"
    assert "fund_kline:512690.SH" in provider.calls      # routed to fund kline
    assert "fund_quote" in provider.calls
    assert len(snap["daily"]["bars"]) == 300
    assert snap["daily"]["analysis"]["last_close"]        # indicators work on ETF bars
    assert snap["quote"]["thscode"] == "512690.SH"
    # stock-only sections are absent (graceful degradation, no errors)
    for gone in ("valuation", "fin_indicators", "statements", "corp_actions", "hot_rank"):
        assert gone not in snap
    assert snap["quality"]["ok"] is True
    assert snap["benchmark"]["thscode"] == "000300.SH"    # RS still computed
    assert snap["benchmark"].get("relative_strength", {}).get("available") is True


def test_snapshot_fund_etf_window_guard():
    provider = FakeProvider()
    snap = build_snapshot(provider, "512690.SH", "fund-etf", 1300, "forward",
                          "000300.SH", set(), NOW)
    assert any("5 个自然年" in n for n in snap["quality"]["notes"])
    assert snap["meta"]["window"]["bars"] == 300          # fixture only has 300 bars


def test_journal_bars_since_routes_fund():
    import journal
    from conftest import FakeProvider as FP

    provider = FP()
    decision = {"date": "2026-09-01", "asset_type": "fund-etf"}
    journal._bars_since(provider, decision, "512690.SH", 9999999999999)
    assert "fund_kline:512690.SH" in provider.calls
    decision2 = {"date": "2026-09-01", "asset_type": "a-share"}
    journal._bars_since(provider, decision2, "600519.SH", 9999999999999)
    assert "daily_kline:600519.SH" in provider.calls
