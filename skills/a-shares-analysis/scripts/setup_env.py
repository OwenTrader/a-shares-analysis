#!/usr/bin/env python3
"""Environment bootstrap: build SKILL_DIR/.venv with pandas+numpy(+pytest).

策略（最可能优先）：**系统 Python 优先**（多数机器已有）——当前解释器 `venv`+pip；
失败才回退 uv（uv venv + uv pip）。零依赖入口是同目录的 setup_env.ps1（Windows
自带 PowerShell，无 Python/uv 也可跑，负责发现解释器并调用本脚本或 uv）。

  引导（无 Python/uv 的机器，AI 执行）：
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup_env.ps1
  之后所有脚本统一用：
    SKILL_DIR/.venv/Scripts/python.exe  (Windows)  或 .venv/bin/python (POSIX)

  --check-only  只报告状态不修改
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
VENV_DIR = SKILL_DIR / ".venv"
VENV_PY = VENV_DIR / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
DEPS = ("pandas", "numpy", "pytest")
MIRRORS = (
    None,  # default PyPI
    "https://pypi.tuna.tsinghua.edu.cn/simple",
    "https://mirrors.aliyun.com/pypi/simple",
)


def venv_ok() -> bool:
    if not VENV_PY.is_file():
        return False
    r = subprocess.run([str(VENV_PY), "-c", "import pandas, numpy"],
                       capture_output=True)
    return r.returncode == 0


def have_uv() -> bool:
    return shutil.which("uv") is not None


def build_with_uv() -> tuple[int, str]:
    if VENV_DIR.exists():
        shutil.rmtree(VENV_DIR, ignore_errors=True)
    r = subprocess.run(["uv", "venv", str(VENV_DIR), "--python", "3.12"], capture_output=True, text=True)
    if r.returncode != 0:
        return 4, f"uv venv failed: {(r.stderr or '')[-400:]}"
    for mirror in MIRRORS:
        cmd = ["uv", "pip", "install", "--python", str(VENV_PY), *DEPS]
        if mirror:
            cmd += ["--index-url", mirror]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0 and venv_ok():
            return 0, f"venv ready via uv (installed {', '.join(DEPS)} from {mirror or 'PyPI'})"
        print(f"[setup_env] uv install failed via {mirror or 'PyPI'}: {(r.stderr or '')[-400:]}")
    return 4, "all uv pip sources failed"


def build_with_stdlib() -> tuple[int, str]:
    if VENV_DIR.exists():
        shutil.rmtree(VENV_DIR, ignore_errors=True)
    r = subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)])
    if r.returncode != 0:
        return 4, "python -m venv failed (need a real Python >=3.10)"
    for mirror in MIRRORS:
        cmd = [str(VENV_PY), "-m", "pip", "install", "--quiet", *DEPS]
        if mirror:
            cmd += ["-i", mirror]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0 and venv_ok():
            return 0, f"venv ready via pip (installed {', '.join(DEPS)} from {mirror or 'PyPI'})"
        print(f"[setup_env] pip install failed via {mirror or 'PyPI'}: {(r.stderr or '')[-400:]}")
    return 4, "all pip sources failed"


def report(code: int, status: str, detail: str) -> int:
    print(json.dumps({
        "status": status, "detail": detail, "ok": code == 0,
        "venv_python": str(VENV_PY) if VENV_PY.is_file() else None,
        "uv": have_uv(),
    }, ensure_ascii=False))
    return code


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    if args.check_only:
        ok = venv_ok()
        return report(0 if ok else 1, "ok" if ok else "incomplete",
                      "venv usable" if ok else
                      (".venv missing or lacks pandas/numpy — run: "
                       "uv run --no-project python scripts/setup_env.py"))
    if venv_ok():
        return report(0, "ok", "venv ready")
    # system python first (most machines already have one); uv is the fallback
    code, detail = build_with_stdlib()
    if code == 0:
        return report(code, "ok", detail)
    print(f"[setup_env] stdlib venv/pip failed: {detail}")
    if have_uv():
        print("[setup_env] retrying with uv...")
        code, detail = build_with_uv()
    return report(code, "ok" if code == 0 else "failed", detail)


if __name__ == "__main__":
    raise SystemExit(main())
