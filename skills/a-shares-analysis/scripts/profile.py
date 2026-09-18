#!/usr/bin/env python3
"""User profile: total capital & position-sizing preferences, persisted at data/profile.json.

The skill asks for these ONCE (AskUserQuestion at 参数确认 step), stores them,
and reuses them for every later analysis. Defaults when the user declines:

  total_capital    = 100_000   (10 万)
  max_position_pct = 10        (单次最多使用 10% 资金建一只标的)
  risk_pct         = 2         (单笔交易风险预算 2%)

CLI:
  python profile.py --show                          # JSON dump (or {status: none})
  python profile.py --set --capital 300000 --max-position-pct 15 [--risk-pct 2]
  python profile.py --clear
"""
from __future__ import annotations

import argparse
import sys

from ash_common import DATA_DIR, emit, force_utf8_stdout, now_cst

PROFILE_PATH = DATA_DIR / "profile.json"
DEFAULTS = {"total_capital": 100_000.0, "max_position_pct": 10.0, "risk_pct": 2.0}


def load_profile() -> dict | None:
    if not PROFILE_PATH.is_file():
        return None
    from ash_common import load_json

    data = load_json(PROFILE_PATH)
    for key, default in DEFAULTS.items():
        if not isinstance(data.get(key), (int, float)) or data[key] <= 0:
            data[key] = default
    return data


def save_profile(capital: float, max_position_pct: float, risk_pct: float) -> dict:
    profile = {
        "total_capital": float(capital),
        "max_position_pct": float(max_position_pct),
        "risk_pct": float(risk_pct),
        "updated_at": now_cst().strftime("%Y-%m-%d %H:%M:%S %z"),
    }
    from ash_common import dump_json

    dump_json(PROFILE_PATH, profile)
    return profile


def effective_profile() -> dict:
    """Stored profile, or defaults flagged as such (never blocks the pipeline)."""
    stored = load_profile()
    if stored:
        return {**stored, "is_default": False}
    return {**DEFAULTS, "updated_at": None, "is_default": True,
            "note": "用户未提供资金信息，使用默认档（10万/单次10%/单笔风险2%）"}


def position_plan(price: float, stop: float, profile: dict | None = None,
                  lot_size: int = 100) -> dict:
    """Shares under BOTH constraints: risk budget AND max-position cap.

    lot_size: A-share 100（整手）; US 1 股；HK board lot 未确认时按 1 股粒度。
    Also derives min-lot thresholds so an "不可执行" verdict comes with
    actionable numbers: what capital / cap% / risk% would make one lot fit.
    """
    p = profile or effective_profile()
    capital, max_pos, risk = p["total_capital"], p["max_position_pct"], p["risk_pct"]
    lot = max(1, int(lot_size))
    per_share_risk = abs(price - stop)
    if per_share_risk <= 0 or price <= 0:
        return {"shares": 0, "binding": "invalid_prices"}
    by_risk = int(capital * risk / 100 / per_share_risk // lot) * lot
    by_cap = int(capital * max_pos / 100 / price // lot) * lot
    shares = min(by_risk, by_cap)
    binding = "risk_pct" if by_risk <= by_cap else "max_position_pct"
    position_value = shares * price
    # --- min-lot thresholds (always computed; power the not-executable guidance) ---
    cost_1lot = lot * price
    cap_pct_1lot = cost_1lot / capital * 100            # 一手/最小单位占当前总资金 %
    risk_pct_1lot = lot * per_share_risk / capital * 100  # 一手止损损失占当前资金 %
    req_capital_by_cap = cost_1lot / (max_pos / 100) if max_pos > 0 else None
    req_capital_by_risk = (lot * per_share_risk) / (risk / 100) if risk > 0 else None
    thresholds = [c for c in (req_capital_by_cap, req_capital_by_risk) if c]
    min_capital_1lot = max(thresholds) if thresholds else None
    unit = "股"
    return {
        "shares": shares,
        "lot_size": lot,
        "shares_by_risk": by_risk,
        "shares_by_cap": by_cap,
        "binding_constraint": binding,
        "position_value": round(position_value, 2),
        "position_pct": round(position_value / capital * 100, 2),
        "risk_amount_at_stop": round(shares * per_share_risk, 2),
        "risk_pct_actual": round(shares * per_share_risk / capital * 100, 2),
        "capital": capital,
        "cost_1lot": round(cost_1lot, 2),
        "cap_pct_1lot": round(cap_pct_1lot, 1),
        "risk_pct_1lot": round(risk_pct_1lot, 2),
        "required_capital_by_cap": round(req_capital_by_cap, 0) if req_capital_by_cap else None,
        "required_capital_by_risk": round(req_capital_by_risk, 0) if req_capital_by_risk else None,
        "min_capital_1lot": round(min_capital_1lot, 0) if min_capital_1lot else None,
        "note": (f"不足最小交易单位（{lot}{unit}）——按当前风险/仓位约束不可执行，"
                 "需提高资金或单笔风险容忍，或等待更近的止损位" if shares < lot else None),
    }


def main() -> int:
    force_utf8_stdout()
    parser = argparse.ArgumentParser(description="user capital/position profile")
    parser.add_argument("--show", action="store_true")
    parser.add_argument("--set", action="store_true")
    parser.add_argument("--capital", type=float)
    parser.add_argument("--max-position-pct", type=float)
    parser.add_argument("--risk-pct", type=float)
    parser.add_argument("--clear", action="store_true")
    args = parser.parse_args()

    if args.clear:
        if PROFILE_PATH.is_file():
            PROFILE_PATH.unlink()
        emit({"status": "cleared", "profile_file": str(PROFILE_PATH)})
        return 0
    if args.set:
        if not args.capital or not args.max_position_pct:
            parser.error("--set requires --capital and --max-position-pct")
        profile = save_profile(args.capital, args.max_position_pct,
                               args.risk_pct or DEFAULTS["risk_pct"])
        emit({"status": "saved", "profile": profile, "profile_file": str(PROFILE_PATH)})
        return 0
    # default: show effective profile (stored or defaults) + a worked sizing example
    p = effective_profile()
    emit({"status": "ok", "profile": p, "profile_file": str(PROFILE_PATH) if load_profile() else None})
    return 0


if __name__ == "__main__":
    sys.exit(main())
