"""ash_env --verify: key validation + welcome text (provider mocked offline)."""
from __future__ import annotations

import providers
from ash_env import WELCOME_TEXT, verify_key


class _OkProvider:
    name = "fake"

    def search(self, q, asset_type=None, limit=10):
        return [{"thscode": "600519.SH", "ticker": "600519", "name": "贵州茅台",
                 "exchange": "SH", "asset_type": "a-share"}]


class _BrokenProvider:
    name = "fake"

    def search(self, q, asset_type=None, limit=10):
        from providers.base import ProviderError

        raise ProviderError("auth", "invalid key (code=2001)")


def test_verify_success_returns_sample_and_welcome(monkeypatch):
    monkeypatch.setattr(providers, "get_provider", lambda name=None: _OkProvider())
    out = verify_key()
    assert out["ok"] is True
    assert out["sample"][0]["thscode"] == "600519.SH"
    assert out["say_to_user"] == WELCOME_TEXT
    # welcome must introduce capabilities AND invite a ticker
    for phrase in ("中长线", "快速", "指数", "复盘", "贵州茅台", "名称或代码"):
        assert phrase in out["say_to_user"]


def test_verify_auth_failure_gives_actionable_hint(monkeypatch):
    monkeypatch.setattr(providers, "get_provider", lambda name=None: _BrokenProvider())
    out = verify_key()
    assert out["ok"] is False
    assert out["error"].startswith("[auth]")
    assert "重新复制" in out["say_to_user"]  # most common cause: stray spaces


def test_welcome_mentions_no_commands():
    """User-facing onboarding text must not demand terminal usage."""
    forbidden = ("cmd", "python ", "pip ", "terminal", "命令行")
    for word in forbidden:
        assert word not in WELCOME_TEXT.lower()
