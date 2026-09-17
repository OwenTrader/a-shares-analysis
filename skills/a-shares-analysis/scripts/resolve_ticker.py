#!/usr/bin/env python3
"""Ticker resolution & error-correction gate — MUST pass before any analysis.

Handles the messy ways users name a stock:
  茅台 / 贵州茅台 / 600519 / 600519.SH / sh600519 / ６００５１９ (full-width) / typos

Resolution pipeline (pure logic separated from I/O for offline testing):
  1. normalize the query (NFKC, strip spaces, unify suffix forms)
  2. provider.search(query, asset_type)
  3. score candidates: exact thscode > exact ticker > exact name >
     name startswith > name contains > difflib similarity
  4. status: verified (unique high-confidence match) | ambiguous (agent must ask
     the user via AskUserQuestion) | not_found (suggest closest names)
  5. warnings: 退市/摘牌 (end_date), ST/*ST 风险警示, 上市不足一年

Exit codes: 0 verified · 2 ambiguous / no_key (needs user input) · 3 not_found · 4 data error
"""
from __future__ import annotations

import argparse
import difflib
import re
import sys
import unicodedata

from ash_common import EXIT_DATA_ERROR, EXIT_NEEDS_INPUT, EXIT_NOT_FOUND, emit, force_utf8_stdout, now_cst
from providers import ProviderError, get_provider
from providers.base import ERR_AUTH

DEFAULT_ASSET_TYPE = "a-share"


def normalize_query(q: str) -> str:
    q = unicodedata.normalize("NFKC", str(q)).strip()          # full-width -> ASCII
    q = re.sub(r"\s+", "", q)
    q = q.upper()
    m = re.match(r"^(SH|SZ|BJ)(\d{6})$", q)                    # sh600519 -> 600519.SH
    if m:
        q = f"{m.group(2)}.{m.group(1)}"
    m = re.match(r"^(\d{6})[._](SH|SZ|BJ)$", q)                # 600519_sh -> 600519.SH
    if m:
        q = f"{m.group(1)}.{m.group(2)}"
    return q


def _score(query: str, cand: dict) -> float:
    thscode, ticker, name = (cand.get("thscode") or ""), (cand.get("ticker") or ""), (cand.get("name") or "")
    if query == thscode:
        return 100.0
    if query == ticker:
        return 90.0
    if query == name:
        return 80.0
    if name.startswith(query):
        return 70.0
    if query in name:
        return 60.0
    return round(difflib.SequenceMatcher(None, query, name).ratio() * 50, 1)


def match(query: str, candidates: list[dict]) -> dict:
    """Pure ranking/matching over search results — no I/O (unit-tested)."""
    query = normalize_query(query)
    ranked = sorted(
        ({**c, "_score": _score(query, c)} for c in candidates),
        key=lambda c: c["_score"], reverse=True,
    )
    if not ranked or ranked[0]["_score"] < 50:
        suggestions = [
            {"thscode": c["thscode"], "name": c.get("name"), "similarity": c["_score"]}
            for c in ranked[:5] if c["_score"] > 0
        ]
        return {"status": "not_found", "target": None, "candidates": suggestions}

    top = ranked[0]["_score"]
    top_ties = [c for c in ranked if c["_score"] == top]
    if top >= 80 and len(top_ties) == 1:
        return {"status": "verified", "target": top_ties[0], "candidates": ranked[:5]}
    if len(ranked) == 1 and top >= 60:
        # sole substring hit (e.g. 茅台 -> 贵州茅台) — verify with a note for the agent to echo
        return {"status": "verified", "target": ranked[0], "candidates": ranked,
                "note": f"唯一子串匹配（得分 {top}），已按唯一候选确认，请向用户复述全称"}
    # two equally-plausible matches (same name on two boards, ticker shared
    # across asset types after filtering, ...) or merely fuzzy hits -> ask user
    return {"status": "ambiguous", "target": None, "candidates": ranked[:5]}


def warnings_for(target: dict, today=None) -> list[str]:
    out = []
    today = today or now_cst().date()
    name = target.get("name") or ""
    end_date = target.get("end_date")
    if end_date and str(end_date) <= str(today):
        out.append(f"已摘牌/退市（最后交易日 {end_date}），无法交易，仅可做历史复盘")
    if end_date and str(end_date) > str(today):
        out.append(f"即将摘牌（定于 {end_date}），存在退市风险")
    if "退" in name:
        out.append("名称含「退」，退市整理期股票，涨跌幅限制与流动性异常")
    if re.search(r"\*?ST", name.upper()):
        out.append("ST/*ST 风险警示股票：涨跌幅限制 5%，且有退市风险，谨慎分析")
    list_date = target.get("list_date")
    if list_date:
        try:
            from datetime import date

            listed_days = (today - date.fromisoformat(str(list_date))).days
            if listed_days < 365:
                out.append(f"上市不足一年（{list_date} 上市），缺乏年线与长期财务历史")
        except ValueError:
            pass
    return out


