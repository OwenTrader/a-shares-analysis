---
name: a-shares-analysis
version: 0.1.0
description: 基于扶摇（同花顺）金融数据 API 的 A 股多智能体中长线分析。先强制纠错用户给出的股票名称/代码（模糊检索、同名消歧、退市/ST 检测），确认后拉取日线+财务+估值+热榜数据快照，再以团队模式产出研判：快速模式主 agent 直出，标准模式 11 个子 agent 流水线（技术/基本面/资金情绪/宏观行业 → 多空辩论 → 交易员 → 风控 → 组合经理）。数据源仅提供日线，因此核心定位中长线（趋势+基本面+估值）。当用户要求分析某只 A 股、看看某某股票、研判中长线机会、A 股个股深度分析时使用。仅输出研究结论，不构成投资建议，不代客下单。
license: Apache-2.0
homepage: https://github.com/OwenTrader/a-shares-analysis
---

# A 股多智能体中长线分析

用扶摇（同花顺金融数据）API 的**真实日线与财务数据**驱动团队式 A 股研判，输出结构化研究报告。

## 核心定位与硬约束

- **中长线**：数据源免费档仅提供**日线**（无分钟/tick），因此本 skill 的方法论全部围绕日线周期以上的趋势、财务与估值展开，**不做日内/短线研判**。用户要短线时，明确说明能力边界并给出日线视角下能给的结论。
- **仅做多视角**：A 股个股无便捷做空工具，评级只有 `BUY / HOLD / REDUCE / WAIT`，没有 SHORT。
- **A 股交易规则必须写进风控**：T+1、整手 100 股、涨跌停（主板 ±10%、创业板/科创板 ±20%、ST ±5%）、分红除权。
- **只读保证**：所有脚本只调用行情/财务只读接口，不涉及任何交易接口。

## 分析模式

| 模式 | 耗时 | 参与者 | 适用场景 |
|------|------|--------|----------|
| **standard（默认）** | 约 8–12 分钟 | 11 个子 agent 完整流水线 | "分析XX股票"、"XX值不值得买"、中长线决策 |
| **fast** | 1–2 分钟 | 主 agent 亲自分析，零子 agent | "快速看看XX"、"XX现在什么情况" |
| **deep** | 15 分钟以上 | standard + 2 轮多空辩论 | 重大仓位决策前 |

模式判定：用户说「快速/简单看看/什么情况」→ fast；说「深度/全面/仔细分析」→ deep；
**未指定 → standard**（中长线场景时效压力小，团队研判是本 skill 的核心价值；这与日内
行情 skill 默认快速模式相反）。

> **执行前先读 `references/agent_guide.md`**：决策树、命令速查、话术模板、反模式清单。
> 标准模式执行前**必须**再读 `references/agent_team.md`。

---

## 路径约定与环境自举

`SKILL_DIR` 指代本 SKILL.md 所在目录（安装位置因机器而异，定位本文件即可）。

**解释器解析顺序**（首个可用者胜出）：

```bash
SKILL_DIR/.venv/Scripts/python.exe   # 首选：自带隔离环境（Windows 路径；POSIX 为 .venv/bin/python）
uv run --no-project python           # 本机约定：uv（无独立 Python 的机器）
py -3 / python / python3             # 兜底（若存在真实安装）
```

`.venv` 缺失或损坏（import pandas/numpy 失败）时，**优先用 uv 修复**（本机无独立 Python）：

```bash
uv run --no-project python "SKILL_DIR/scripts/setup_env.py"            # uv venv + uv pip install
uv run --no-project python "SKILL_DIR/scripts/setup_env.py" --check-only
```

setup_env.py 策略：有 uv → `uv venv` + `uv pip install pandas numpy pytest`；
无 uv → 当前解释器 `venv` + pip（PyPI，失败回退清华/阿里镜像）。
Git Bash 里给 uv 传路径必须用 `C:/...` 形式（`/c/...` 会被判为相对路径）。
uv 也没有时：引导用户 `winget install astral-sh.uv`（或安装 Python 3.12），
**不要**继续后续步骤。修复后统一用 `.venv` 解释器。

---

## 第零步：API Key 检查与对话式引导

```bash
"$PY" "$SKILL_DIR/scripts/ash_env.py" --check     # 由 AI 执行，用户无需敲任何命令
```

**原则：所有命令由 AI 执行，用户全程只在对话里操作（最多粘贴一次 Key）。**
绝不向用户展示 python/cmd 命令——不懂编程的用户不应被要求打开终端。

