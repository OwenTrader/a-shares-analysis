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


def _make_yahoo() -> DataProvider:
    from providers.yahoo import YahooProvider

    return YahooProvider()  # keyless (unofficial endpoints, browser UA)


def _make_sec() -> DataProvider:
    from providers.sec import SecProvider

    return SecProvider()    # keyless (official SEC EDGAR)


_FACTORY_NAMES = {
    "fuyao": _make_fuyao,
    "yahoo": _make_yahoo,   # US/HK market data (and global index benchmarks)
    "sec": _make_sec,       # US fundamentals (SEC EDGAR)
    # "tushare": _make_tushare,   # <- register future providers here
}

# market routing: asset_type -> (market provider, fundamentals provider|None)
# us/hk are fully KEYLESS: no fuyao API key needed for those universes
MARKET_ROUTES = {
    "us-stock": ("yahoo", "sec"),
    "hk-stock": ("yahoo", None),
}


def route_market(asset_type: str) -> tuple[str, str | None]:
    return MARKET_ROUTES.get(asset_type, ("fuyao", "fuyao"))


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


__all__ = ["get_provider", "available_providers", "route_market",
           "DataProvider", "ProviderError"]