def fallback_searches(query: str) -> list[str]:
    """Secondary queries when the primary search returns nothing (typos etc.)."""
    qs = []
    if re.match(r"^\d{6}$", query):
        qs.append(query)  # retry without asset_type filter can surface index/fund twins
    if len(query) >= 2:
        qs.append(query[:2])  # 贵州茅台 typo -> try first two chars as substring seed
    return qs


def resolve(provider, query: str, asset_type: str | None) -> dict:
    query_n = normalize_query(query)
    asset_type = asset_type or DEFAULT_ASSET_TYPE
    try:
        results = provider.search(query_n, asset_type=asset_type, limit=20)
    except ProviderError as exc:
        if exc.kind == ERR_AUTH:
            return {"status": "no_key", "error": exc.message}
        raise
    if not results:  # typo fallback: broaden with substring seeds, then fuzzy-rank
        for alt in fallback_searches(query_n):
            try:
                results = provider.search(alt, asset_type=asset_type, limit=20)
            except ProviderError as exc:
                if exc.kind == ERR_AUTH:
                    return {"status": "no_key", "error": exc.message}
                continue
            if results:
                break
    outcome = match(query_n, results)
    if outcome["status"] == "verified":
        target = outcome["target"]
        outcome["warnings"] = warnings_for(target)
    else:
        outcome.setdefault("warnings", [])
    outcome["query"] = query_n
    outcome["asset_type"] = asset_type
    return outcome


_SAY = {
    "verified": "✓ 已确认标的：{thscode} {name}（{exchange}）",
    "ambiguous": "「{query}」有多个可能的标的，请确认是哪一个：",
    "not_found": "没有找到与「{query}」匹配的标的",
}


def humanize(outcome: dict) -> str:
    status = outcome["status"]
    if status == "no_key":
        return "缺少 API Key，无法检索标的。请到 https://fuyao.aicubes.cn/admin 签发后提供给我。"
    if status == "verified":
        t = outcome["target"]
        line = _SAY["verified"].format(**t)
        if outcome.get("warnings"):
            line += " ⚠ " + "；".join(outcome["warnings"])
        return line
    if status == "ambiguous":
        lines = [_SAY["ambiguous"].format(query=outcome["query"])]
        for c in outcome["candidates"][:4]:
            lines.append(f"  - {c['thscode']} {c.get('name', '')}（{c.get('exchange') or c.get('asset_type')}）")
        return "\n".join(lines)
    return _SAY["not_found"].format(query=outcome["query"]) + "，请检查名称或代码是否正确"


def main() -> int:
    force_utf8_stdout()
    parser = argparse.ArgumentParser(description="A-share ticker resolution & error correction")
    parser.add_argument("query", nargs="?", help="股票名称/代码/thscode")
    parser.add_argument("--q", dest="q_opt", help="同上（可选写法）")
    parser.add_argument("--type", dest="asset_type", default=DEFAULT_ASSET_TYPE,
                        help="a-share(默认) / a-share-index / fund-etf / fund-lof ...")
    args = parser.parse_args()
    query = (args.query or args.q_opt or "").strip()
    if not query:
        emit({"status": "need_query", "say_to_user": "请告诉我要分析的股票名称或代码，例如「贵州茅台」或 600519"})
        return EXIT_NEEDS_INPUT

    try:
        provider = get_provider()
        outcome = resolve(provider, query, args.asset_type)
    except ProviderError as exc:
        if exc.kind == ERR_AUTH:
            emit({"status": "no_key", "error": exc.message, "exit": EXIT_NEEDS_INPUT})
            return EXIT_NEEDS_INPUT
        emit({"status": "error", "error": exc.message, "exit": EXIT_DATA_ERROR})
        return EXIT_DATA_ERROR

    outcome["say_to_user"] = humanize(outcome)
    outcome["exit"] = {"verified": 0, "ambiguous": EXIT_NEEDS_INPUT,
                       "not_found": EXIT_NOT_FOUND, "no_key": EXIT_NEEDS_INPUT}[outcome["status"]]
    if outcome["status"] == "verified":
        t = outcome["target"]
        outcome["target"] = {k: v for k, v in t.items() if not k.startswith("_")}
        outcome["candidates"] = [{k: v for k, v in c.items() if not k.startswith("_")}
                                 for c in outcome["candidates"]]
    else:
        outcome["candidates"] = [{k: v for k, v in c.items() if not k.startswith("_")}
                                 for c in outcome.get("candidates", [])]
    emit(outcome)
    return outcome["exit"]


if __name__ == "__main__":
    sys.exit(main())