- `status: ready` → 继续（首次使用可顺手 `--verify` 确认并播报欢迎语）。
- `status: no_key` → 按以下**对话式三步**引导（命令全部由 AI 在后台跑）：
  1. **拉起页面**：AI 运行 `ash_env.py --open-admin` 直接在浏览器打开
     https://fuyao.aicubes.cn/admin/ （失败才给网址让用户手动访问）；
     有截图时再运行 `--guide` 打开 `assets/guide/` 指引图。
  2. **口述步骤 + 等待粘贴**：「请在打开的页面 ① 注册/登录 ② 进入『API Key 管理』
     ③ 点击签发/创建 ④ 把生成的 Key 直接粘贴到对话里发给我」——**AI 拿到 Key 后
     自己运行 `--save-key <KEY>`**（存于 `SKILL_DIR/.cache/`，永不入版本库），
     不要求用户敲命令或设置环境变量。
  3. **真实验证 + 欢迎语**：AI 运行 `ash_env.py --verify`（真实调一次标的检索）——
     - 成功：**把返回的 `say_to_user` 欢迎语原文播报给用户**（内容为"我能做 ①个股
       中长线分析 ②快速看盘 ③指数/板块分析 ④决策复盘 + 示例问法 + 请直接说股票
       名称或代码"），引导用户说出第一个标的；
     - 失败：按 `say_to_user` 里的针对性提示处理（Key 复制带空格/限流/上游故障），
       修复后重验。
- 技术型用户主动要求自助时，才告知：环境变量 `FUYAO_API_KEY` 优先于本地缓存文件。

---

## 第一步：标的纠错（强制闸门，绝不可跳过）

用户说出的股票名/代码**必须先过纠错关**，确认无误后才能分析。人类给的输入常有：
错别字（"茅台"→贵州茅台 ✓、"贵州矛台"→需模糊匹配）、纯代码（600519）、
带交易所（600519.SH / sh600519）、全角数字（６００５１９）、代码撞车（000001 平安银行
vs 上证指数）、退市股、想分析指数却说成股票。

```bash
"$SKILL_DIR/.venv/Scripts/python.exe" "$SKILL_DIR/scripts/resolve_ticker.py" 茅台
"$SKILL_DIR/.venv/Scripts/python.exe" "$SKILL_DIR/scripts/resolve_ticker.py" 600519 --type a-share
"$SKILL_DIR/.venv/Scripts/python.exe" "$SKILL_DIR/scripts/resolve_ticker.py" 白酒 --type a-share-index  # 概念/行业指数
```

按返回 `status` 处置（退出码：0 已确认 / 2 需用户选择或缺 key / 3 找不到 / 4 数据错误）：

| status | 处置 |
|--------|------|
| `verified` | 取 `target.thscode` 进入第二步；有 `warnings`（退市/ST/次新股）必须转告用户 |
| `ambiguous` | 把 `candidates` 用 `AskUserQuestion` 列给用户选择，**不要自作主张** |
| `not_found` | 告知未找到，请用户检查名称/代码；可建议相近候选 |
| `no_key` | 回到第零步 |

**纪律：未 verified 的代码不允许进 fetch_snapshot，更不允许开始分析。**

## 第二步：确认分析参数与用户画像

**用户画像（每次分析前核对，缺了必须问）**：

```bash
"$PY" "$SKILL_DIR/scripts/profile.py" --show
```

`profile.is_default=true`（还没问过）→ 用 `AskUserQuestion` 询问三项并保存：
**总资金规模**、**单次仓位上限 %**（单只标的一次建仓最多占资金的比例）、
**单笔风险 %**（止损打穿时愿意亏损的资金比例）。用户不愿透露 → 采用默认档
**10 万总资金 / 单次最多 10% 仓位 / 单笔风险 2%**，并在报告注明「默认档」。
保存：`profile.py --set --capital <数值> --max-position-pct <数值> [--risk-pct <数值>]`。
画像持久化于 `SKILL_DIR/data/profile.json`，之后每次分析直接复用（用户资金变化时才重问）。

其余参数用 `AskUserQuestion` 确认（用户已明确给出的跳过）：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| 标的 | 已纠错确认 | — |
| 模式 | `standard` | fast / standard / deep，判定规则见开头 |
| K 线根数 | 600（≈2.5 年） | 中长线研判建议 ≥ 350（保证年线可用）；次新股自动降级 |
| 复权 | `forward` 前复权 | 技术分析必须用复权价；除权影响在 corp_actions 段单独看 |
| 基准指数 | `000300.SH` 沪深300 | 相对强度对照 |
| 资金画像 | 第一步已问/默认档 | 总资金/单次仓位上限/单笔风险，来自 profile.json |

