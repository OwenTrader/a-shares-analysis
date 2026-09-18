"""journal.py — decision validation and settlement logic (offline)."""
from __future__ import annotations

import pytest

from journal import _settle_plan, _validate


def base_decision(**over):
    d = {
        "thscode": "600519.SH", "name": "贵州茅台", "date": "2026-09-17",
        "verdict": "BUY",
        "plans": [{"entry": 1500, "stop": 1420, "tp1": 1650, "tp2": 1780,
                   "shares": 200, "rrr_tp1": 1.875}],
    }
    d.update(over)
    return d


def test_validate_computes_rrr_and_flags():
    problems = _validate(base_decision())
    assert problems == []
    rrr = base_decision()["plans"][0]["rrr_tp1"]  # 150/80 = 1.875
    assert rrr == pytest.approx(1.875, abs=0.01)


def test_validate_rejects_bad_geometry():
    problems = _validate(base_decision(plans=[{"entry": 100, "stop": 110, "tp1": 120}]))
    assert any("stop must be below" in p for p in problems)
    problems = _validate(base_decision(plans=[{"entry": 100, "stop": 90, "tp1": 95}]))
    assert any("tp1 must be above" in p for p in problems)


def test_validate_rounds_to_lots():
    d = base_decision(plans=[{"entry": 100, "stop": 90, "tp1": 120, "shares": 250}])
    _validate(d)
    assert d["plans"][0]["shares"] == 200
    assert "取整" in d["plans"][0]["shares_note"]


def test_validate_wait_needs_no_plans():
    assert _validate(base_decision(verdict="WAIT", plans=[])) == []
    problems = _validate(base_decision(verdict="SHORT"))
    assert any("verdict" in p for p in problems)


def _bars(rows):
    """rows: (date, open, high, low, close) 5-tuples."""
    return [{"date": d, "open": o, "high": h, "low": lo, "close": c, "volume": 1, "turnover": 1}
            for d, o, h, lo, c in rows]


PLAN = {"entry": 100.0, "stop": 95.0, "tp1": 110.0, "tp2": 120.0}


def test_settle_stop_hit_first():
    bars = _bars([("2026-09-18", 99, 100, 94.5, 99)])   # gaps through stop on day 1
    out = _settle_plan(PLAN, bars)
    assert out["outcome"] == "stopped"
    assert out["hit_date"] == "2026-09-18"
    assert out["realized_pct"] == -5.0


def test_settle_tp1_then_tp2():
    bars = _bars([
        ("2026-09-18", 101, 111, 100, 110),
        ("2026-09-19", 112, 122, 111, 121),
    ])
    out = _settle_plan(PLAN, bars)
    assert out["outcome"] == "tp1_hit"
    assert out["tps_hit"] == ["tp1", "tp2"]
    assert out["hit_date"] == "2026-09-18"
    assert out["max_gain_pct"] == 22.0


def test_settle_open_position():
    bars = _bars([("2026-09-18", 101, 103, 99, 102), ("2026-09-19", 102, 104, 100, 103)])
    out = _settle_plan(PLAN, bars)
    assert out["outcome"] == "open"
    assert out["unrealized_pct"] == 3.0
    assert out["max_drawdown_pct"] == -1.0


def test_settle_stop_after_tp_keeps_tp_outcome():
    # tp1 hits first, later price collapses below stop — outcome stays tp1_hit
    bars = _bars([("2026-09-18", 101, 111, 100, 110), ("2026-09-19", 100, 101, 90, 91)])
    out = _settle_plan(PLAN, bars)
    assert out["outcome"] == "tp1_hit"
