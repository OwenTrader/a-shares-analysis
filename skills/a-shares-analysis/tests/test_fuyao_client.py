"""fuyao provider client — envelope handling, retries, mappings (offline transport)."""
from __future__ import annotations

import json

import pytest

from providers.base import ProviderError
from providers.fuyao import FuyaoProvider


def envelope(code=0, data=None, message="success"):
    return json.dumps({"code": code, "message": message, "request_id": "t", "data": data})


def make_provider(responses, calls=None):
    """responses: list of raw body strings returned by the fake transport."""
    calls = calls if calls is not None else []

    def send(path, params):
        calls.append((path, params))
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return FuyaoProvider("test-key", send=send, politeness_s=0.0, max_retries=3)


def test_success_returns_data():
    p = make_provider([envelope(0, {"item": [{"thscode": "600519.SH", "name": "贵州茅台"}]})])
    hits = p.search("茅台")
    assert hits[0]["thscode"] == "600519.SH"
    assert hits[0]["name"] == "贵州茅台"
    assert hits[0]["exchange"] is None


def test_param_error_raises_immediately(monkeypatch):
    monkeypatch.setattr("providers.fuyao.time.sleep", lambda *_: None)
    p = make_provider([envelope(1001, None, "missing q")])
    with pytest.raises(ProviderError) as ei:
        p.search("", limit=1)
    assert ei.value.kind == "param"


def test_rate_limit_retries_then_succeeds(monkeypatch):
    slept = []
    monkeypatch.setattr("providers.fuyao.time.sleep", lambda s: slept.append(s))
    p = make_provider([
        envelope(4001, None, "rate limited"),
        envelope(0, {"item": []}),
    ])
    assert p.calendar() == []
    assert len(slept) == 1  # backoff before retry


def test_auth_error_no_retry(monkeypatch):
    monkeypatch.setattr("providers.fuyao.time.sleep", lambda *_: None)
    p = make_provider([envelope(2001, None, "bad key")])
    with pytest.raises(ProviderError) as ei:
        p.quote(["600519.SH"])
    assert ei.value.kind == "auth"


def test_upstream_exhausts_retries(monkeypatch):
    monkeypatch.setattr("providers.fuyao.time.sleep", lambda *_: None)
    p = make_provider([envelope(5003, None, "upstream down")] * 4)
    with pytest.raises(ProviderError) as ei:
        p.quote(["600519.SH"])
    assert ei.value.kind == "upstream"


def test_daily_kline_maps_bars_and_dates():
    body = envelope(0, {"item": [{
        "date_ms": 1716134400000,  # 2024-05-20 00:00 Asia/Shanghai
        "open_price": 1611.6, "high_price": 1626.6, "low_price": 1601.7,
        "close_price": 1602.6, "volume": 3142572.0, "turnover": 5401389334.87,
    }]})
    p = make_provider([body])
    bars = p.daily_kline("600519.SH", 0, 9999999999999)
    assert bars[0]["date"] == "2024-05-20"
    assert bars[0]["close"] == 1602.6
    assert bars[0]["volume"] == 3142572.0


def test_calendar_normalizes_yyyymmdd():
    body = envelope(0, {"item": [{"date_ms": 1, "date": "20250526"}]})
    p = make_provider([body])
    assert p.calendar() == ["2025-05-26"]


def test_corp_actions_maps_dates():
    body = envelope(0, {"thscode": "600519.SH", "ticker": "600519", "item": [
        {"ticker": "600519", "ex_date_ms": 1766073600000,
         "dividend_per_share": 23.957, "per_share_bonus": 0},
    ]})
    p = make_provider([body])
    events = p.corp_actions("600519.SH")
    assert events[0]["ex_date"] == "2025-12-19"
    assert events[0]["dividend_per_share"] == 23.957


def test_capabilities_exclude_unopened_modules():
    p = make_provider([])
    assert "daily_kline" in p.capabilities
    assert not any(c.startswith(("capital", "high_freq")) for c in p.capabilities)
    assert p.has("hot_rank_trend")