## 第三步：拉取数据快照（数据接地）

```bash
"$SKILL_DIR/.venv/Scripts/python.exe" "$SKILL_DIR/scripts/fetch_snapshot.py" \
  --thscode 600519.SH --bars 600 --benchmark 000300.SH
```

脚本自动完成：身份复核 → 交易日历（新鲜度基准）→ 日线（前复权）+ 指标全集 →
实时快照 → 基准指数与相对强度 → 估值（PE/PB/PS/PCF）→ 近 6 期财务指标 →
利润表（年报 5 期+季报 8 期）/资产负债表/现金流量表 → 分红事件 → 近 60 日热榜排名。
快照写入 `SKILL_DIR/.cache/snapshots/<ticker>_<ts>.json`，stdout 给 JSON 摘要。

然后生成精简 digest（**所有后续分析的阅读入口**，避免整份快照进上下文）：

```bash
"$SKILL_DIR/.venv/Scripts/python.exe" "$SKILL_DIR/scripts/make_digest.py" "<snapshot.json>"
```

digest 与快照同目录，含：technical（趋势/动量/波动/结构精选）、fundamentals（估值+
财务指标近 4 期+利润表趋势+股息率）、sentiment（热榜排名）、benchmark（基准趋势+
相对强度）、recent_bars（近 30 根日线表）。

### 数据质量护栏（`quality`）——每次都必须看一眼

| 字段 | 含义与处置 |
|------|-----------|
| `ok` | 硬闸门。`false`（日线 <60 根，或滞后 >5 个交易日）→ 结论必须降级为「仅结构参考」，不得给出 BUY |
| `fresh` / `days_behind` | 日线末端落后最新交易日数；落后通常是**停牌**（本身就是重要信号），也可能是数据滞后——报告中必须写明并提示核实 |
| `sections_errors` | 某数据段拉取失败时降级记录，分析中对应维度写「数据缺失」，禁止编造 |
| `notes` | 中文告警：次新股缺年线、停牌提示等 |

纪律：`ok=false` 时不给 BUY 评级；估值/财务段缺失时基本面结论必须标注「数据缺失」；
快照中的数字是**唯一事实来源**，任何 agent 不得引用快照不存在的数字。

## 第四步：执行分析

### 4A. 快速模式（fast）——主 agent 亲自，不派发任何子 agent

1. 读 `digest.json`。
2. 按序综合研判（全部基于 digest 数字）：
   - **趋势**：均线排列（ma_stack）、MA20/60 与 MA60/250 金叉状态、60/250 日回归斜率、ADX
   - **位置**：250 日区间位置、距年线幅度、布林 %B、月度收益序列
   - **基本面**（fast 模式仅扫一眼）：估值四指标、净利润/营收增速、ROE、股息率
   - **相对强度**：对沪深300 的超额收益与比值斜率
   - **风险**：ATR%、20/60 日已实现波动、最大回撤、量能状态
3. 直接给出结论（评级 / 建仓区间 / 止损 / TP1-TP3 / RRR / 失效条件 / 持有周期），
   仓位按第五步公式（资金未提供则给区间与公式）。
4. 在回复中直接输出结论；另存 `<工作目录>/FAST_REPORT.md`（轻量，不必套完整模板）。
   fast 模式不含宏观/新闻/行业检索——涉及重大事件窗口时提示「建议用标准模式复核」。

### 4B. 标准模式（standard / deep）——11 个子 agent 完整流水线

**执行前必须读 `references/agent_team.md`**（角色定义、prompt 要点、工作目录约定）。
流水线：Stage 0 数据官（主 agent 亲自）→ Stage 1 四分析师并行（技术 / 基本面 / 资金情绪 /
宏观行业）→ Stage 2 多空辩论 → Stage 3 交易员合成 → Stage 4 风控三视角并行 →
Stage 5 组合经理拍板 → Stage 6 交付。

派发纪律：`Agent` 工具 + `subagent_type: general-purpose`；每个 prompt 必须包含
digest 精简摘要 + 角色任务 + 输出文件绝对路径；Stage 1 四个与 Stage 4 三个各自
**同一消息内并行派发**；所有 prompt 写明「只引用摘要中的数字，缺失写『数据缺失』，
严禁编造」。联网检索角色（情绪/宏观）必须标注来源与日期。

