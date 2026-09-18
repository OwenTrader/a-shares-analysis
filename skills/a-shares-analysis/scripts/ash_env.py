#!/usr/bin/env python3
"""API-key & provider configuration resolution.

Key lookup order for the default provider `fuyao`:
  1. env FUYAO_API_KEY            (per-provider, highest priority)
  2. env ASHARES_API_KEY          (generic fallback, any provider)
  3. SKILL_DIR/.cache/<provider>_api_key.txt   (saved via --save-key)

CLI:
  python ash_env.py --check                  # JSON status report
  python ash_env.py --save-key <KEY>         # persist key for default provider
  python ash_env.py --save-key <KEY> --provider fuyao
"""
from __future__ import annotations

import argparse
import os
import stat
from pathlib import Path

from ash_common import CACHE_DIR, SKILL_DIR, emit, force_utf8_stdout

PROVIDER_ENV_VARS = {
    # provider name -> dedicated env var; ASHARES_API_KEY is the shared fallback
    "fuyao": "FUYAO_API_KEY",
}

# user-facing guidance for getting a fuyao key (used by --check / --open-admin / --guide)
KEY_GUIDE = {
    "url": "https://fuyao.aicubes.cn/admin/",
    "say_to_user": (
        "还没有配置 API Key，我带你 3 分钟搞定：\n"
        "  1. 打开 https://fuyao.aicubes.cn/admin/ （我可以直接帮你拉起浏览器）\n"
        "  2. 注册/登录账号\n"
        "  3. 进入「API Key 管理」页面，点击签发/创建 API Key\n"
        "  4. 复制生成的 Key 发给我，我保存到本地后即可开始分析"
    ),
    "steps": [
        "浏览器打开 https://fuyao.aicubes.cn/admin/",
        "注册 / 登录（支持手机号或邮箱）",
        "进入「API Key 管理」，点击「签发/创建」",
        "复制 Key，发回给 AI 助手或运行: ash_env.py --save-key <KEY>",
    ],
}


# welcome message shown right after the key is verified working (one real API call)
WELCOME_TEXT = (
    "✓ Key 已生效！我现在可以帮你做这些：\n"
    "  ① 个股中长线深度分析（A 股 / 美股 / 港股）——多智能体团队研判，"
    "产出建仓/止损/目标价方案\n"
    "  ② 快速看盘——1-2 分钟给出某只股票的现状结论\n"
    " ③ 指数 / 板块 / 场内 ETF——沪深300、白酒指数、酒ETF 等的趋势\n"
    "  ④ 决策复盘——用真实行情结算之前每一次判断的对错\n"
    "你可以直接说：「分析贵州茅台的中长线机会」「快速看看平安银行」"
    "「600519 怎么样」「白酒行业指数如何」，或输入任何 A 股 / 指数 / "
    "场内基金的名称或代码。\n"
    "另外：分析美股 / 港股（如「分析特斯拉」「腾讯港股怎么样」）"
    "不需要任何 Key，随时可用。"
)


def verify_key(provider_name: str | None = None) -> dict:
    """One real API call to confirm the key works; on success returns the welcome text."""
    import providers
    from providers.base import ProviderError

    try:
        provider = providers.get_provider(provider_name)
        hits = provider.search("600519", asset_type="a-share", limit=3)
        sample = [{"thscode": h.get("thscode"), "name": h.get("name")} for h in hits[:3]]
        return {"ok": True, "provider": provider.name, "sample": sample,
                "say_to_user": WELCOME_TEXT}
    except ProviderError as exc:
        hint = {
            "auth": "Key 无效或未生效，请回到管理页重新复制（注意前后空格）",
            "rate": "触发限流，稍等几秒我再试一次即可",
            "upstream": "数据源暂时不可用，稍后重试；Key 本身可能没问题",
        }.get(exc.kind, f"验证失败：{exc.message}")
        return {"ok": False, "error": f"[{exc.kind}] {exc.message}",
                "say_to_user": f"✗ {hint}"}


def open_admin_page() -> bool:
    """Open the key-signing admin page in the default browser."""
    import webbrowser

    try:
        return webbrowser.open(KEY_GUIDE["url"])
    except Exception:
        return False


GUIDE_CAPTIONS = SKILL_DIR / "assets" / "guide" / "captions.json"


def load_guide_captions() -> list[dict]:
    """Step captions paired with screenshot filenames (captions.json next to images)."""
    import json as jsonlib

    if not GUIDE_CAPTIONS.is_file():
        return []
    try:
        data = jsonlib.loads(GUIDE_CAPTIONS.read_text(encoding="utf-8"))
        return data.get("steps", [])
    except (ValueError, OSError):
        return []


def open_guide_images() -> list[str]:
    """Open registration guide screenshots in assets/guide/ (if any)."""
    import webbrowser

    guide_dir = SKILL_DIR / "assets" / "guide"
    opened = []
    if guide_dir.is_dir():
        for img in sorted(guide_dir.glob("*.png")) + sorted(guide_dir.glob("*.jpg")):
            try:
                if webbrowser.open(img.resolve().as_uri()):
                    opened.append(img.name)
            except Exception:
                continue
    return opened


