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
    """The script must never require pre-installed anything: it can install uv
    itself and let uv fetch a managed CPython (last-resort route)."""
    s = PS1.read_text(encoding="utf-8")
    for needle in ("winget", "astral.sh/uv/install.ps1", "uv venv", "--python 3.12"):
        assert needle in s, needle


def test_ps1_prefers_system_python_over_uv():
    """Typical machines already have Python — detection must come BEFORE the
    uv fallback, and the Microsoft Store stub must be rejected."""
    s = PS1.read_text(encoding="utf-8")
    assert "Find-SystemPython" in s
    py_block = s.index("Find-SystemPython")
    uv_install = s.index("installing uv via winget")
    assert py_block < uv_install, "system-python detection must precede uv install"
    assert "py -3" in s or "'-3'" in s          # windows launcher tried first
    assert s.index("system python route failed") < uv_install


def test_setup_env_py_tries_stdlib_before_uv():
    """Same preference inside the python-side bootstrap (compare CALL sites,
    not function definitions)."""
    s = (PS1.parent / "setup_env.py").read_text(encoding="utf-8")
    stdlib_call = s.index("code, detail = build_with_stdlib()")
    uv_call = s.index("code, detail = build_with_uv()")
    assert stdlib_call < uv_call, "stdlib venv must be attempted before uv"
    assert "system python first" in s
