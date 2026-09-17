#!/usr/bin/env python3
"""Data grounding: pull everything needed for a medium/long-term review into ONE snapshot.

  python fetch_snapshot.py --thscode 600519.SH
      [--asset-type a-share|a-share-index] [--bars 600] [--adjust forward]
      [--benchmark 000300.SH] [--skip fundamentals,hot,statements]
      [--out path.json] [--strict-freshness]

Snapshot layout (the ONLY data source for every downstream agent):
  meta      identity / provider / window / generated_at
  quality   ok · fresh · days_behind · bars_note · sections_errors · notes[]
  daily     {bars[], analysis{...indicators.compute}}          — core, failure = exit 4
  quote     latest snapshot quote
  benchmark {thscode, bars[], analysis, relative_strength}
  valuation PE/PB/PS/PCF                                        — optional, degrade
  fin_indicators  recent report periods (5-ability sets)
  statements     income(annual+quarterly) / balance / cashflow
  corp_actions   dividend & bonus events
  hot_rank       daily heat-rank series (last ~60 natural days)

Optional sections fail soft: recorded in quality.sections_errors, analysis proceeds.
"""
from __future__ import annotations

import argparse
import math
import sys
from datetime import date, datetime, timedelta

from ash_common import (
    CACHE_DIR,
    EXIT_DATA_ERROR,
    EXIT_NEEDS_INPUT,
    EXIT_QUALITY_FAIL,
    emit,
    force_utf8_stdout,
    now_cst,
)
from providers import ProviderError, get_provider
from providers.base import ERR_AUTH

DEFAULT_BENCHMARK = "000300.SH"  # 沪深300


def recent_report_codes(now: datetime, n: int = 6) -> list[str]:
    """Report codes (yyyy-q) whose disclosure deadline has passed, newest first."""
    candidates = []
    for year in (now.year, now.year - 1, now.year - 2):
        candidates += [
            (year, 1, date(year, 4, 30)),      # Q1 披露截止 4/30
            (year, 2, date(year, 8, 31)),      # 中报 8/31
            (year, 3, date(year, 10, 31)),     # 三季报 10/31
            (year, 4, date(year + 1, 4, 30)),  # 年报次年 4/30
        ]
    candidates.sort(key=lambda x: x[2], reverse=True)
    out = []
    for year, q, deadline in candidates:
        if deadline <= now.date():
            out.append(f"{year}-{q}")
        if len(out) >= n:
            break
    return out


def window_ms(bars: int, now: datetime) -> tuple[int, int]:
    """Natural-day window that safely contains `bars` trading days."""
    from ash_common import days_ago_ms

    natural_days = math.ceil(bars * 1.55) + 30
    return days_ago_ms(natural_days, now), int(now.timestamp() * 1000)


def _safe(provider, section: str, fn, errors: list, skip: set[str]):
    """Run an optional section; return None on failure or skip (soft degrade)."""
    if section in skip:
        return None
    try:
        return fn()
    except ProviderError as exc:
        if exc.kind == "no_data":
            return {"no_data": True}  # exists upstream but nothing published — not an error
        errors.append({"section": section, "error": f"[{exc.kind}] {exc.message}"})
        return None
    except Exception as exc:  # noqa: BLE001 — never let an optional section kill the run
        errors.append({"section": section, "error": f"[local] {exc}"})
        return None


