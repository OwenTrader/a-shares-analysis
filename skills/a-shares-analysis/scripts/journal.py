#!/usr/bin/env python3
"""Decision journal — archive every verdict, settle it later against real bars.

  python journal.py record --decision decision.json [--report FINAL_REPORT.md]
                           [--snapshot snapshot.json] [--mode fast|standard]
  python journal.py list [--since-days 30] [--markdown]
  python journal.py settle --thscode 600519.SH [--latest]

Verdicts: BUY / HOLD / REDUCE / WAIT (A-share retail is long-only; no SHORT).
Plans are long-only with 100-share lots enforced (科创板/创业板 lot rules noted).

Settlement walks daily bars after the decision date: for each plan, stop vs TP1
whichever hits first (then TP2/TP3 follow-ups), max adverse/favourable excursion,
and open-position mark-to-market. History is append-only — records are never
rewritten, settlements are added alongside.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from ash_common import (
    DATA_DIR,
    EXIT_NEEDS_MANUAL,
    emit,
    force_utf8_stdout,
    load_json,
    now_cst,
)

VERDICTS = {"BUY", "HOLD", "REDUCE", "WAIT"}
JOURNAL_DIR = DATA_DIR / "journal"
INDEX = JOURNAL_DIR / "index.jsonl"


def _validate(decision: dict) -> list[str]:
    problems = []
    for field in ("thscode", "date", "verdict"):
        if not decision.get(field):
            problems.append(f"missing {field}")
    verdict = str(decision.get("verdict", "")).upper()
    if verdict not in VERDICTS:
        problems.append(f"verdict must be one of {sorted(VERDICTS)}")
    decision["verdict"] = verdict
    plans = decision.get("plans")
    if verdict == "WAIT":
        decision["plans"] = plans or []
        return problems
    if not plans:
        problems.append("non-WAIT verdict requires at least one plan")
        return problems
    for i, p in enumerate(plans):
        for field in ("entry", "stop", "tp1"):
            if p.get(field) is None:
                problems.append(f"plans[{i}] missing {field}")
        if problems:
            continue
        entry, stop, tp1 = float(p["entry"]), float(p["stop"]), float(p["tp1"])
        if stop >= entry:
            problems.append(f"plans[{i}] stop must be below entry (long-only)")
        if tp1 <= entry:
            problems.append(f"plans[{i}] tp1 must be above entry")
        shares = p.get("shares")
        if shares is not None:
            if shares < 100:
                p["shares"] = 0
                p["shares_note"] = "低于一手(100股)，视为不建议建仓"
            elif shares % 100:
                p["shares"] = int(shares // 100) * 100
                p["shares_note"] = f"A股按整手交易，已向下取整为 {p['shares']}"
        rrr = round((tp1 - entry) / (entry - stop), 2)
        if p.get("rrr_tp1") not in (None, rrr):
            p["rrr_tp1_reported"] = p.get("rrr_tp1")
        p["rrr_tp1"] = rrr
    return problems


def record(args) -> int:
    decision = load_json(args.decision)
    problems = _validate(decision)
    if problems:
        emit({"status": "needs_manual", "problems": problems, "exit": EXIT_NEEDS_MANUAL})
        return EXIT_NEEDS_MANUAL

    mode = args.mode or decision.get("mode") or "fast"
    thscode = decision["thscode"]
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    rec_dir = JOURNAL_DIR / thscode.replace(".", "_") / f"{ts}-{mode}"
    rec_dir.mkdir(parents=True, exist_ok=True)

    meta = {"recorded_at": now_cst().strftime("%Y-%m-%d %H:%M:%S %z"),
            "mode": mode, "snapshot": args.snapshot,
            "provider": None, "quality": None}
    if args.snapshot and Path(args.snapshot).is_file():
        snap = load_json(args.snapshot)
        meta["provider"] = snap.get("meta", {}).get("provider")
        meta["quality"] = snap.get("quality", {})
    from ash_common import dump_json

    dump_json(rec_dir / "decision.json", decision)
    dump_json(rec_dir / "meta.json", meta)
    if args.report and Path(args.report).is_file():
        (rec_dir / "report.md").write_text(Path(args.report).read_text(encoding="utf-8"),
                                           encoding="utf-8")
    entry = {"id": f"{ts}-{mode}", "thscode": thscode, "name": decision.get("name"),
             "date": decision["date"], "verdict": decision["verdict"],
             "rrr_tp1": decision["plans"][0].get("rrr_tp1") if decision.get("plans") else None,
             "dir": str(rec_dir)}
    with INDEX.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    quality_txt = ("快照未提供" if meta["quality"] is None
                   else "完整" if meta["quality"].get("ok") else "有告警")
    emit({
        "status": "recorded",
        "record": entry,
        "provenance_echo": f"数据源={meta['provider'] or '未知'} | 快照={args.snapshot or '未提供'} | "
                           f"质量={quality_txt}",
        "say_to_user": f"✓ 已归档 {thscode} {decision['date']} {decision['verdict']}（{entry['id']}）",
    })
    return 0


def _load_index() -> list[dict]:
    if not INDEX.is_file():
        return []
    out = []
    for line in INDEX.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def list_records(args) -> int:
    from datetime import timedelta

    cutoff = (now_cst() - timedelta(days=args.since_days)).strftime("%Y-%m-%d")
    rows = [r for r in _load_index() if r.get("date", "") >= cutoff]
    if args.markdown:
        force_utf8_stdout()
        print("| id | 日期 | 代码 | 名称 | 评级 | RRR(TP1) | 结算 |")
        print("|---|---|---|---|---|---|---|")
        for r in rows:
            settled = "已结算" if (Path(r["dir"]) / "settlement.json").is_file() else "—"
            print(f"| {r['id']} | {r['date']} | {r['thscode']} | {r.get('name') or ''} "
                  f"| {r['verdict']} | {r.get('rrr_tp1') or '—'} | {settled} |")
    else:
        emit({"status": "ok", "count": len(rows), "records": rows})
    return 0


def _settle_plan(plan: dict, bars: list[dict]) -> dict:
    entry, stop = float(plan["entry"]), float(plan["stop"])
    tps = {f"tp{i}": float(plan[f"tp{i}"]) for i in (1, 2, 3) if plan.get(f"tp{i}")}
    outcome, hit_date = "open", None
    hit = {"stop": False, **{k: False for k in tps}}
    max_gain = max_dd = 0.0
    for b in bars:
        lo, hi = float(b["low"]), float(b["high"])
        if lo <= stop:
            if not any(hit[k] for k in tps) and not hit["stop"]:
                outcome, hit_date = "stopped", b["date"]
            hit["stop"] = True
            max_dd = min(max_dd, lo / entry - 1)
            break
        for k, level in tps.items():
            if hi >= level:
                hit[k] = True
                if outcome == "open" and k == "tp1":
                    outcome, hit_date = "tp1_hit", b["date"]
        max_gain = max(max_gain, hi / entry - 1)
        max_dd = min(max_dd, lo / entry - 1)
    last = bars[-1] if bars else {}
    result = {
        "entry": entry, "outcome": outcome, "hit_date": hit_date,
        "tps_hit": [k for k in ("tp1", "tp2", "tp3") if hit.get(k)],
        "max_gain_pct": round(max_gain * 100, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "current_close": last.get("close"),
        "unrealized_pct": round((float(last["close"]) / entry - 1) * 100, 2) if last.get("close") else None,
    }
    if outcome == "stopped":
        result["realized_pct"] = round((stop / entry - 1) * 100, 2)
    return result


def _bars_since(provider, decision: dict, thscode: str, end_ms: int) -> list[dict]:
    """Post-decision daily bars (or fund/NAV bars) for settlement, ascending."""
    from ash_common import date_to_ms

    start = date_to_ms(decision["date"]) + 1
    if decision.get("asset_type") == "fund-etf" and provider.has("fund_kline"):
        return provider.fund_kline(thscode, start, end_ms)
    return provider.daily_kline(thscode, start, end_ms)


def settle(args) -> int:
    from providers import ProviderError, get_provider

    rows = [r for r in _load_index() if r["thscode"].upper() == args.thscode.upper()]
    if not rows:
        emit({"status": "not_found", "error": f"no journal records for {args.thscode}"})
        return 3
    rows.sort(key=lambda r: r["id"])
    targets = rows[-1:] if args.latest else rows
    try:
        provider = get_provider()
    except ProviderError as exc:
        emit({"status": "no_key", "error": exc.message})
        return 2

    results = []
    for rec in targets:
        rec_dir = Path(rec["dir"])
        decision = load_json(rec_dir / "decision.json")
        end_ms = int(now_cst().timestamp() * 1000)
        bars = _bars_since(provider, decision, args.thscode, end_ms)
        bars = [b for b in bars if b.get("date") and b["date"] > decision["date"]]
        plans_out = [_settle_plan(p, bars) for p in decision.get("plans", [])]
        payload = {"id": rec["id"], "date": decision["date"], "verdict": decision["verdict"],
                   "settled_at": now_cst().strftime("%Y-%m-%d %H:%M:%S %z"),
                   "bars_since": len(bars), "plans": plans_out}
        from ash_common import dump_json

        dump_json(rec_dir / "settlement.json", payload)
        results.append(payload)

    emit({"status": "ok", "settled": len(results), "results": results,
          "say_to_user": f"✓ 已结算 {len(results)} 条记录（结算文件已写入各自归档目录）"})
    return 0


def main() -> int:
    force_utf8_stdout()
    parser = argparse.ArgumentParser(description="A-share decision journal")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_rec = sub.add_parser("record", help="archive a decision")
    p_rec.add_argument("--decision", required=True, help="decision.json path")
    p_rec.add_argument("--report", default=None, help="final report md to archive alongside")
    p_rec.add_argument("--snapshot", default=None, help="snapshot.json the decision was based on")
    p_rec.add_argument("--mode", choices=["fast", "standard"], default=None)

    p_list = sub.add_parser("list", help="list recent records")
    p_list.add_argument("--since-days", type=int, default=30)
    p_list.add_argument("--markdown", action="store_true")

    p_set = sub.add_parser("settle", help="settle records against real bars")
    p_set.add_argument("--thscode", required=True)
    p_set.add_argument("--latest", action="store_true", help="only the most recent record")

    args = parser.parse_args()
    if args.cmd == "record":
        return record(args)
    if args.cmd == "list":
        return list_records(args)
    return settle(args)


if __name__ == "__main__":
    sys.exit(main())
