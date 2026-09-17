"""End-to-end offline: fetch_snapshot.build_snapshot + make_digest.build_digest on FakeProvider.

All timestamps pinned to a fixed NOW (2026-09-17 CST) so freshness/report-period
assertments are deterministic regardless of the machine clock.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from conftest import FakeProvider, synth_bars

from ash_common import CST, dump_json
from fetch_snapshot import build_snapshot, recent_report_codes
from make_digest import build_digest

NOW = datetime(2026, 9, 17, 15, 0, tzinfo=CST)


def test_recent_report_codes_respect_disclosure_deadlines():
    codes = recent_report_codes(datetime(2026, 9, 17), n=6)
    assert codes[0] == "2026-2"           # 中报 8/31 已过
    assert "2026-3" not in codes           # 三季报 10/31 未到
    assert codes[:6] == ["2026-2", "2026-1", "2025-4", "2025-3", "2025-2", "2025-1"]


def test_snapshot_full_structure():
    provider = FakeProvider()
    snap = build_snapshot(provider, "600519.SH", "a-share", 300, "forward",
                          "000300.SH", set(), NOW)

    assert snap["meta"]["name"] == "贵州茅台"
    assert snap["meta"]["provider"] == "fake"
    assert snap["meta"]["window"]["bars"] == 300

    q = snap["quality"]
    assert q["ok"] is True
    assert q["fresh"] is True
    assert q["sections_errors"] == []
    assert q["notes"] == []

    assert len(snap["daily"]["bars"]) == 300
    assert snap["daily"]["analysis"]["ma_stack"] == "bull"  # drift 0.002 uptrend
    assert snap["quote"]["thscode"] == "600519.SH"
    assert snap["valuation"]["pe_ttm"] == 21.4
    assert snap["fin_indicators"][0]["report"] == "2026-1"   # 2026-2 raises no_data -> skipped
    assert len(snap["fin_indicators"]) == 5
    assert "income_annual" in snap["statements"]
    assert snap["corp_actions"][0]["ex_date"] == "2026-06-20"
    assert snap["hot_rank"]
    bench = snap["benchmark"]
    assert bench["thscode"] == "000300.SH"
    assert bench["relative_strength"]["excess_return_120d_pct"] > 0  # stock drifts harder


def test_snapshot_detects_stale_bars_as_suspension():
    provider = FakeProvider(bars=synth_bars(300, end=date(2026, 9, 1)))
    snap = build_snapshot(provider, "600519.SH", "a-share", 300, "forward",
                          "000300.SH", set(), NOW)
    q = snap["quality"]
    assert q["fresh"] is False
    assert q["days_behind"] >= 5
    assert q["ok"] is False
    assert any("停牌" in n for n in q["notes"])


def test_snapshot_soft_degrades_missing_fundamentals():
    provider = FakeProvider()

    def broken_valuation(thscodes):
        from providers.base import ProviderError

        raise ProviderError("upstream", "5003 down")

    provider.valuation = broken_valuation
    snap = build_snapshot(provider, "600519.SH", "a-share", 300, "forward",
                          "000300.SH", set(), NOW)
    assert "valuation" not in snap
    assert any(e["section"] == "valuation" for e in snap["quality"]["sections_errors"])
    assert snap["quality"]["ok"] is True  # core kline intact -> analysis may proceed


def test_snapshot_index_target_skips_stock_sections():
    provider = FakeProvider()
    snap = build_snapshot(provider, "000001.SH", "a-share-index", 300, "forward",
                          "000300.SH", set(), NOW)
    assert "valuation" not in snap
    assert "fin_indicators" not in snap
    assert snap["daily"]["bars"]  # index kline via index_kline


def test_digest_from_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr("make_digest.now_cst", lambda: NOW)
    provider = FakeProvider()
    snap = build_snapshot(provider, "600519.SH", "a-share", 300, "forward",
                          "000300.SH", set(), NOW)
    path = dump_json(tmp_path / "snapshot.json", snap)
    digest = build_digest(path)

    assert digest["identity"]["name"] == "贵州茅台"
    assert digest["data_quality"]  # non-empty one-liner
    assert digest["technical"]["ma_stack"] == "bull"
    assert len(digest["recent_bars"]) == 30
    assert digest["fundamentals"]["valuation"]["pe_ttm"] == 21.4
    assert digest["fundamentals"]["fin_indicators_recent"][0]["加权ROE%"] == 30.5
    # revenue grows 10% per year in the fixture
    annual = digest["fundamentals"]["income_annual"]
    assert all(row["revenue_yoy_pct"] == 10.0 for row in annual[1:])
    # ttm dividend = only the 2026 event (27.0), yield vs last close
    assert digest["fundamentals"]["dividends"]["ttm_per_share"] == 27.0
    assert digest["fundamentals"]["dividends"]["yield_ttm_pct"] > 0
    assert digest["sentiment"]["rank_latest"] == 540
    assert digest["benchmark"]["thscode"] == "000300.SH"