def build_snapshot(provider, thscode: str, asset_type: str, bars_wanted: int,
                   adjust: str, benchmark: str, skip: set[str], now: datetime) -> dict:
    errors: list[dict] = []
    notes: list[str] = []

    # -- identity (cheap re-verification; resolve_ticker is the real gate) ----
    identity_hits = provider.search(thscode, asset_type=asset_type, limit=5)
    identity = next((c for c in identity_hits if c["thscode"].upper() == thscode.upper()), None)
    if identity is None:
        raise ProviderError("not_found", f"{thscode} not found in ticker search")

    start_ms, end_ms = window_ms(bars_wanted, now)

    # -- calendar: freshness baseline ----------------------------------------
    trading_days = _safe(provider, "calendar", provider.calendar, errors, skip) or []
    last_trading_day = trading_days[-1] if trading_days else None

    # -- core kline -----------------------------------------------------------
    if asset_type == "a-share-index":
        bars = provider.index_kline(thscode, start_ms, end_ms)
    else:
        bars = provider.daily_kline(thscode, start_ms, end_ms, adjust=adjust)
    if not bars or len(bars) < 20:
        raise ProviderError("no_data", f"daily kline empty/too short for {thscode}")
    bars = bars[-bars_wanted:]
    bars = [b for b in bars if b.get("date")]  # drop any malformed rows

    from indicators import compute, relative_strength

    analysis = compute(bars)
    last_bar_date = bars[-1]["date"]

    fresh = last_trading_day is None or last_bar_date >= last_trading_day
    days_behind = 0
    if not fresh and trading_days:
        today_s = now.strftime("%Y-%m-%d")
        days_behind = len([d for d in trading_days if last_bar_date < d <= today_s])

    # staleness beyond 5 trading days (suspension or feed lag) fails the gate;
    # within 5 is noted but acceptable for medium/long-term daily-bar analysis
    ok = len(bars) >= 60 and days_behind <= 5
    if len(bars) < 60:
        ok = False
        notes.append(f"仅 {len(bars)} 根日线，不足以支撑中长线研判（上市太短或数据缺失）")
    if len(bars) < 250:
        notes.append("日线不足 250 根：年线（MA250）及 250d 区间指标缺失，长期结构判断受限")
    if not fresh:
        notes.append(f"最后一根日线为 {last_bar_date}，落后最新交易日 {days_behind} 个交易日——可能停牌或数据滞后，请核实")

    snapshot: dict = {
        "meta": {
            "thscode": identity["thscode"], "ticker": identity.get("ticker"),
            "name": identity.get("name"), "exchange": identity.get("exchange"),
            "asset_type": asset_type, "list_date": identity.get("list_date"),
            "end_date": identity.get("end_date"),
            "provider": provider.name, "adjust": adjust,
            "window": {"first": bars[0]["date"], "last": last_bar_date, "bars": len(bars)},
            "benchmark_thscode": benchmark,
            "generated_at": now.strftime("%Y-%m-%d %H:%M:%S %z"),
        },
        "quality": {"ok": ok, "fresh": fresh, "days_behind": days_behind,
                    "last_trading_day": last_trading_day,
                    "sections_errors": errors, "notes": notes},
        "daily": {"bars": bars, "analysis": analysis},
    }

    # -- quote ----------------------------------------------------------------
    if asset_type == "a-share-index":
        quote_fn = lambda: provider.index_quote([thscode])[0]  # noqa: E731
    else:
        quote_fn = lambda: provider.quote([thscode])[0]        # noqa: E731
    quote = _safe(provider, "quote", quote_fn, errors, skip)
    if quote:
        snapshot["quote"] = quote

    # -- benchmark & relative strength ----------------------------------------
    bench = {"thscode": benchmark}
    if "benchmark" not in skip:
        try:
            bench_bars = provider.index_kline(benchmark, start_ms, end_ms)
            if bench_bars:
                bench_bars = bench_bars[-bars_wanted:]
                bench["bars"] = bench_bars
                bench["analysis"] = {
                    k: analysis_b for k, analysis_b in compute(bench_bars).items()
                    if k in ("last_close", "moving_averages", "ma_stack", "returns_pct",
                             "regression_slope_ann_pct", "adx", "range_250d")
                }
                try:
                    import pandas as pd

                    s = pd.Series({b["date"]: b["close"] for b in bars}, dtype=float)
                    b_ = pd.Series({b["date"]: b["close"] for b in bench_bars}, dtype=float)
                    joined = pd.concat([s.rename("s"), b_.rename("b")], axis=1).dropna()
                    bench["relative_strength"] = relative_strength(joined["s"], joined["b"])
                except Exception as exc:  # noqa: BLE001
                    errors.append({"section": "benchmark_rs", "error": f"[local] {exc}"})
        except ProviderError as exc:
            errors.append({"section": "benchmark", "error": f"[{exc.kind}] {exc.message}"})
    snapshot["benchmark"] = bench

    # -- valuation ------------------------------------------------------------
    if asset_type == "a-share":
        val = _safe(provider, "valuation", lambda: provider.valuation([thscode])[0], errors, skip)
        if val:
            snapshot["valuation"] = val

    # -- financial indicators ---------------------------------------------------
    if asset_type == "a-share":
        reports = recent_report_codes(now, n=6)
        fin = []
        for code in reports:
            try:
                fin.append(provider.fin_indicators(thscode, code))
            except ProviderError as exc:
                if exc.kind in ("no_data", "not_found"):
                    continue  # quarter not disclosed yet — expected, not an error
                errors.append({"section": f"fin_indicators[{code}]", "error": f"[{exc.kind}] {exc.message}"})
                break
            except Exception as exc:  # noqa: BLE001
                errors.append({"section": f"fin_indicators[{code}]", "error": f"[local] {exc}"})
                break
        if fin:
            snapshot["fin_indicators"] = fin

    # -- statements --------------------------------------------------------------
    if asset_type == "a-share" and "statements" not in skip:
        stmts: dict[str, list] = {}
        jobs = (
            ("income_annual", lambda: provider.income_statements(thscode, "annual", 5)),
            ("income_quarterly", lambda: provider.income_statements(thscode, "quarterly", 8)),
            ("balance_annual", lambda: provider.balance_sheets(thscode, "annual", 3)),
            ("cashflow_annual", lambda: provider.cash_flow_statements(thscode, "annual", 3)),
        )
        for section, fn in jobs:
            try:
                result = fn()
                if result:
                    stmts[section] = result
            except ProviderError as exc:
                errors.append({"section": section, "error": f"[{exc.kind}] {exc.message}"})
            except Exception as exc:  # noqa: BLE001
                errors.append({"section": section, "error": f"[local] {exc}"})
        if stmts:
            snapshot["statements"] = stmts

    # -- corporate actions --------------------------------------------------------
    if asset_type == "a-share":
        corp = _safe(provider, "corp_actions", lambda: provider.corp_actions(thscode), errors, skip)
        if corp:
            snapshot["corp_actions"] = corp

    # -- heat rank (sentiment) -----------------------------------------------------
    if asset_type == "a-share":
        d_from = (now - timedelta(days=70)).strftime("%Y-%m-%d")
        d_to = now.strftime("%Y-%m-%d")
        hot = _safe(provider, "hot", lambda: provider.hot_rank_trend(thscode, d_from, d_to),
                    errors, skip)
        if hot:
            snapshot["hot_rank"] = hot

    return snapshot