## 第五步：交付要求

- 报告写入 `<工作目录>/FINAL_REPORT.md`（工作目录：`<workspace>/a-shares-analysis/<thscode>_<YYYYmmdd_HHMM>/`）。
- **报告开头必须放 AI 理财建议风险横幅**（Markdown 报告与 HTML 报告皆然，措辞如下）：

  > ⚠️ **AI 生成内容风险提示**：本报告由多智能体 AI 流水线自动生成，属于研究演示，
  > **不是持牌投资顾问服务，不构成任何投资建议**。AI 结论可能出错、数据可能滞后或缺失，
  > 历史表现不代表未来收益；据此操作风险自负。市场有风险，投资需谨慎。

- **必须含 `## 投资决策` 段**（归档提取契约，字段行「标签与数值同行」）：

```markdown
## 投资决策
- **评级：BUY**
- **建仓区间：1480.00–1520.00**
- **止损：1420.00**
- **TP1：1650.00**
- **TP2：1780.00**
- **TP3：**
- **股数：200**（整手）
- **RRR：2.10**（TP1 口径）
- **持有周期：6–12 个月**
- **失效条件（价格）**：收盘跌破 1420 或跌破年线且 3 日不收回
- **失效条件（基本面）**：连续两季净利润同比转负
```

评级为 `WAIT` 时该段只保留评级与持有周期两行（可加一句话理由）。

- **股数由用户画像双约束反推**（脚本已实现：`profile.py` 的 `position_plan(entry, stop)`，
  报告中必须展示算术）：

```
by_risk     = floor(capital × risk_pct% ÷ |entry_mid − stop| ÷ 100) × 100   # 风险预算约束
by_cap      = floor(capital × max_position_pct% ÷ entry_mid ÷ 100) × 100   # 单次仓位上限约束
shares      = min(by_risk, by_cap)                                          # A股整手，取两者更小
shares = 0（不足一手）→ 写明「按当前画像不可执行」，给出取舍：提高资金/放宽仓位上限/更近止损
```

- 止损取两者**更远**者：波动率口径（≥1.5×ATR14）与结构失效位（关键支撑/年线下方）。
  RRR(TP1) < 2 时评级原则上降为 WAIT（中长线机会成本高，比日内交易要求更宽的盈亏比）。
- **HTML 仪表盘报告（推荐交付形态）**——先写 `team.json`（11 个智能体各一条
  **≤40 字**核心观点：`{"team":[{"role":"技术分析师","tone":"bear","view":"…"}]}`，
  tone ∈ bull/bear/neutral，内容取自各 agent 的回复摘要），然后：

```bash
"$PY" "$SKILL_DIR/scripts/generate_html.py" --digest <digest.json> \
      --snapshot <snapshot.json> --decision <decision.json> --team <team.json> \
      --out report.html
```

  自绘 dashboard（无 CSS 框架依赖，仅图表用 Chart.js CDN）：AI 风险横幅 →
  **首屏 = 最终决策英雄卡（评级/建仓/止损/TP/RRR/画像股数可执行性）+ 团队观点卡**
  → 关键指标单卡（六个 KPI 内置分栏）→ 全宽价格+均线+计划价位图 → **瀑布流内容区**
  （状态分区刻度条（250日位置/RSI/ADX 为区间位置类指标，用刻度条而非环形图）、
  量能、月度收益、基本面、市场环境——CSS columns 布局，卡片高度互不牵扯）。
  **报告固定产出于 `SKILL_DIR/reports/<代码>_<名称>_<时间戳>.html`**（用户复盘查找的
  唯一目录），每次生成自动维护 `reports/index.html` 历史索引（标的/评级/数据日期/股数，
  倒序）。生成后脚本**自动拉起浏览器打开报告**，`emit` 返回 `report_path` 与
  `index`——回复中必须附带报告绝对路径；`--no-open` 或环境变量 `ASHARES_NO_BROWSER=1`
  可关掉自动开窗。注意脚本输出的 `profile_is_default=true` 时提醒用户画像仍是默认档。
  **若输出含 `reminder`（`shares < 100` 不可执行），
  必须在回复中主动向用户复述**：不可执行原因、一手成本与占资金比、可执行资金门槛
  （两条约束口径取大），并询问是否调整画像（总资金/仓位上限/单笔风险）——用户答完
  立即 `profile.py --set` 更新并重新生成报告与股数，不允许只丢一句"不可执行"。
- 数据质量披露：`quality.ok=false` 或有 `sections_errors` 时，报告开头必须列出受影响
  范围与结论降级说明。
