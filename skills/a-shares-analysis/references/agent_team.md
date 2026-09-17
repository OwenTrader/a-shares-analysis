# Agent Team — A 股中长线研判团队编排（standard / deep 模式）

复刻 [TradingAgents](https://github.com/tauricresearch/tradingagents) 的多智能体分工并
A 股化：**数据接地 → 四分析师并行 → 多空辩论 → 交易员合成 → 风控三视角 → 组合经理拍板**。
与原框架的差异：美股的「新闻/社交情绪」拆成**资金情绪**与**宏观行业**两个 A 股特色角色
（热榜排名 + 指数环境），并把「交易员」改造为**中长线建仓方案师**（分批建仓/持有周期）。

> 本文档只描述 standard（11 子 agent，约 8–12 分钟）与 deep（+1 轮辩论）。
> fast 模式见 SKILL.md 第 4A 节。子 agent 用 `Agent` 工具（`subagent_type: general-purpose`）
> 派发，无需任何 LLM API Key。

## 0. 工作目录约定（归档规则——所有工件只落在 SKILL_DIR 内，绝不写当前目录）

```
SKILL_DIR/data/archives/<THSCODE>_<YYYYmmdd_HHMM>/     # THSCODE 保留点号，如 600519.SH
├── digest.json                 # 唯一阅读入口（make_digest.py 产出）
├── reports/
│   ├── 01_technical.md         # 技术分析师
│   ├── 02_fundamental.md       # 基本面分析师
│   ├── 03_flow_sentiment.md    # 资金与情绪分析师
│   ├── 04_macro_industry.md    # 宏观与行业分析师
│   ├── 05_bull_case.md         # 看多研究员
│   ├── 06_bear_case.md         # 看空研究员
│   ├── 07_trader_proposal.md   # 交易员（建仓方案）
│   ├── 08_risk_aggressive.md   # 风控-进取
│   ├── 09_risk_conservative.md # 风控-保守
│   ├── 10_risk_neutral.md      # 风控-中性
│   └── 11_portfolio_decision.md# 组合经理
├── FINAL_REPORT.md             # 交付用户（含 ## 投资决策 段）
├── decision.json               # 归档输入
└── team.json                   # 11 智能体观点（≤40字/条）

HTML 交付（唯一用户可见形态）：SKILL_DIR/reports/<ticker>_<名称>_<时间戳>.html
                              + 自动维护的 reports/index.html 索引
```

派发子 agent 时 prompt 中的输出路径一律用上述**绝对路径**。data/、reports/ 已
gitignore；若发现历史运行在别处散落了工件目录（如 `<cwd>/a-shares-analysis/`），
迁入 `data/archives/` 并删除原目录。

## 1. Stage 0 — 数据官（主 agent 亲自，不派发）

1. 纠错已通过（resolve_ticker verified），fetch_snapshot + make_digest 完成。
2. 读 digest：先看 `data_quality` 与 `_quality_raw`，把结论写进每个子 agent 的 prompt：
   - `ok=false` → 写明哪个维度不可用于决策；
   - `sections_errors` 有财务段 → 提示基本面分析师按「数据缺失」处理；
   - `fresh=false` → 写明「末端日线滞后 N 个交易日，可能停牌，请核实」。
3. 给子 agent 的**精简摘要** = digest 的 technical + fundamentals + sentiment + benchmark
   四段 + recent_bars 前 15 根。不要塞整份快照。
4. 每个 prompt 末尾必须带硬约束：
   > 只能引用上方摘要中出现的数字。任何摘要中不存在的价格、指标、财务、新闻一律不得
   > 编造；需要但未提供的信息写「数据缺失」。所有结论必须落到中长线（周线级别以上）
   > 时间框架，禁止日内思维。

## 2. Stage 1 — 四分析师并行（同一消息内派发 4 个 Agent）

### 2.1 技术分析师 `technical-analyst` → `reports/01_technical.md`
- **输入**：digest.technical + recent_bars。
- **任务**：多周期趋势判定（均线排列/金叉状态/回归斜率/ADX）、250 日区间位置与回撤、
  动量（RSI/MACD）、波动状态（ATR%/已实现波动）、量价配合、支撑阻力结构
  （structure 段的 zones + 触及次数）。输出方向性结论（多/空/中性）+ 置信度 +
  **关键价位清单**（支撑/阻力/趋势失效位）。
- **禁止**：不给买卖方案（那是交易员的事）。

### 2.2 基本面分析师 `fundamental-analyst` → `reports/02_fundamental.md`
- **输入**：digest.fundamentals（估值四指标、财务指标近 4 期、利润表年报/季报趋势、
  资产负债、现金流、股息）。
- **任务**：成长性（营收/净利/经营现金流增速与趋势）、盈利质量（毛利率/净利率/ROE/
  净利润现金含量）、偿债与报表健康（资产负债率/流动比率）、估值判断（PE/PB 与增速匹配
  ——PEG 思路；亏损或负值指标的正确解读）、分红能力与股息率。
- **约束**：指标缺失写「数据缺失」；估值结论必须给「以当前数据看偏贵/合理/偏便宜 +
  依据」，不许和稀泥；明确指出**最需要跟踪的 2 个基本面变量**。

### 2.3 资金与情绪分析师 `flow-sentiment-analyst` → `reports/03_flow_sentiment.md`
- **输入**：digest.sentiment（热榜排名现状/30 日均值/极值）、digest.technical.volume
  （量能状态）、quote（换手与成交额）。
- **任务**：热度画像（当前排名 vs 60 日分布——排名骤升常是情绪过热）、量能解读
  （放量位置在突破还是滞涨）、成交活跃度（turnover_ma20 量级）。
  **必须实际联网检索**（WebSearch/WebFetch）该股近 2 周重大公告/新闻（业绩预告、回购、
  减持、监管函、行业政策），每条标注来源与日期；检索失败写「检索失败」，严禁编造。
- **输出**：情绪与资金面结论（过热/中性/冰点）+ 风险事件清单。

### 2.4 宏观与行业分析师 `macro-industry-analyst` → `reports/04_macro_industry.md`
- **输入**：digest.benchmark（基准指数趋势、个股相对强度）、股票名称。
- **任务**：大盘环境（沪深300 趋势，牛/熊/震荡）、个股相对强度解读（超额收益与比值
  斜率）、所属行业/概念的中期景气逻辑（**必须联网检索**行业近期驱动与政策，标注来源）。
- **输出**：环境结论（顺风/逆风/中性）+ 未来 1–3 个月关键日历（财报日、行业事件、
  宏观数据窗口）。

## 3. Stage 2 — 多空辩论（可并行写作、互相批驳）

### 3.1 看多研究员 `bull-researcher` → `reports/05_bull_case.md`
输入 Stage 1 四份报告 + 摘要。构建**最强看多论点**：趋势/基本面/情绪/环境四维度中
最有力的证据链 + 最合理的建仓逻辑 + 目标位推演（结构位/估值锚）。

### 3.2 看空研究员 `bear-researcher` → `reports/06_bear_case.md`
同输入。构建**最强看空论点**：估值/趋势破坏/情绪过热/环境逆风/黑历史，并**逐条反驳**
多头论点（能读到 05 就反驳 05，否则预判性反驳）。

每份辩论必须含「对方论点中最有力的 3 条 + 我的回应」。
**deep 模式**：第 2 轮 Bull 读 06 后反驳更新 05，Bear 再读更新后的 05 反驳更新 06。

## 4. Stage 3 — 交易员（中长线建仓方案师）→ `reports/07_trader_proposal.md`

- 输入：全部 Stage 1、2 报告 + 摘要。
- 输出**唯一**可执行方案（A 股约束下）：
  - 评级建议：BUY / HOLD / REDUCE / WAIT
  - 建仓区间（回调限价 or 突破确认，二选一并说明）；可给**分两批**的建仓计划
  - 初始止损：max(1.5–2×ATR14 结构距离, 关键支撑/年线下方失效位)——取更远者；
    **必须检查该距离对应的一字跌停风险**（20% 板块单日即可能击穿止损）
  - TP1/TP2/TP3 与分批止盈比例（结构位或估值锚推演）
  - RRR（TP1 口径）；< 2 时必须说明为何仍值得做，否则建议 WAIT
  - 持有周期（如 6–12 个月）与失效条件（价格 + 基本面两条）
- 报告必须含完整 `## 投资决策` 段草稿（SKILL.md 第五步的格式），供组合经理修订。

## 5. Stage 4 — 风控三视角并行（同一消息内派发 3 个 Agent）

三个 agent 读同一份 `07_trader_proposal.md`：

| 角色 | 关注点 |
|------|--------|
| `risk-aggressive` | 是否过于保守踏空；可否第一批就给足仓位、止损放宽到结构外侧 |
| `risk-conservative` | 最坏情形：跌停无法止损、停牌流动性、财务恶化滞后披露、减持/解禁；建议减半仓位或 WAIT 的条件 |
| `risk-neutral` | 权衡两者，给折中参数与明确放行/否决理由 |

每个输出必须含：**风险等级（低/中/高）**、**建议仓位上限（占资金 %）**、**修改建议**、
**放行与否**。A 股特定风险（T+1、涨跌停、ST、次新、解禁、商誉）至少由 conservative
逐项过一遍。

## 6. Stage 5 — 组合经理 → `reports/11_portfolio_decision.md`

- 输入：全部报告 + **用户画像**（`profile.py --show`；主 agent 在派发 prompt 中提供
  total_capital / max_position_pct / risk_pct 三值，并注明是否默认档）。
- 拍板：**批准 / 否决 / 修改后批准** + 最终 `## 投资决策` 段（与 07 一致或修订后）。
- **股数必须由画像双约束反推**（脚本 `profile.py position_plan(entry, stop)` 已实现，
  报告中完整展示算术）：

```
by_risk = floor(capital × risk_pct% ÷ |entry_mid − stop| ÷ 100) × 100   # 风险预算
by_cap  = floor(capital × max_position_pct% ÷ entry_mid ÷ 100) × 100   # 单次仓位上限
shares  = min(by_risk, by_cap)                                          # A股整手
shares = 0 → 写明「按当前画像不可执行」，给出取舍：
          提高总资金 / 放宽单次仓位上限 / 接受更近止损，或直接 WAIT
默认档（10万/10%/2%）下高价股常见 shares=0——这不是错误，是画像约束的真实结论，
必须如实呈现并给出分档资金门槛。
```

- 最大不利情形与应对；触发复盘的条件（价格触及 X / 基本面变量 Y 恶化 / 时间到达 Z）。

## 7. Stage 6 — 交付（主 agent）

1. 汇总为 `FINAL_REPORT.md`：**AI 理财建议风险横幅（必须放最顶部）** → 数据质量声明 →
   核心结论 → 四分析师要点 → 辩论摘要 → 决策方案 → 股数推导（画像双约束）→
   风险与应对 → 跟踪清单 → 免责声明。
2. **生成 HTML 仪表盘报告（必做）**。先写 `team.json`：11 个智能体各一条
   **≤40 字**核心观点（`{"team":[{"role","tone","view"}]}`，tone ∈ bull/bear/neutral，
   内容压缩自各 agent 回复——例如 `{"role":"看空研究员","tone":"bear",
   "view":"Q3正常基数最危险；股息锚按下修EPS算还能跌8-18%"}`），然后：

   ```bash
   "$PY" "$SKILL_DIR/scripts/generate_html.py" --digest digest.json \
         --snapshot snapshot.json --decision decision.json --team team.json \
         --out report.html
   ```

   自绘 dashboard：**首屏 = 最终决策英雄卡 + 团队观点卡**；关键指标合并为单卡；
   价格图全宽；其余卡片走**瀑布流**。报告**固定产出于 `SKILL_DIR/reports/`** 并自动
   维护 `reports/index.html` 历史索引，生成后自动拉起浏览器；回复中必须附带
   `report_path` 与索引路径。250日位置/RSI/ADX 用分区刻度条（区间位置类
   指标，不用环形图）。输出 `profile_is_default=true` 时提醒设置真实画像。
3. 报告开头写明数据时点（快照 generated_at + 最后一根日线日期）；全程 >15 分钟时提示
   数据可能已变化。
4. 回复中给核心结论（评级/区间/止损/TP/股数/RRR），开头带 AI 风险提示一句，
   并用 present_files 展示报告（HTML 优先）。
5. 按 SKILL.md 第六步归档（decision.json 与 11 号报告的投资决策段一致）。

**硬性要求**：`FINAL_REPORT.md` 必须含 `## 投资决策` 段，字段行「标签与数值同行」
（`- **评级：BUY**`、`- **建仓区间：…**`、`- **止损：…**`、`- **TP1：…**`），
评级为 WAIT 时只保留评级与持有周期。价位与股数必须与 `11_portfolio_decision.md`
完全一致，否则归档 needs_manual。

**合规声明（每条输出必带）**：
> 本报告由多智能体分析流水线自动生成，仅供研究与教育目的，不构成任何投资建议。
> 股市有风险，投资需谨慎；所有决策与后果由投资者本人承担。
