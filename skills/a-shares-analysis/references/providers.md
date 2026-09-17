# Providers — 数据提供方抽象层与接入指南

`scripts/providers/` 是所有数据访问的唯一入口；任何脚本都不直接 import 厂商 SDK 或发 HTTP。

```
providers/
├── __init__.py   # 注册表 + get_provider()；ASHARES_PROVIDER 环境变量选择
├── base.py       # DataProvider 协议 + 能力集 + 归一化 schema + ProviderError
└── fuyao.py      # 扶摇（同花顺）实现 —— 默认源
```

## 运行时选择

```bash
ASHARES_PROVIDER=fuyao      # 默认，可省略
ASHARES_PROVIDER=tushare    # 登记后的其他源
```

Key 解析顺序（`ash_env.py`）：`<PROVIDER>_API_KEY` 环境变量 → `ASHARES_API_KEY` →
`SKILL_DIR/.cache/<provider>_api_key.txt`。

## 归一化 Schema（提供方必须映射到的形状）

| 类型 | 字段 |
|------|------|
| Ticker | `thscode, ticker, name, exchange, asset_type, list_date, end_date` |
| Bar（日线） | `date:"YYYY-MM-DD", open, high, low, close, volume(股), turnover(元)` |
| Quote | `thscode, ticker, last, chg, chg_pct, open, high, low, prev, volume, turnover` |
| Valuation | `thscode, name, pe_ttm, pe_mrq, pb_mrq, ps_ttm, pcf_ttm` |
| FinInds | `report:"yyyy-q", abilities:[{ability, indicators:[{index_id, value}]}]` |
| Statement | 原商字段字典（`fiscal_year / period_end_ms` 等公共字段保留） |
| CorpAction | `ex_date, dividend_per_share, per_share_bonus`（最新在前） |
| HotRank | `date, rank`（排名越小越热） |
| calendar() | `["YYYY-MM-DD", ...]` 升序 |

错误统一为 `ProviderError(kind, message, code)`，kind ∈
`auth / rate / not_found / no_data / upstream / param`——下游按 kind 决定重试、
软降级还是终止，不感知厂商错误码。

## 能力声明与软降级

每个 provider 声明 `capabilities` 集合（见 base.py `CAPABILITIES`）。
`fetch_snapshot.py` 对可选段（估值/财务/分红/热榜/基准）逐段 try/except：
失败或能力缺失 → 记入 `quality.sections_errors` → 分析流水线照常运行，对应维度
写「数据缺失」。**因此最小可用 provider 只需实现 `search + daily_kline + calendar`。**

## 新增一个数据源（以 tushare 为例）

1. 新建 `scripts/providers/tushare.py`：

```python
from providers.base import ProviderError

class TushareProvider:
    name = "tushare"
    capabilities = {"search", "daily_kline", "calendar", "valuation"}  # 按实际能力

    def __init__(self, api_key): ...

    def search(self, q, asset_type=None, limit=10):
        # 调 tushare 接口 → 映射为 [Ticker]，失败 raise ProviderError("...", msg)
        ...
    def daily_kline(self, thscode, start_ms, end_ms, adjust="forward"):
        # 映射为 [Bar]；交易日历口径、复权口径必须写清
        ...
    # 未实现的方法：保留方法签名并 raise ProviderError("param", "not implemented")
```

2. 在 `providers/__init__.py` 的 `_FACTORY_NAMES` 登记：

```python
def _make_tushare() -> DataProvider:
    from ash_env import load_api_key
    return TushareProvider(load_api_key("tushare") or "")

_FACTORY_NAMES = {"fuyao": _make_fuyao, "tushare": _make_tushare}
```

3. （可选）`ash_env.PROVIDER_ENV_VARS` 加 `"tushare": "TUSHARE_TOKEN"`。

4. 验证：`ASHARES_PROVIDER=tushare python resolve_ticker.py 茅台`，再跑一次
   `fetch_snapshot.py --skip valuation,fin_indicators,...` 分段验证。

### 实现契约清单（review 时逐条对照）

- [ ] 所有日期一律 `Asia/Shanghai` 口径输出 `YYYY-MM-DD`
- [ ] `daily_kline` 默认前复权且升序；volume 单位为股
- [ ] 错误映射到 ProviderError 六种 kind；瞬时错误（网络/上游）抛 `upstream`
- [ ] 主动限速（礼貌间隔）；对 `rate` kind 至少退避重试 2 次
- [ ] 无数据时返回空列表或抛 `no_data`，**绝不编造或补零**
- [ ] 在本文件追加该源的能力矩阵与已知局限（字段口径差异等）

## 已知源能力矩阵

| 能力 | fuyao（默认） | 说明 |
|------|---------------|------|
| search / daily_kline / quote / calendar | ✓ | 日线前复权，窗口 ≤10 年 |
| valuation | ✓ | 仅最新快照，无历史分位 |
| fin_indicators / 三大报表 | ✓ | 按报告期逐期 |
| corp_actions | ✓ | 原始分红/送股事件 |
| index_kline / index_quote / index_constituents | ✓ | 交易所指数 + 同花顺板块 |
| hot_rank_trend | ✓ | 近 60 日热榜排名 |
| 主力资金 / 高频分钟线 | ✗ | 扶摇未开放外部接入；如需接入新付费源，登记新 capability 后在 fetch_snapshot 增加对应段 |
