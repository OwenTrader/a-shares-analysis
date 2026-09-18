"""profile.py — persistence, defaults, and dual-constraint position sizing."""
from __future__ import annotations

import json

import pytest

import profile as profile_mod
from profile import DEFAULTS, effective_profile, position_plan, save_profile


@pytest.fixture(autouse=True)
def isolated_profile_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(profile_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(profile_mod, "PROFILE_PATH", tmp_path / "profile.json")
    yield


def test_defaults_when_missing():
    p = effective_profile()
    assert p["is_default"] is True
    assert p["total_capital"] == 100_000
    assert p["max_position_pct"] == 10
    assert p["risk_pct"] == 2


def test_save_and_load_roundtrip():
    save_profile(300_000, 15, 2.5)
    p = effective_profile()
    assert p["is_default"] is False
    assert p["total_capital"] == 300_000
    assert p["max_position_pct"] == 15
    assert p["risk_pct"] == 2.5


def test_sizing_risk_binding():
    # 100万, 2% risk(=2万), entry 100 stop 90 -> risk allows 2000; cap 30% allows 3000
    out = position_plan(100, 90, {"total_capital": 1_000_000, "max_position_pct": 30, "risk_pct": 2})
    assert out["shares"] == 2000
    assert out["binding_constraint"] == "risk_pct"
    assert out["position_pct"] == pytest.approx(20.0)


def test_sizing_cap_binding():
    # cap 10% of 100万 at price 100 -> 1000 shares; risk budget (2%/10元=2000) is bigger
    out = position_plan(100, 90, {"total_capital": 1_000_000, "max_position_pct": 10, "risk_pct": 2})
    assert out["shares"] == 1000
    assert out["binding_constraint"] == "max_position_pct"


def test_sizing_not_executable_under_one_lot():
    # moutai-like prices with default profile -> 0 shares, must carry a warning
    out = position_plan(1215.7, 1146.5, {**DEFAULTS})
    assert out["shares"] == 0
    assert out["shares_by_risk"] == 0
    assert out["note"] and "不足最小交易单位" in out["note"]


def test_one_lot_thresholds_are_actionable():
    out = position_plan(1215.7, 1146.5, {**DEFAULTS})  # 10万/10%/2%
    assert out["cost_1lot"] == pytest.approx(121_570, rel=1e-3)
    assert out["cap_pct_1lot"] == pytest.approx(121.6, abs=0.1)   # >100% -> cap route infeasible
    assert out["risk_pct_1lot"] == pytest.approx(6.92, abs=0.01)
    assert out["required_capital_by_cap"] == pytest.approx(1_215_700, rel=1e-3)
    assert out["required_capital_by_risk"] == pytest.approx(346_000, rel=1e-3)  # 100*69.2/0.02
    assert out["min_capital_1lot"] == out["required_capital_by_cap"]  # cap binds harder
    # user's actual profile (10万/10%/3%): risk route threshold is lower
    out3 = position_plan(1215.7, 1146.5, {"total_capital": 100_000,
                                          "max_position_pct": 10, "risk_pct": 3})
    assert out3["required_capital_by_risk"] == pytest.approx(230_667, abs=2)  # 6920/0.03
    assert out3["min_capital_1lot"] == out3["required_capital_by_cap"]