def quality_oneline(quality: dict) -> str:
    parts = []
    parts.append("数据完整可用" if quality.get("ok") else "数据质量不达标")
    if not quality.get("fresh", True):
        parts.append(f"行情滞后 {quality.get('days_behind')} 个交易日")
    if quality.get("sections_errors"):
        parts.append(f"{len(quality['sections_errors'])} 个数据段缺失")
    parts += quality.get("notes", [])
    return "；".join(parts)


def main() -> int:
    force_utf8_stdout()
    parser = argparse.ArgumentParser(description="A-share analysis data snapshot")
    parser.add_argument("--thscode", required=True, help="verified thscode, e.g. 600519.SH")
    parser.add_argument("--asset-type", default="a-share",
                        help="a-share (default) or a-share-index")
    parser.add_argument("--bars", type=int, default=600,
                        help="daily bars to keep (default 600 ≈ 2.5 years)")
    parser.add_argument("--adjust", default="forward", choices=["none", "forward", "backward"])
    parser.add_argument("--benchmark", default=DEFAULT_BENCHMARK)
    parser.add_argument("--skip", default="", help="comma list: valuation,fin_indicators,"
                                                   "statements,corp_actions,hot,benchmark,quote,calendar")
    parser.add_argument("--out", default=None)
    parser.add_argument("--strict-freshness", action="store_true",
                        help="exit 5 when quality.ok is false (snapshot still written)")
    parser.add_argument("--json", action="store_true", help="print full snapshot JSON to stdout")
    args = parser.parse_args()

    now = now_cst()
    skip = {s.strip() for s in args.skip.split(",") if s.strip()}
    try:
        provider = get_provider()
        snap = build_snapshot(provider, args.thscode, args.asset_type,
                              args.bars, args.adjust, args.benchmark, skip, now)
    except ProviderError as exc:
        if exc.kind == ERR_AUTH:
            emit({"status": "no_key", "error": exc.message, "exit": EXIT_NEEDS_INPUT})
            return EXIT_NEEDS_INPUT
        emit({"status": "data_error", "error": exc.message, "exit": EXIT_DATA_ERROR})
        return EXIT_DATA_ERROR

    from ash_common import dump_json

    ts = now.strftime("%Y%m%d_%H%M%S")
    out = args.out or str(CACHE_DIR / "snapshots" / f"{snap['meta']['ticker']}_{ts}.json")
    dump_json(out, snap)

    m = snap["meta"]
    summary = {
        "status": "ok",
        "snapshot": out,
        "thscode": m["thscode"], "name": m["name"],
        "window": m["window"],
        "quality": snap["quality"],
        "quality_oneline": quality_oneline(snap["quality"]),
        "say_to_user": f"✓ 快照就绪 {m['thscode']} {m['name']} | {m['window']['bars']} 根日线"
                       f"（{m['window']['first']} ~ {m['window']['last']}）| {quality_oneline(snap['quality'])}",
    }
    if args.json:
        snap["_summary"] = summary
        emit(snap)
    else:
        emit(summary)

    if args.strict_freshness and not snap["quality"]["ok"]:
        return EXIT_QUALITY_FAIL
    return 0


if __name__ == "__main__":
    sys.exit(main())
