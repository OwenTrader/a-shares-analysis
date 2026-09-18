# Changelog

## 0.3.1（2026-09-18）

- HTML 报告模板市场自适应：基准标签映射（^GSPC→标普500 / ^HSI→恒生指数，
  修复美股报告出现"沪深300"）；KPI 动态槽位（美股显示 PE(FY)/市值/币种后缀，
  替代恒空的 TTM 股息槽）；"无做空"提示按市场措辞
- 修复 AAPL 报告图表空白（生成时误用 digest 充当 snapshot 的时序 bug，归档已修正）


## 0.3.0（2026-09-18）

- **美股分析（Yahoo + SEC EDGAR，全程零 Key）**：`--type us-stock`；
  Yahoo 前复权日线/快照/指数基准（^GSPC，交易所时区感知 + 市场化新鲜度判定）；
  SEC companyfacts → FY 收入/净利/EPS/资产/现金流 + 股本 → 本地 FY 估值
  （市值/PE/PS）；估值 chips 通用化；美股规则入风控（T+0 回转/PDT/盘前盘后/1 股起）
- **港股分析（Yahoo，零 Key）**：`--type hk-stock`，基准 ^HSI，HKD，
  board lot 按 1 股粒度并强制提示人工确认
- 跨市场纠错：a-share 未命中自动回退基金与美/港股候选（标注 asset_type）；
  纠错按 asset_type 自动选 provider（美/港股不要求扶摇 Key）
- 仓位 lot 参数化（A 股 100 股 / 美股 1 股 / 港股待确认）；journal 按
  decision.asset_type 路由结算 K 线
- AAPL 实战闭环验证（600 根日线 + FY2020-2025 SEC 财报 + WAIT 研判归档）


## 0.2.0（2026-09-17）

- **场内基金（ETF）分析支持（Phase 1）**：`fund_kline` / `fund_quote` 数据能力；
  纠错支持 `--type fund-etf` 且股票检索未命中时自动回退基金类型；快照
  `--asset-type fund-etf` 分支（前复权日线+快照+基准相对强度，估值/财务/热榜自动
  降级，5 个自然年窗口护栏）；决策结算按 `asset_type` 路由基金 K 线；
  ETF 交易规则入风控（跨境/债券/货币/黄金 ETF T+0、无印花税、一手 100 份）
- digest 文件按快照名命名（`<快照>_digest.json`），修复共用 digest.json 相互覆盖


## 0.1.0（2026-09-17）

首个公开发布版本。

### 核心能力
- **标的纠错闸门**：名称/代码/全角/前缀/错别字模糊消歧，退市、ST、次新股告警
- **数据接地**（扶摇 API）：前复权日线 600 根 + 技术指标全集、估值四指标、
  近 6 期财务指标、三大报表、分红事件、热榜排名、沪深300 相对强度；质量护栏
  （停牌/滞后检测、数据段软降级）
- **团队研判**：fast（1-2 分钟直出）/ standard（11 智能体流水线）/ deep（+1 轮辩论）
  三模式；评级 BUY/HOLD/REDUCE/WAIT
- **用户画像**：总资金/单次仓位上限/单笔风险（默认 10 万/10%/2%），股数双约束
  整手反推，不可执行时给出量化出路
- **HTML 仪表盘报告**：固定目录 `reports/` 产出，自动维护 index.html 索引，
  首屏最终决策 + 11 智能体观点卡，两列瀑布流布局，生成后自动开浏览器
- **决策闭环**：journal 归档（record/list/settle），真实日线结算历史判断
- **提供方抽象层**：providers 协议 + fuyao 实现，`ASHARES_PROVIDER` 换源预留
- **对话式引导**：无 Key 时自动拉起申请页、用户仅粘贴 Key、真实验证 + 欢迎语
- **零依赖环境自举**：`setup_env.ps1` 仅用 Windows 自带 PowerShell——自动定位/安装
  uv（winget 或官方脚本，免管理员）→ `uv venv` 拉起托管版 CPython → 装依赖（镜像
  回退）；用户机器**无需预装 Python/uv**，全程 AI 执行、用户零命令
- 67 项离线单测（无需网络与 Key）

### 声明
本项目完全免费开源（Apache-2.0）。开发者微信：tradinginfinity。
https://github.com/OwenTrader/a-shares-analysis
