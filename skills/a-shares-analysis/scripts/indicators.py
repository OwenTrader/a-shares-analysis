#!/usr/bin/env python3
"""Pure pandas/numpy indicator engine for A-share DAILY bars (no TA-Lib).

Medium/long-term oriented — the data source only serves daily candles, so the
indicator set favours trend / regime / risk metrics over intraday timing:

  trend        MA5..MA250 stack, EMA/MACD, 60/250d regression slope, MA crosses
  momentum     RSI6/14, ROC windows, monthly returns
  volatility   ATR14(+pct), 20d realized vol, annualized vol, Bollinger %B
  range        250d high/low position, drawdown from 250d high
  volume       vol MA5/20/60, volume ratio, turnover MA20
  structure    swing pivots -> clustered support/resistance zones with touches

Every function takes bars as list[dict] (ascending, normalized Bar schema) and
returns JSON-serialisable values (NaN -> None). compute() returns the full
`analysis` block embedded into snapshots and digests.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

TRADING_DAYS = 250  # A-share annual trading-day count


def _frame(bars: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(bars)
    if df.empty:
        return df
    for col in ("open", "high", "low", "close", "volume", "turnover"):
        if col not in df.columns:
            df[col] = np.nan
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _last(series: pd.Series | None, digits: int = 4):
    if series is None or len(series) == 0:
        return None
    value = series.iloc[-1]
    if value is None or pd.isna(value):
        return None
    return round(float(value), digits)


def _sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def _wilder(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


def _rsi(close: pd.Series, n: int) -> pd.Series:
    delta = close.diff()
    gain = _wilder(delta.clip(lower=0.0), n)
    loss = _wilder((-delta).clip(lower=0.0), n)
    rs = gain / loss.replace(0.0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(loss != 0, 100.0)  # all-gain window -> RSI 100


def _pct(close: pd.Series, n: int):
    """n-bar percentage return; None when window unavailable."""
    if len(close) <= n:
        return None
    base = close.iloc[-1 - n]
    if not base or pd.isna(base) or base == 0:
        return None
    return round((float(close.iloc[-1]) / float(base) - 1) * 100, 2)


def _slope_pct(close: pd.Series, n: int):
    """Annualised-ish regression slope over last n bars, % per bar * 250.

    Robust trend measure: fit y=close on x=0..n-1, slope normalised by mean
    price so it is comparable across stocks. Returned as pct-per-year.
    """
    if len(close) < n or n < 10:
        return None
    y = close.iloc[-n:].astype(float).to_numpy()
    x = np.arange(n, dtype=float)
    slope = float(np.polyfit(x, y, 1)[0])
    mean = float(np.nanmean(y))
    if mean == 0 or np.isnan(mean):
        return None
    return round(slope / mean * 100 * TRADING_DAYS, 2)  # % of price per year


def _adx(df: pd.DataFrame, n: int = 14):
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift()).abs(),
        (df["low"] - df["close"].shift()).abs(),
    ], axis=1).max(axis=1)
    atr = _wilder(tr, n)
    plus_di = 100 * _wilder(plus_dm, n) / atr.replace(0.0, np.nan)
    minus_di = 100 * _wilder(minus_dm, n) / atr.replace(0.0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
    return _wilder(dx, n), plus_di, minus_di, atr


def _ma_cross_state(close: pd.Series, fast_n: int, slow_n: int) -> dict:
    """Golden/dead-cross events in the last 5 bars + current fast-vs-slow."""
    if len(close) < slow_n + 2:
        return {"state": None, "recent_cross": None}
    fast = _sma(close, fast_n)
    slow = _sma(close, slow_n)
    diff = (fast - slow).iloc[-6:]
    signs = np.sign(diff)
    cross = None
    for i in range(1, len(signs)):
        a, b = signs.iloc[i - 1], signs.iloc[i]
        if a in (-1.0, 0.0) and b == 1.0:
            cross = "golden"
        elif a in (1.0, 0.0) and b == -1.0:
            cross = "dead"
    state = None
    last = diff.iloc[-1]
    if not pd.isna(last):
        state = "bull" if last > 0 else "bear"
    return {"state": state, "recent_cross": cross}


def _pivots(df: pd.DataFrame, k: int = 5) -> list[dict]:
    """Swing highs/lows (fractal window k). Returns [{'type','date','price'}]."""
    out = []
    high, low = df["high"].to_numpy(), df["low"].to_numpy()
    dates = df["date"].to_numpy() if "date" in df.columns else np.arange(len(df))
    for i in range(k, len(df) - k):
        window_h = high[i - k:i + k + 1]
        window_l = low[i - k:i + k + 1]
        if high[i] == window_h.max() and (window_h == high[i]).sum() == 1:
            out.append({"type": "high", "date": str(dates[i]), "price": float(high[i])})
        if low[i] == window_l.min() and (window_l == low[i]).sum() == 1:
            out.append({"type": "low", "date": str(dates[i]), "price": float(low[i])})
    return out


def support_resistance(df: pd.DataFrame, last_close: float, atr: float | None,
                       k: int = 5, max_zones: int = 3) -> dict:
    """Cluster pivot levels into zones. Tolerance = max(0.5*ATR, 0.8% of price)."""
    pivots = _pivots(df, k)
    if not pivots:
        return {"supports": [], "resistances": []}
    tol = max(0.005 * last_close, 0.5 * atr) if (atr and last_close) else 0.005 * last_close
    levels = sorted(p["price"] for p in pivots)
    zones: list[list[float]] = []
    for price in levels:
        if zones and abs(price - np.mean(zones[-1])) <= tol:
            zones[-1].append(price)
        else:
            zones.append([price])
    ranked = sorted(
        ({"price": round(float(np.mean(z)), 2), "touches": len(z)} for z in zones),
        key=lambda z: z["touches"], reverse=True,
    )
    supports = [z for z in ranked if z["price"] < last_close][:max_zones]
    resistances = [z for z in ranked if z["price"] >= last_close][:max_zones]
    return {"supports": supports, "resistances": resistances}


def monthly_returns(df: pd.DataFrame, months: int = 12) -> list[dict]:
    """Month-end closes -> month-over-month pct, oldest first."""
    if len(df) < 40:
        return []
    month_end = df["close"].groupby(df["date"].str[:7]).last()
    pct = month_end.pct_change() * 100
    recent = pct.dropna().iloc[-months:]
    return [{"month": str(m), "pct": round(float(v), 2)} for m, v in recent.items()]


def relative_strength(stock_close: pd.Series, bench_close: pd.Series) -> dict:
    """stock/benchmark ratio behaviour over the shared window (60d/120d slope+return gap)."""
    n = min(len(stock_close), len(bench_close))
    if n < 65:
        return {"available": False}
    ratio = (stock_close.iloc[-n:] / bench_close.iloc[-n:]).astype(float)
    stock_r = _pct(stock_close, 120 if n > 120 else 60)
    bench_r = _pct(bench_close, 120 if n > 120 else 60)
    out: dict[str, Any] = {"available": True, "window_bars": int(n)}
    for label, win in (("rs_60d", 60), ("rs_120d", 120)):
        out[label] = {
            "ratio_slope_ann_pct": _slope_pct(ratio, win),
            "ratio_at_60d_high": bool(ratio.iloc[-win:].idxmax() == ratio.index[-1])
            if n >= win and len(ratio.iloc[-win:]) else None,
        }
    out["excess_return_120d_pct"] = (
        round(stock_r - bench_r, 2) if (stock_r is not None and bench_r is not None) else None
    )
    return out


def compute(bars: list[dict]) -> dict:
    """Full analysis block for one daily-bar series (ascending)."""
    df = _frame(bars)
    if df.empty or "close" not in df or df["close"].notna().sum() < 5:
        return {"error": "insufficient bars"}

    close, high, low = df["close"], df["high"], df["low"]
    last_close = float(close.iloc[-1])

    ma = {f"ma_{n}": _last(_sma(close, n), 3) for n in (5, 10, 20, 60, 120, 250)}
    ma_stack = None
    if all(ma[k] is not None for k in ("ma_5", "ma_20", "ma_60")):
        ma_stack = "bull" if ma["ma_5"] > ma["ma_20"] > ma["ma_60"] else (
            "bear" if ma["ma_5"] < ma["ma_20"] < ma["ma_60"] else "mixed")

    ema12, ema26 = _ema(close, 12), _ema(close, 26)
    dif = ema12 - ema26
    dea = _ema(dif, 9)
    hist = (dif - dea) * 2

    adx14, plus_di, minus_di, atr14 = _adx(df, 14)
    atr = _last(atr14, 4)
    atr_pct = round(atr / last_close * 100, 2) if (atr and last_close) else None

    ret = {f"ret_{n}d": _pct(close, n) for n in (5, 20, 60, 120, 250)}

    window250 = close.iloc[-250:]
    high250 = float(window250.max()) if len(window250) else None
    low250 = float(window250.min()) if len(window250) else None
    pos250 = None
    if high250 and low250 and high250 > low250:
        pos250 = round((last_close - low250) / (high250 - low250) * 100, 1)
    dd_from_high = (
        round((last_close / high250 - 1) * 100, 1) if high250 else None
    )

    logret = np.log(close.astype(float) / close.astype(float).shift(1))
    vol20 = float(logret.rolling(20).std().iloc[-1] * np.sqrt(TRADING_DAYS) * 100)
    vol60 = float(logret.rolling(60).std().iloc[-6:].mean() * np.sqrt(TRADING_DAYS) * 100)

    vol, turnover = df["volume"], df["turnover"]
    vol_ma5 = _last(_sma(vol, 5), 0)
    vol_ma20 = _last(_sma(vol, 20), 0)
    vol_ma60 = _last(_sma(vol, 60), 0)
    vol_ratio = round(vol_ma5 / vol_ma60, 2) if (vol_ma5 and vol_ma60) else None
    # recent-day volume ratio vs previous 5-day average (excludes today)
    prev5 = vol.iloc[-6:-1].mean()
    vol_vs_prev5 = round(float(vol.iloc[-1] / prev5), 2) if prev5 else None

    bb_mid = _sma(close, 20)
    bb_std = close.rolling(20, min_periods=20).std()
    bb_up, bb_lo = bb_mid + 2 * bb_std, bb_mid - 2 * bb_std
    pct_b = None
    if not pd.isna(bb_up.iloc[-1]) and bb_up.iloc[-1] != bb_lo.iloc[-1]:
        pct_b = round(float((last_close - bb_lo.iloc[-1]) / (bb_up.iloc[-1] - bb_lo.iloc[-1])), 2)

    sr = support_resistance(df, last_close, atr)

    return {
        "bars": int(len(df)),
        "last_date": str(df["date"].iloc[-1]) if "date" in df.columns else None,
        "last_close": round(last_close, 3),
        "moving_averages": ma,
        "ma_stack": ma_stack,
        "ma_cross_20_60": _ma_cross_state(close, 20, 60),
        "ma_cross_60_250": _ma_cross_state(close, 60, 250),
        "macd": {"dif": _last(dif, 4), "dea": _last(dea, 4), "hist": _last(hist, 4),
                 "hist_prev": _last(hist.iloc[:-1], 4),
                 "bias": ("bull" if (dif.iloc[-1] > dea.iloc[-1] and not pd.isna(dif.iloc[-1]))
                          else "bear" if not pd.isna(dif.iloc[-1]) else None)},
        "rsi": {"rsi_6": _last(_rsi(close, 6), 1), "rsi_14": _last(_rsi(close, 14), 1)},
        "adx": {"adx_14": _last(adx14, 1), "plus_di": _last(plus_di, 1),
                "minus_di": _last(minus_di, 1)},
        "atr": {"atr_14": atr, "atr_pct": atr_pct},
        "bollinger": {"mid": _last(bb_mid, 3), "upper": _last(bb_up, 3),
                      "lower": _last(bb_lo, 3), "pct_b": pct_b},
        "returns_pct": ret,
        "range_250d": {"high": high250, "low": low250,
                       "position_pct": pos250, "drawdown_from_high_pct": dd_from_high},
        "volatility": {"realized_vol_20d_ann_pct": round(vol20, 1) if not np.isnan(vol20) else None,
                       "realized_vol_60d_ann_pct": round(vol60, 1) if not np.isnan(vol60) else None},
        "regression_slope_ann_pct": {"slope_60d": _slope_pct(close, 60),
                                     "slope_250d": _slope_pct(close, 250)},
        "volume": {"vol_ma5": vol_ma5, "vol_ma20": vol_ma20, "vol_ma60": vol_ma60,
                   "vol_ratio_5v60": vol_ratio, "vol_vs_prev5": vol_vs_prev5,
                   "turnover_ma20": _last(_sma(turnover, 20), 0)},
        "structure": sr,
        "monthly_returns": monthly_returns(df),
    }
