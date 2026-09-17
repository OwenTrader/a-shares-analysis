"""indicators.py — pure engine tests on synthetic daily bars."""
from __future__ import annotations

import math

from conftest import synth_bars, trading_dates

from indicators import (
    compute,
    monthly_returns,
    relative_strength,
    support_resistance,
    _frame,
    _ma_cross_state,
    _pct,
    _sma,
)


def test_sma_known_value():
    closes = _frame([{"close": i, "date": f"2026-01-{i:02d}"} for i in range(1, 11)])["close"]
    assert math.isclose(_sma(closes, 5).iloc[-1], (6 + 7 + 8 + 9 + 10) / 5)


def test_pct_windows():
    closes = _frame([{"close": float(i + 1), "date": f"d{i}"} for i in range(10)])["close"]
    # 10 vs 5 -> +100%
    assert _pct(closes, 5) == 100.0
    assert _pct(closes, 100) is None  # window longer than series


def test_compute_uptrend_shape():
    bars = synth_bars(300, drift=0.002)  # steady uptrend with wiggle
    out = compute(bars)
    assert out["bars"] == 300
    assert out["last_close"] == bars[-1]["close"]
    assert out["ma_stack"] == "bull"
    assert out["moving_averages"]["ma_250"] is not None
    assert out["returns_pct"]["ret_20d"] > 0
    # near top of 250d range after steady climb
    assert out["range_250d"]["position_pct"] > 85
    assert out["range_250d"]["drawdown_from_high_pct"] >= -1.5
    # regression slope positive on uptrend
    assert out["regression_slope_ann_pct"]["slope_60d"] > 0
    # structure has zones on both sides for a trending series
    assert isinstance(out["structure"]["supports"], list)


def test_compute_short_series_degrades_gracefully():
    out = compute(synth_bars(80))
    assert out["moving_averages"]["ma_250"] is None   # not enough data -> null, not 0
    assert out["returns_pct"]["ret_250d"] is None
    assert out["range_250d"]["high"] is not None      # 80-bar window still yields a range


def test_compute_downtrend_is_bear():
    out = compute(synth_bars(200, start_price=50, drift=-0.002))
    assert out["ma_stack"] == "bear"
    assert out["regression_slope_ann_pct"]["slope_60d"] < 0
    assert out["range_250d"]["position_pct"] < 15


def test_ma_cross_state_bull_on_uptrend():
    closes = _frame([{"close": float(i), "date": f"d{i}"} for i in range(1, 81)])["close"]
    state = _ma_cross_state(closes, 20, 60)
    assert state["state"] == "bull"


def test_support_resistance_separates_sides():
    bars = synth_bars(120, drift=0.0)  # sideways with wicks
    last = bars[-1]["close"]
    out = support_resistance(_frame(bars), last, atr=None)
    for s in out["supports"]:
        assert s["price"] < last
    for r in out["resistances"]:
        assert r["price"] >= last
    assert out["supports"] and out["resistances"]


def test_monthly_returns_spans_months():
    bars = synth_bars(70)  # ~3.5 months of trading days
    rows = monthly_returns(_frame(bars))
    assert len(rows) >= 2
    assert all(len(r["month"]) == 7 for r in rows)  # YYYY-MM


def test_relative_strength_identical_series():
    import pandas as pd

    s = pd.Series([float(i) for i in range(1, 130)])
    rs = relative_strength(s, s.copy())
    assert rs["available"] is True
    assert rs["excess_return_120d_pct"] == 0.0


def test_relative_strength_outperformer():
    import pandas as pd

    bench = pd.Series([float(i) for i in range(1, 130)])
    stock = bench * (1.0 + 0.001 * bench.index)  # accelerating outperformance
    rs = relative_strength(stock, bench)
    assert rs["excess_return_120d_pct"] > 0
