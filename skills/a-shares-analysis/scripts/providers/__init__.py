#!/usr/bin/env python3
"""Provider registry — the seam where new data sources plug in.

    from providers import get_provider
    provider = get_provider()          # reads ASHARES_PROVIDER env, default fuyao

To add a source (e.g. tushare):
  1. create providers/tushare.py implementing the DataProvider protocol
     (see references/providers.md for the normalized schemas)
  2. register it in _FACTORIES below
  3. select it at runtime with ASHARES_PROVIDER=tushare

fetch_snapshot.py degrades gracefully for capabilities a provider lacks,
so a minimal provider (search + daily_kline) still works end-to-end.
"""
from __future__ import annotations

import sys
from pathlib import Path

from providers.base import DataProvider, ProviderError

# allow running scripts/xxx.py directly (scripts dir already on sys.path then)
_HERE = Path(__file__).resolve().parent.parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


def _make_fuyao() -> DataProvider:
    from ash_env import load_api_key
    from providers.fuyao import FuyaoProvider

    key = load_api_key("fuyao")
    if not key:
        raise ProviderError("auth", "missing fuyao API key — set FUYAO_API_KEY or run "
                                     "ash_env.py --save-key <KEY> (get one at https://fuyao.aicubes.cn/admin)")
    return FuyaoProvider(key)


_FACTORY_NAMES = {
    "fuyao": _make_fuyao,
    # "tushare": _make_tushare,   # <- register future providers here
}


def available_providers() -> list[str]:
    return sorted(_FACTORY_NAMES)


def get_provider(name: str | None = None) -> DataProvider:
    from ash_env import active_provider

    name = (name or active_provider()).lower()
    factory = _FACTORY_NAMES.get(name)
    if factory is None:
        raise ProviderError("param",
                            f"unknown provider '{name}' (available: {available_providers()})")
    return factory()


__all__ = ["get_provider", "available_providers", "DataProvider", "ProviderError"]
