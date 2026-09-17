#!/usr/bin/env python3
"""Shared plumbing for the a-shares-analysis skill: paths, timezone, JSON, CLI exit codes.

Every entry-point script imports from here. Pure stdlib — safe to use before the
venv exists (setup_env.py bootstraps pandas/numpy separately).
"""
from __future__ import annotations

import io
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# A-share market timezone. Pinned to UTC+8 regardless of the host machine's
# timezone, so timestamps line up with the API's Asia/Shanghai convention.
CST = timezone(timedelta(hours=8))

SKILL_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = SKILL_DIR / "scripts"
CACHE_DIR = SKILL_DIR / ".cache"
# decision journal is append-only user data; relocate with ASHARES_DATA_DIR
DATA_DIR = Path(os.environ.get("ASHARES_DATA_DIR") or (SKILL_DIR / "data"))

# Exit codes (documented in references/agent_guide.md)
EXIT_OK = 0
EXIT_NEEDS_INPUT = 2      # missing API key / ambiguous ticker -> agent must ask the user
EXIT_NOT_FOUND = 3        # ticker resolution failed outright
EXIT_DATA_ERROR = 4       # core data (daily kline) unavailable
EXIT_QUALITY_FAIL = 5     # snapshot written but freshness gate failed (only with --strict)
EXIT_NEEDS_MANUAL = 6     # journal: decision extraction needs manual fix


def now_cst() -> datetime:
    return datetime.now(CST)


def ms_to_date(ms: int | float) -> str:
    """Millisecond Unix timestamp -> YYYY-MM-DD in Asia/Shanghai."""
    return datetime.fromtimestamp(int(ms) / 1000, CST).strftime("%Y-%m-%d")


def ms_to_datetime(ms: int | float) -> str:
    return datetime.fromtimestamp(int(ms) / 1000, CST).strftime("%Y-%m-%d %H:%M:%S")


def date_to_ms(date: str) -> int:
    """YYYY-MM-DD -> millisecond Unix timestamp at Asia/Shanghai 00:00."""
    dt = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=CST)
    return int(dt.timestamp() * 1000)


def days_ago_ms(days: int, ref: datetime | None = None) -> int:
    ref = ref or now_cst()
    return int((ref - timedelta(days=days)).timestamp() * 1000)


def force_utf8_stdout() -> None:
    """Windows consoles default to GBK; make stdout/stderr tolerate Chinese + arrows."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass


def to_jsonable(obj):
    """Recursively convert numpy types / NaN into plain JSON types (used by indicators)."""
    import math

    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, bool):
        return bool(obj)
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else float(obj)
    if obj is None or isinstance(obj, (int, str)):
        return obj
    # numpy scalars/arrays without importing numpy at module level
    if hasattr(obj, "item"):
        try:
            return to_jsonable(obj.item())
        except Exception:
            pass
    if hasattr(obj, "tolist"):
        try:
            return to_jsonable(obj.tolist())
        except Exception:
            pass
    return obj


def dump_json(path: Path | str, payload) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with io.open(path, "w", encoding="utf-8") as fh:
        json.dump(to_jsonable(payload), fh, ensure_ascii=False, indent=2)
    return path


def load_json(path: Path | str):
    with io.open(Path(path), "r", encoding="utf-8") as fh:
        return json.load(fh)


def emit(payload: dict) -> None:
    """Print a machine-readable JSON line — every CLI script's stdout contract."""
    force_utf8_stdout()
    print(json.dumps(to_jsonable(payload), ensure_ascii=False))


def fmt_yi(value: float | None) -> str | None:
    """Format CNY amounts in 亿 (1e8) for human-facing summaries."""
    if value is None:
        return None
    return f"{value / 1e8:.2f}亿"