def key_file(provider: str) -> Path:
    return CACHE_DIR / f"{provider}_api_key.txt"


def load_api_key(provider: str = "fuyao") -> str | None:
    env_name = PROVIDER_ENV_VARS.get(provider)
    for candidate in ([env_name] if env_name else []) + ["ASHARES_API_KEY"]:
        value = (os.environ.get(candidate) or "").strip()
        if value:
            return value
    path = key_file(provider)
    if path.is_file():
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    return None


def save_api_key(key: str, provider: str = "fuyao") -> Path:
    key = key.strip()
    if not key:
        raise ValueError("empty api key")
    path = key_file(provider)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(key + "\n", encoding="utf-8")
    try:  # best-effort tighten perms; Windows ignores mode bits for most ACLs
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        pass
    return path


def active_provider() -> str:
    """Provider selection: env ASHARES_PROVIDER overrides, default fuyao."""
    return (os.environ.get("ASHARES_PROVIDER") or "fuyao").strip().lower()


def main() -> int:
    force_utf8_stdout()
    parser = argparse.ArgumentParser(description="A-shares skill env/key manager")
    parser.add_argument("--check", action="store_true", help="report key status as JSON")
    parser.add_argument("--save-key", metavar="KEY", help="persist API key")
    parser.add_argument("--open-admin", action="store_true",
                        help="open the key-signing page in the default browser")
    parser.add_argument("--guide", action="store_true",
                        help="open guide screenshots (assets/guide/) if provided")
    parser.add_argument("--verify", action="store_true",
                        help="make one real API call to confirm the key works (used after save)")
    parser.add_argument("--provider", default=None, help="target provider (default: active)")
    args = parser.parse_args()

    provider = args.provider or active_provider()
    if args.save_key:
        path = save_api_key(args.save_key, provider)
        emit({
            "status": "saved",
            "provider": provider,
            "key_file": str(path),
            "note": "key stored locally in plaintext; .cache/ must never be committed",
        })
        return 0
    if args.open_admin:
        ok = open_admin_page()
        emit({
            "status": "opened" if ok else "open_failed",
            "url": KEY_GUIDE["url"],
            "steps": KEY_GUIDE["steps"],
            "say_to_user": ("✓ 已在浏览器打开签发页面，请登录后在「API Key 管理」创建 Key 并发给我"
                            if ok else
                            f"无法自动打开浏览器，请手动访问 {KEY_GUIDE['url']} 并按步骤签发"),
        })
        return 0 if ok else 2
    if args.verify:
        if not load_api_key(provider):
            emit({"status": "no_key", "say_to_user": KEY_GUIDE["say_to_user"],
                  "admin_url": KEY_GUIDE["url"]})
            return 2
        result = verify_key(provider)
        result["status"] = "verified" if result["ok"] else "verify_failed"
        emit(result)
        return 0 if result["ok"] else 4
    if args.guide:
        opened = open_guide_images()
        captions = load_guide_captions()
        steps_text = "\n".join(
            f"  第{i}步（{c['image']}）：{c['caption']}"
            for i, c in enumerate(captions, 1))
        if not steps_text:
            steps_text = "\n".join(f"  第{i}步：{s}" for i, s in enumerate(KEY_GUIDE["steps"], 1))
        emit({
            "status": "opened" if opened else "no_images",
            "opened": opened,
            "guide_dir": str(SKILL_DIR / "assets" / "guide"),
            "captions": captions,
            "say_to_user": ("✓ 已在浏览器打开注册指引截图，按下面 3 步操作：\n" + steps_text +
                            "\n完成后把 sk-fuyao- 开头的 Key 粘贴发给我即可"
                            if opened else
                            "assets/guide/ 下暂无指引截图；请将注册/签发页面的 png 放入该目录后重试"),
        })
        return 0
    if args.check:
        key = load_api_key(provider)
        source = None
        if key:
            env_name = PROVIDER_ENV_VARS.get(provider)
            if env_name and os.environ.get(env_name, "").strip():
                source = f"env:{env_name}"
            elif os.environ.get("ASHARES_API_KEY", "").strip():
                source = "env:ASHARES_API_KEY"
            else:
                source = f"file:{key_file(provider)}"
        emit({
            "status": "ready" if key else "no_key",
            "provider": provider,
            "has_key": bool(key),
            "key_source": source,
            "admin_url": None if key else KEY_GUIDE["url"],
            "say_to_user": None if key else KEY_GUIDE["say_to_user"],
            "next_action": None if key else [
                "运行: python ash_env.py --open-admin   # 直接拉起签发页面",
                "或运行: python ash_env.py --guide       # 打开图文指引（如有截图）",
            ],
        })
        return 0 if key else 2
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