- **每条输出末尾附免责声明**：
  > 本报告由多智能体分析流水线自动生成，仅供研究与教育目的，不构成任何投资建议。
  > 股市有风险，投资需谨慎；所有决策与后果由投资者本人承担。

## 第六步：归档与复盘（闭环，每次分析后必做）

```bash
# 把 FINAL_REPORT 的投资决策段整理成 decision.json（字段见下），然后：
"$PY" "$SKILL_DIR/scripts/journal.py" record --decision decision.json \
      --report FINAL_REPORT.md --snapshot <snapshot.json> --mode standard
# 用户问「上次判断对不对」或定期复盘：
"$PY" "$SKILL_DIR/scripts/journal.py" list --since-days 30 --markdown
"$PY" "$SKILL_DIR/scripts/journal.py" settle --thscode 600519.SH --latest
```

decision.json 最小字段：`thscode / name / date / verdict / plans[{entry, stop, tp1, tp2?, tp3?,
shares?, rrr_tp1?, horizon?, invalidation?}]`。脚本自动校验（stop<entry、tp1>entry、整手、
RRR 重算），不合格返回 `needs_manual`（退出码 6）不入库；归档响应的 `provenance_echo`
（数据源+快照+质量）必须在回复中复述。settle 用真实日线判定 stopped / tp1_hit / open
及最大浮盈浮亏——只追加不改写历史；**样本 <10 笔时必须声明样本不足，禁止拿百分比当依据**。
记录存于 `SKILL_DIR/data/`（环境变量 `ASHARES_DATA_DIR` 可外迁，与可再生的 `.cache/`
严格分离，不入版本库）。

---

## 数据提供方切换（预留其他 API）

所有脚本经 `scripts/providers/` 抽象层取数，不直接耦合扶摇：

```bash
ASHARES_PROVIDER=fuyao    # 默认；换源只需实现 DataProvider 协议并在注册表登记
```

新数据源（tushare / baostock / akshare / 付费分钟线源等）接入方法见
**`references/providers.md`**（归一化 schema、能力声明、软降级机制）。能力不足的源
（例如只有日线没有财务）会自动降级对应分析段，流水线照常运行。

## 资源

| 文件 | 用途 |
|------|------|
| `scripts/resolve_ticker.py` | **标的纠错闸门**：名称/代码消歧、退市与 ST 告警 |
| `scripts/fetch_snapshot.py` | **数据接地**：日线+指标+估值+财务+热榜 → snapshot.json |
| `scripts/make_digest.py` | 快照 → 精简 digest（分析唯一阅读入口） |
| `scripts/generate_html.py` | **HTML 仪表盘报告**（自绘 dashboard：首屏决策+团队观点，推荐交付形态） |
| `scripts/profile.py` | **用户画像**：总资金/单次仓位上限/单笔风险（默认 10万/10%/2%），仓位双约束反推 |
| `scripts/indicators.py` | 纯 pandas 日线指标引擎（无 TA-Lib） |
| `scripts/journal.py` | 决策归档 record / list / settle（真实日线结算） |
| `scripts/ash_env.py` | API Key 管理：--check / --save-key / **--open-admin（拉起签发页）/ --guide（图文指引）** |
| `scripts/setup_env.py` | venv 自举（uv 优先，pandas+numpy，镜像回退） |
| `scripts/providers/` | **数据提供方抽象层**（base 协议 + fuyao 实现 + 注册表） |
| `assets/guide/` | Key 申请指引截图目录（png/jpg，由用户提供，--guide 打开） |
| `references/agent_guide.md` | **AI 执行手册（决策树/命令速查/话术/反模式，执行前必读）** |
| `references/agent_team.md` | **团队编排全流程（standard 模式执行前必读）** |
| `references/fuyao_api.md` | 扶摇 API 速查：端点/错误码/限流/未开放能力 |
| `references/providers.md` | 提供方协议与新增数据源指南 |
| `references/indicators.md` | 指标口径与中长线常见误读 |
| `tests/` | 离线单测（`pytest tests -q`，API 已打桩，不需要网络与 Key） |

## 环境重建

`.venv` 缺失/损坏时：`uv run --no-project python SKILL_DIR/scripts/setup_env.py`
（uv 建 venv 并装 pandas/numpy/pytest；无 uv 时回退系统 Python venv + pip，
默认 PyPI，失败自动回退清华/阿里镜像）。Git Bash 下给 uv 传路径用 `C:/...` 形式。
