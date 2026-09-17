#!/usr/bin/env python3
"""Compact analysis digest extracted from a snapshot — what agents actually read.

  python make_digest.py <snapshot.json> --out digest.json

Rationale: snapshots can exceed 500KB (600 bars + statements). The digest keeps
every number an analyst needs (~10-20KB) so fast-mode main-agent reads it whole
and standard-mode prompts embed it without flooding context. All values are
passed through verbatim from the snapshot — nothing is re-derived except
trivial presentation math (pct changes, dividend TTM aggregation) which is
computed from snapshot numbers only.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ash_common import emit, force_utf8_stdout, load_json, now_cst

# financial-indicator fields worth surfacing (index_id -> 中文 label)
KEY_FIN_INDICATORS = {
    "net_profit_yoy_growth_ratio": "净利润同比增速%",
    "operating_income_yoy_growth_ratio": "营收同比增速%",
    "operating_profit_yoy_growth_ratio": "营业利润同比增速%",
    "total_assets_growth_ratio": "总资产增速%",
    "index_weighted_avg_roe": "加权ROE%",
    "index_deduct_weighted_avg_roe": "扣非加权ROE%",
    "sale_gross_margin": "销售毛利率%",
    "sale_net_interest_ratio": "销售净利率%",
    "assets_debt_ratio": "资产负债率%",
    "current_ratio": "流动比率",
    "net_profit_cash_content": "净利润现金含量",
    "operating_cash_net_yoy_growth_ratio": "经营现金流净额增速%",
}

RECENT_BARS = 30


def _pct(cur: float | None, prev: float | None) -> float | None:
    if cur is None or prev in (None, 0):
        return None
    return round((cur / prev - 1) * 100, 2)


def technical_view(analysis: dict) -> dict:
    """Curate indicators.compute output — drop series-shaped extras, keep decisions."""
    return {
        "last_close": analysis.get("last_close"),
        "moving_averages": analysis.get("moving_averages"),
        "ma_stack": analysis.get("ma_stack"),
        "ma_cross_20_60": analysis.get("ma_cross_20_60"),
        "ma_cross_60_250": analysis.get("ma_cross_60_250"),
        "macd": analysis.get("macd"),
        "rsi": analysis.get("rsi"),
        "adx": analysis.get("adx"),
        "atr": analysis.get("atr"),
        "bollinger": analysis.get("bollinger"),
        "returns_pct": analysis.get("returns_pct"),
        "range_250d": analysis.get("range_250d"),
        "volatility": analysis.get("volatility"),
        "regression_slope_ann_pct": analysis.get("regression_slope_ann_pct"),
        "volume": analysis.get("volume"),
        "structure": analysis.get("structure"),
        "monthly_returns": (analysis.get("monthly_returns") or [])[-6:],
    }


def recent_bars_view(bars: list[dict], n: int = RECENT_BARS) -> list[dict]:
    out = []
    window = bars[-(n + 1):] if len(bars) > n else bars
    for i, b in enumerate(window):
        prev = window[i - 1]["close"] if i > 0 else None
        out.append({
            "date": b["date"],
            "close": b["close"],
            "chg_pct": _pct(b["close"], prev),
            "high": b["high"], "low": b["low"],
            "volume": b["volume"], "turnover": b["turnover"],
        })
    return out[-n:]


def fundamentals_view(snap: dict) -> dict | None:
    out: dict = {}
    if snap.get("valuation"):
        out["valuation"] = snap["valuation"]
    if snap.get("fin_indicators"):
        periods = []
        for rep in snap["fin_indicators"]:  # newest first (requested that way)
            flat = {}
            for ab in rep.get("abilities", []):
                for ind in ab.get("indicators", []):
                    iid = ind.get("index_id")
                    if iid in KEY_FIN_INDICATORS and ind.get("value") is not None:
                        try:
                            flat[KEY_FIN_INDICATORS[iid]] = float(ind["value"])
                        except (TypeError, ValueError):
                            flat[KEY_FIN_INDICATORS[iid]] = ind.get("value")
            if flat:
                periods.append({"report": rep.get("report"), **flat})
        if periods:
            out["fin_indicators_recent"] = periods[:4]
    stmts = snap.get("statements") or {}
    income_annual = stmts.get("income_annual") or []
    if income_annual:
        rows = []
        items = sorted(income_annual, key=lambda x: x.get("fiscal_year") or 0)
        for i, it in enumerate(items):
            prev = items[i - 1] if i > 0 else None
            rows.append({
                "year": it.get("fiscal_year"),
                "revenue": it.get("operating_income"),
                "revenue_yoy_pct": _pct(it.get("operating_income"), prev.get("operating_income")) if prev else None,
                "net_profit_parent": it.get("parent_holder_net_profit"),
                "net_profit_yoy_pct": _pct(it.get("parent_holder_net_profit"),
                                           prev.get("parent_holder_net_profit")) if prev else None,
                "eps": it.get("basic_eps"),
            })
        out["income_annual"] = rows
    income_q = stmts.get("income_quarterly") or []
    if income_q:
        rows = []
        items = sorted(income_q, key=lambda x: x.get("period_end_ms") or 0)
        for it in items[-6:]:
            prev_year = next((x for x in items if _same_quarter_prev_year(x, it)), None)
            rows.append({
                "period_end": it.get("period_end_ms"),
                "revenue": it.get("operating_income"),
                "revenue_yoy_pct": _pct(it.get("operating_income"),
                                       prev_year.get("operating_income")) if prev_year else None,
                "net_profit_parent": it.get("parent_holder_net_profit"),
                "net_profit_yoy_pct": _pct(it.get("parent_holder_net_profit"),
                                           prev_year.get("parent_holder_net_profit")) if prev_year else None,
            })
        out["income_quarterly_recent"] = rows
    bal = stmts.get("balance_annual") or []
    if bal:
        last = sorted(bal, key=lambda x: x.get("fiscal_year") or 0)[-1]
        debt_ratio = (round(last["total_debt"] / last["assets_total"] * 100, 2)
                      if last.get("total_debt") and last.get("assets_total") else None)
        out["balance_latest"] = {
            "fiscal_year": last.get("fiscal_year"),
            "assets_total": last.get("assets_total"),
            "total_debt": last.get("total_debt"),
            "holder_equity_total": last.get("holder_equity_total"),
            "cash": last.get("cash"),
            "debt_ratio_pct": debt_ratio,
        }
    cf = stmts.get("cashflow_annual") or []
    if cf:
        rows = sorted(cf, key=lambda x: x.get("fiscal_year") or 0)
        out["cashflow_annual"] = [{
            "year": it.get("fiscal_year"),
            "operating_cf_net": it.get("act_cash_flow_net"),
            "invest_cf_net": it.get("invest_cash_flow_net"),
            "financing_cf_net": it.get("financing_cash_flow_net"),
            "dividend_paid": it.get("pay_dividends_profits_interest_cash"),
        } for it in rows]
    if snap.get("corp_actions"):
        events = snap["corp_actions"]
        last_close = (snap.get("daily", {}).get("analysis") or {}).get("last_close")
        from datetime import timedelta

        cutoff = (now_cst() - timedelta(days=365)).strftime("%Y-%m-%d")
        ttm_dps = sum(e["dividend_per_share"] for e in events
                      if e.get("ex_date") and e["ex_date"] > cutoff
                      and isinstance(e.get("dividend_per_share"), (int, float)))
        out["dividends"] = {
            "ttm_per_share": round(ttm_dps, 4) if ttm_dps else 0.0,
            "yield_ttm_pct": round(ttm_dps / last_close * 100, 2)
            if (ttm_dps and last_close) else None,
            "last_events": events[:5],
        }
    return out or None


def _same_quarter_prev_year(candidate: dict, ref: dict) -> bool:
    """True if `candidate` is the same fiscal quarter one year before `ref`."""
    from ash_common import ms_to_date

    c, r = candidate.get("period_end_ms"), ref.get("period_end_ms")
    if not c or not r:
        return False
    cd, rd = ms_to_date(c), ms_to_date(r)
    return cd[5:] == rd[5:] and int(cd[:4]) == int(rd[:4]) - 1


def sentiment_view(snap: dict) -> dict | None:
    hot = snap.get("hot_rank") or []
    if not hot:
        return None
    ranks = [h["rank"] for h in hot if isinstance(h.get("rank"), int)]
    if not ranks:
        return None
    last30 = ranks[-30:]
    return {
        "rank_latest": ranks[-1],
        "rank_avg_30d": round(sum(last30) / len(last30), 0),
        "rank_best_60d": min(ranks),
        "rank_worst_60d": max(ranks),
        "note": "排名越小热度越高；Top30 为热门股",
    }


def benchmark_view(snap: dict) -> dict:
    bench = snap.get("benchmark") or {}
    out = {"thscode": bench.get("thscode")}
    if bench.get("analysis"):
        a = bench["analysis"]
        out["trend"] = {
            "ma_stack": a.get("ma_stack"),
            "ret_60d_pct": (a.get("returns_pct") or {}).get("ret_60d"),
            "ret_120d_pct": (a.get("returns_pct") or {}).get("ret_120d"),
            "slope_60d": (a.get("regression_slope_ann_pct") or {}).get("slope_60d"),
            "adx": (a.get("adx") or {}).get("adx_14"),
        }
    if bench.get("relative_strength"):
        out["relative_strength"] = bench["relative_strength"]
    return out


def build_digest(snapshot_path: str | Path) -> dict:
    snap = load_json(snapshot_path)
    meta = snap.get("meta", {})
    a = (snap.get("daily") or {}).get("analysis") or {}
    digest = {
        "identity": {k: meta.get(k) for k in
                     ("thscode", "ticker", "name", "exchange", "asset_type",
                      "list_date", "end_date")},
        "as_of": (snap.get("daily", {}).get("bars") or [{}])[-1].get("date"),
        "generated_at": meta.get("generated_at"),
        "provider": meta.get("provider"),
        "adjust": meta.get("adjust"),
        "data_quality": None,
        "technical": technical_view(a) if a else None,
        "recent_bars": recent_bars_view(snap.get("daily", {}).get("bars", [])),
        "quote": snap.get("quote"),
        "benchmark": benchmark_view(snap),
        "fundamentals": fundamentals_view(snap),
        "sentiment": sentiment_view(snap),
        "snapshot": str(snapshot_path),
    }
    from fetch_snapshot import quality_oneline

    digest["data_quality"] = quality_oneline(snap.get("quality", {}))
    digest["_quality_raw"] = snap.get("quality", {})
    return digest


def main() -> int:
    force_utf8_stdout()
    parser = argparse.ArgumentParser(description="snapshot -> compact digest")
    parser.add_argument("snapshot", help="path to snapshot.json")
    parser.add_argument("--out", default=None, help="output path (default: <snapshot dir>/digest.json)")
    args = parser.parse_args()

    src = Path(args.snapshot)
    if not src.is_file():
        emit({"status": "error", "error": f"snapshot not found: {src}"})
        return 4
    digest = build_digest(src)
    # per-snapshot filename: snapshots share one cache dir, a fixed digest.json
    # would be overwritten by every new analysis
    out = Path(args.out) if args.out else src.parent / f"{src.stem}_digest.json"
    from ash_common import dump_json

    dump_json(out, digest)
    emit({
        "status": "ok",
        "digest": str(out),
        "identity": digest["identity"],
        "as_of": digest["as_of"],
        "data_quality": digest["data_quality"],
        "sections": [k for k in ("technical", "fundamentals", "sentiment", "benchmark")
                     if digest.get(k)],
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
