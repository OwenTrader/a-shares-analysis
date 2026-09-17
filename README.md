# A-Shares Analysis — AI-Powered A-Share Mid/Long-Term Analysis Skill

> 🙏 **Acknowledgement / 致谢**：Powered by the [Fuyao API (同花顺金融数据)](https://fuyao.aicubes.cn/) —
> free A-share market & fundamentals data. Special thanks to 同花顺 for opening this data service.
> 本技能的数据能力基于[扶摇 API](https://fuyao.aicubes.cn/)（同花顺金融数据，免费），特此致谢。

**[🇨🇳 中文文档（完整版）](README.zh-CN.md) | [🇬🇧 English (below)](#english)**

<a id="english"></a>
## English

An [Agent Skill](https://agentskills.io) for AI assistants (ZCode / Claude Code / ...):
deep research on any A-share stock with a **multi-agent team pipeline** —
error-corrected ticker resolution → data grounding → 11-agent deliberation
(technical / fundamental / sentiment / macro analysts → bull-vs-bear debate →
trader → 3 risk reviewers → portfolio manager) → an HTML dashboard report.

- **Medium/long-term oriented**: free data tier serves daily bars only, so the
  methodology covers trend, fundamentals and valuation — not intraday trading.
- **Mandatory ticker gate**: fuzzy name/code resolution with delisting & ST warnings.
- **Position sizing from your profile**: capital / per-trade cap / risk budget,
  whole-lot (100-share) arithmetic; honest "not executable" verdicts with thresholds.
- **Closed loop**: every decision is archived and later settled against real bars.

```bash
gh skill install OwenTrader/a-shares-analysis
```

Zero prerequisites: no Python, no uv, no terminal — on first run the agent
bootstraps everything itself via Windows built-in PowerShell (auto-installs
uv + a managed CPython into the skill's `.venv`). Then just tell your
assistant: *"analyze the mid/long-term opportunity of Kweichow Moutai
(600519)"*. First run walks you through the free Fuyao API key
conversationally (browser auto-opened, paste the key, done) and asks your
capital profile once.

> 100% free & open source (Apache-2.0). Developer WeChat: **tradinginfinity**.
> AI-generated output — research/education only, NOT investment advice.

---

# A-Shares Analysis — A 股多智能体中长线分析 Skill（中文完整版）

> 🙏 **致谢**：数据能力基于[扶摇 API（同花顺金融数据）](https://fuyao.aicubes.cn/)——
> 免费的 A 股行情与财务数据服务，感谢同花顺开放接入。
> **[🇬🇧 English summary at top](#english) | [🇨🇳 中文文档（本节）](#中文)**

面向 AI Agent（ZCode / Claude Code 等）的 A 股个股深度研判技能：**先纠错、再接地、
后团队研判**，专为中长线（周线级别以上）设计。

## 它做什么

1. **标的纠错（强制闸门）**——用户说"茅台 / 600519 / ６００５１９ / sh600519 / 贵州矛台"，
   先经模糊检索 + 同名消歧 + 退市/ST/次新告警，确认唯一标的后才进入分析；歧义时列候选
   让用户选，绝不猜。
2. **数据接地**——一次快照拉全：前复权日线（默认 600 根）+ 技术指标全集、实时行情、
   沪深300 基准与相对强度、估值四指标（PE/PB/PS/PCF）、近 6 期财务指标、利润表
   （年报 5 期+季报 8 期）/资产负债表/现金流量表、分红事件、近 60 日热榜排名；
   自带质量护栏（停牌/滞后检测、数据段软降级）。
3. **团队研判（多智能体）**——standard 模式 11 个子 agent：技术 / 基本面 / 资金情绪 /
   宏观行业四分析师并行 → 多空辩论 → 交易员建仓方案 → 风控三视角 → 组合经理拍板；
   fast 模式主 agent 1–2 分钟直出。评级 `BUY / HOLD / REDUCE / WAIT`（A 股仅做多视角），
   输出建仓区间、止损、分批目标、RRR、整手股数与失效条件。
4. **用户画像与仓位**——首次使用询问总资金 / 单次仓位上限 / 单笔风险（默认档
   10 万 / 10% / 2%），持久化复用；股数按「风险预算 × 仓位上限」双约束整手反推，
   高价股资金不足时如实告知不可执行并给分档门槛。
5. **决策闭环**——每次研判归档（append-only），之后用真实日线结算（stopped / tp1_hit /
   open + 最大浮盈浮亏），积累胜率证据。
6. **HTML 仪表盘交付**——报告固定产出于 `skills/a-shares-analysis/reports/`，
   自动维护 `reports/index.html` 历史索引（标的/评级/日期/股数，方便复盘查找），
   生成后自动在浏览器打开。自绘高质量 dashboard（无 CSS 框架依赖，图表用 Chart.js）：
   **首屏即最终决策英雄卡（评级/建仓/止损/目标/画像股数可执行性）+ 11 个智能体
   各≤40字的核心观点**，配价格+均线+计划价位图、250日位置/RSI/ADX 分区刻度条、
   量能与月度收益、基本面表格；另存 Markdown 归档版。

## 为什么是中长线

数据源免费档仅提供**日线**，无分钟/tick。本 skill 的方法论因此全部围绕日线级别以上的
趋势、财务与估值构建，不做日内研判；A 股规则（T+1、±10%/20% 涨跌停、整手 100 股、
分红除权）被写进风控与仓位公式。

## 快速开始（人类视角，零命令）

对你的 AI 助手说：**"用 a-shares-analysis 分析一下贵州茅台的中长线机会"** 即可。

**零前置要求：无需 Python、无需 uv、无需打开终端**——首次使用时 AI 通过 Windows
自带的 PowerShell 自动装齐一切（自动安装 uv 与托管版 Python 到 skill 的 `.venv`，
只需网络），然后带你完成引导（全程对话）：帮你拉起 Key 申请页面 → 你注册并粘贴
Key 到对话 → AI 配置并真实验证 → 播报能力清单（个股中长线分析 / 快速看盘 /
指数板块分析 / 决策复盘）→ 你说出想分析的标的。AI 还会询问一次你的资金画像
（总资金 / 单次仓位上限 / 单笔风险，默认 10 万/10%/2%）。

<details>
<summary>进阶：手动 CLI（可选，普通用户无需使用）</summary>

```bash
cd skills/a-shares-analysis
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup_env.ps1  # 零依赖自举
.venv/Scripts/python.exe scripts/ash_env.py --open-admin      # 打开 Key 申请页
.venv/Scripts/python.exe scripts/ash_env.py --save-key <KEY>  # 保存 Key
.venv/Scripts/python.exe scripts/ash_env.py --verify          # 验证 + 欢迎语
.venv/Scripts/python.exe scripts/profile.py --set --capital 1300000 --max-position-pct 10 --risk-pct 3
```

</details>

## 目录

```
skills/a-shares-analysis/
├── SKILL.md                # Agent 入口（流程编排与硬性纪律）
├── references/             # agent_guide / agent_team / fuyao_api / providers / indicators
├── scripts/                # resolve_ticker / fetch_snapshot / make_digest / journal ...
│   └── providers/          # 数据提供方抽象层（fuyao 默认，可扩展 tushare 等）
├── assets/guide/           # Key 申请图文指引（3 张截图 + captions）
├── tests/                  # 离线单测（API 打桩，无需网络与 Key）
├── .cache/                 # 快照与 Key 缓存（可再生，不入库）
└── data/                   # 决策日志（append-only，不入库）
```

## 数据源与扩展

默认数据源为[扶摇（同花顺金融数据）API](https://fuyao.aicubes.cn/docs/api-reference/overview/)。
所有取数经 provider 抽象层，新增数据源（tushare / baostock / akshare / 付费分钟线源）
只需实现 `DataProvider` 协议并登记，能力不足自动降级对应分析段——见
`references/providers.md`。

## 免责声明与开源声明

本项目**完全免费开源**（Apache-2.0，见 [LICENSE](LICENSE)），仓库地址
https://github.com/OwenTrader/a-shares-analysis ，开发者微信 tradinginfinity。
输出由 AI 流水线自动生成，仅供研究与教育目的，不构成任何投资建议。股市有风险，
投资需谨慎；所有决策与后果由投资者本人承担。

## License

Apache-2.0 © OwenTrader
