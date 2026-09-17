"""setup_env.ps1 — zero-dependency bootstrap smoke test (Windows only)."""
from __future__ import annotations

import json
import platform
import subprocess
from pathlib import Path

import pytest

PS1 = Path(__file__).resolve().parent.parent / "scripts" / "setup_env.ps1"

pytestmark = pytest.mark.skipif(
    platform.system() != "Windows" or not Path(
        "C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe").exists(),
    reason="powershell bootstrap is Windows-only",
)


def test_ps1_exists():
    assert PS1.is_file()


def test_ps1_check_only_emits_json():
    r = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", str(PS1), "-CheckOnly"],
        capture_output=True, text=True, timeout=120)
    assert r.returncode in (0, 1)
    payload = json.loads([l for l in r.stdout.splitlines() if l.strip().startswith("{")][-1])
    assert payload["status"] in ("ok", "incomplete")
    if payload["status"] == "ok":
        assert Path(payload["venv_python"]).is_file()


def test_ps1_contains_zero_dependency_chain():
    """The script must never require pre-installed Python: it must be able to
    install uv itself and let uv fetch a managed CPython."""
    s = PS1.read_text(encoding="utf-8")
    for needle in ("winget", "astral.sh/uv/install.ps1", "uv venv", "--python 3.12"):
        assert needle in s, needle
