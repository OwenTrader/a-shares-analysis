# 扶摇（同花顺金融数据）API 速查

权威文档：https://fuyao.aicubes.cn/docs/api-reference/overview/ （聚合版 `/llms-full.txt`）。
本文件是 skill 使用视角的速查；端点参数以官方为准。

## 通用约定

- Base URL：`https://fuyao.aicubes.cn`
- 鉴权：请求头 `X-api-key`（https://fuyao.aicubes.cn/admin 免费签发）
- 响应信封：`{code, message, request_id, data}`，**HTTP 恒 200**，业务错误看 `code`
- 时间戳：毫秒 Unix，时区 Asia/Shanghai；价格 CNY
- 标的代码：完整 thscode（`600519.SH` / `000001.SZ` / `920002.BJ` / 指数 `000300.SH` /
  同花顺指数 `886042.TI`）
- 限流：不限累计次数，但禁高频突发；`HTTP 429` 或 `code=4001` 表示限流——降速重试
  （providers/fuyao.py 已内置：串行 + 0.3s 礼貌间隔 + 1.5/2.5/3.5s 退避重试 3 次）

## 错误码

| code | 含义 | 脚本处置 |
|------|------|----------|
| 0 | 成功 | — |
| 1001–1004 | 参数缺失/格式/越界/冲突 | 调用方 bug，不重试 |
| 2001 / 2003 | 未认证 / 无权限 | 引导用户配 Key 或检查权限 |
| 3001 | 标的不存在 | 纠错环节处理 |
| 3002 | 数据未就绪（如季报未披露） | 静默跳过该期 |
| 3004 | 标的类型不支持该能力 | 跳过该数据段 |
| 4001 | 频率超限 | 退避重试 |
| 5001–5003 | 服务端/上游错误 | 退避重试，仍失败则软降级 |

## 本 skill 使用的端点

| 能力 | 端点 | 关键参数 | 备注 |
|------|------|----------|------|
| 标的检索 | `GET /api/meta/tickers/search` | `q`(必), `asset_type`, `limit≤50` | 子串匹配，跨市场消歧；纠错核心 |
| 股票日线 | `GET /api/a-share/prices/historical` | `thscode`(必,单个), `interval=1d`(必), `start`,`end`(必, ms), `adjust=forward` | **仅日线**；窗口 ≤10 年 |
| 行情快照 | `GET /api/a-share/prices/snapshot` | `thscodes`(逗号分隔) | 不含中文名 |
| 估值 | `GET /api/a-share/valuations/snapshot` | `thscodes` ≤100 个 | PE_TTM/PE_MRQ/PB_MRQ/PS_TTM/PCF_TTM，无历史估值 |
| 财务指标 | `GET /api/a-share/financials/indicators` | `thscode`, `report=yyyy-{1..4}` | 五能力：成长/盈利/偿债/营运/现金流；value 为原始字符串 |
| 利润表 | `GET /api/a-share/financials/income-statements` | `thscode`, `period=annual\|quarterly`, `limit 1-20` 或 `start/end` | limit 与 start/end 互斥 |
| 资产负债表 | `GET /api/a-share/financials/balance-sheets` | 同上 | — |
| 现金流量表 | `GET /api/a-share/financials/cash-flow-statements` | 同上 | — |
| 复权事件 | `GET /api/a-share/corporate-actions/adjustment-factors` | `thscode`, `from`,`to`(YYYY-MM-DD) | 分红/送股原始事件，最新在前 |
| 交易日历 | `GET /api/a-share/calendar/trading-days` | 无 | 近一年；新鲜度基准 |
| 指数日线 | `GET /api/a-share-index/prices/historical` | `thscode`(单个), `interval=1d`, `start`,`end` | 无 adjust（指数无复权） |
| 指数快照 | `GET /api/a-share-index/prices/snapshot` | `thscodes`(必) | 不支持空入参枚举 |
| 指数成分 | `GET /api/a-share-index/constituents/ths-stock-list` | `thscode` | 沪深300、同花顺板块/行业 |
| 指数目录 | `GET /api/a-share-index/catalog/ths-index-list` | `tag=cn_concept\|region\|tszs\|industry` | 全量不分页 |
| 热榜排名走势 | `GET /api/a-share/special-data/hot-stock-rank-trend` | `thscode`, `start_date`,`end_date`(≤1年) | 排名越小越热；无 Top30 截断 |
| 热股榜 | `GET /api/a-share/special-data/hot-stock-list` | `period=day\|hour` | Top30 |

## 未开放 / 不使用的能力

- **主力资金**（`/api/a-share/capital-flow/*`）与**高频动向**（`/api/a-share/high-frequency/*`）：
  官方标注「暂未开放外部接入」（计划接入同花顺 AI 客户端）。providers/fuyao.py 未实现
  对应 capability——**资金面分析用热榜排名 + 量能数据替代**，报告中注明该局限。
- 集合竞价、龙虎榜、涨跌停池：短线数据，与本 skill 中长线定位不符，未接入
  （需要时按 providers.md 扩展）。
- MCP：同一套能力有 MCP Tools 形态（`/docs/mcp/overview/`），本 skill 走 REST。

## 免费档位与设计对策

| 限制 | 对策 |
|------|------|
| 仅日线（无分钟/tick） | skill 定位中长线；ATR 用日线口径；止损检查考虑单日跌停幅度 |
| 估值只有最新快照（无历史分位） | 基本面分析师用 PE 与增速匹配（PEG 思路）替代历史分位；报告注明局限 |
| 财务指标按报告期逐期查询 | fetch_snapshot 自动生成近 6 个已披露报告期逐期拉取，3002 静默跳过 |
| 限流动态调整 | 串行 + 礼貌间隔 + 退避；一次分析一个快照，不重复拉取 |
