# Agent Guide — AI 执行手册

执行本 skill 前必读。决策树 → 命令速查 → 话术模板 → 反模式清单。

## 1. 决策树

```
用户提到某只 A 股 / 指数 / 想要个股研判
│
├─ 首次使用（本会话第一次）
│   └─ setup_env.py --check-only → 坏则 setup_env.py 修复
│      ash_env.py --check → no_key 则进入【对话式三步引导】：
│      ① --open-admin 拉起签发页（有截图再 --guide）
│      ② 口述步骤，等用户把 Key 粘贴到对话 → AI 自己跑 --save-key
│      ③ --verify 真实验证 → 成功则原文播报欢迎语（能力清单+示例问法），
│         引导用户说出第一个标的；失败按 say_to_user 提示修复重验
│
├─ 标的纠错（强制，每次分析前）
│   resolve_ticker.py <用户输入> [--type ...]
│   ├─ verified   → 继续（warnings 必须转告）
│   ├─ ambiguous  → AskUserQuestion 让用户选 → 重新 resolve 确认 → 继续
│   ├─ not_found  → 告知 + 给相近候选；用户坚持说"就是要这个" → 说明无法分析
│   └─ no_key     → 回到 Key 引导
│
├─ 用户画像（缺了必须问，问一次长期复用）
│   profile.py --show → is_default=true 时 AskUserQuestion：
│   总资金 / 单次仓位上限% / 单笔风险% → profile.py --set --capital .. --max-position-pct ..
│   用户不愿透露 → 默认档 10万/10%/2%（报告中注明）
│
├─ 参数确认（已明确则跳过；模式判定见 SKILL.md）
│   AskUserQuestion：模式 / K线根数 / 基准 / 资金与风险%
│
├─ 数据接地
│   fetch_snapshot.py --thscode <已确认代码> ...
│   make_digest.py <snapshot.json>
│   ├─ quality.ok=false → 按 SKILL.md 护栏降级结论（不给 BUY）
│   └─ exit 4          → 数据错误：告知用户，不要编造分析
│
├─ 分析
│   ├─ fast      → 主 agent 亲自读 digest（SKILL.md 4A）
│   └─ standard/deep → 先读 agent_team.md，按 Stage 0-6 派发
│
├─ 交付：FINAL_REPORT.md（含 ## 投资决策 段）+ 回复摘要 + 免责声明
│
└─ 归档：journal.py record（needs_manual 则修 decision.json 重试）
```

## 2. 命令速查

```bash
PY="SKILL_DIR/.venv/Scripts/python.exe"; S="SKILL_DIR/scripts"
# .venv 不存在时先自举（本机约定：uv）：
#   uv run --no-project python "$S/setup_env.py"

# 环境 / Key（全部由 AI 执行；用户只在对话里粘贴 Key）
"$PY" "$S/setup_env.py" --check-only
"$PY" "$S/ash_env.py" --check
"$PY" "$S/ash_env.py" --open-admin        # 无 Key 时：拉起签发页面给用户
"$PY" "$S/ash_env.py" --guide             # 打开 assets/guide/ 指引截图（如有）
"$PY" "$S/ash_env.py" --save-key <KEY>    # 用户把 Key 粘贴到对话后，AI 执行
"$PY" "$S/ash_env.py" --verify            # 保存后真实验证一次 + 返回欢迎语

# 用户画像
"$PY" "$S/profile.py" --show                # is_default=true 则必须先询问用户
"$PY" "$S/profile.py" --set --capital 300000 --max-position-pct 10 --risk-pct 2

# 纠错
"$PY" "$S/resolve_ticker.py" 茅台
"$PY" "$S/resolve_ticker.py" 600519
"$PY" "$S/resolve_ticker.py" 白酒 --type a-share-index

# 快照 + digest + 交付
"$PY" "$S/fetch_snapshot.py" --thscode 600519.SH --bars 600 --benchmark 000300.SH
"$PY" "$S/make_digest.py" "<snapshot.json>"            # 输出 digest.json（同目录）
"$PY" "$S/generate_html.py" --digest digest.json --snapshot snapshot.json \
      --decision decision.json --team team.json        # 默认存 SKILL_DIR/reports/，自动开浏览器
                                                        # 索引：SKILL_DIR/reports/index.html

# 归档 / 复盘
"$PY" "$S/journal.py" record --decision decision.json --report FINAL_REPORT.md \
      --snapshot <snapshot.json> --mode standard
"$PY" "$S/journal.py" list --since-days 30 --markdown
"$PY" "$S/journal.py" settle --thscode 600519.SH --latest

# 单测（离线）
"$PY" -m pytest "SKILL_DIR/tests" -q
```

所有脚本 stdout 均为单行 JSON（`emit` 契约）：先看 `status` / `say_to_user` /
`quality`，再决定下一步。退出码：0 成功 · 2 需要用户输入 · 3 找不到标的 · 4 数据错误 ·
5 质量闸门失败（--strict-freshness）· 6 归档需人工修正。

## 3. 话术模板

- 要 Key（对话式三步，**命令全由 AI 执行，不向用户展示任何终端命令**）：
  「分析需要免费的扶摇数据 Key，我带你 1 分钟搞定——我已经在浏览器帮你打开了申请
  页面：请 ① 注册/登录 ② 进入『API Key 管理』③ 点击签发 ④ 把 Key 直接粘贴到
  对话里发给我就行，剩下的我来配置。」（已放置截图时补一句：「我也打开了操作指引
  截图，照着点即可。」）
- Key 验证成功（原文播报 --verify 返回的 say_to_user，核心内容）：
  「✓ Key 已生效！我可以帮你：① 个股中长线深度分析（多智能体团队，产出建仓/止损/
  目标价方案）② 快速看盘 ③ 指数/板块分析 ④ 决策复盘。你可以直接说：『分析贵州茅台
  的中长线机会』『快速看看平安银行』『600519 怎么样』『白酒行业指数如何』，或输入
  任何 A 股 / 指数 / 场内基金的名称或代码。」
- Key 验证失败：「Key 好像没生效（最常见原因：复制时带上了空格）。请回到管理页
  重新复制一份发我，我再验证一次。」
- 画像询问：「为了让仓位建议贴合你的实际情况，请告诉我：① 总资金规模大约多少？
  ② 单只股票一次建仓最多愿意占资金百分之几（默认 10%）？③ 一笔交易止损打穿时
  愿意亏资金百分之几（默认 2%）？不方便透露就用默认档 10 万/10%/2%。」
- 纠错通过：「✓ 已确认标的：600519.SH 贵州茅台（SH）」+（如有）「⚠ 上市不足一年，
  年线指标缺失」
- 纠错歧义：「『平安』有多个标的：601318.SH 中国平安 / 000001.SZ 平安银行……请确认
  是哪一个？」（用 AskUserQuestion）
- 数据降级：「本次财务数据段拉取失败，基本面结论按『数据缺失』处理，不影响技术面结论。」
- 画像不可执行提醒（sizing.shares<100 时必须说，不许沉默）：
  「⚠ 按你的画像（总资金 X / 仓位上限 Y% / 单笔风险 Z%）该方案买不足一手。
  一手成本约 A 元（占资金 B%）。可执行门槛：总资金 ≥ C 元（仓位与风险口径取大）。
  要调整画像吗？直接告诉我新数值，或运行 profile.py --set --capital <数值>
  --max-position-pct <数值> --risk-pct <数值>。资金达不到门槛时建议放弃该标的，
  不建议融资凑仓。」
- 交付时（AI 风险提示，回复开头或报告开头必带）：
  「⚠️ 本报告由 AI 流水线生成，不是持牌投资顾问服务，不构成投资建议；据此操作风险自负。」
- 免责声明：见 SKILL.md 第五步，每条输出末尾必带。

## 4. A 股特有注意点（写进分析时的硬知识）

| 规则 | 数值 | 对分析的影响 |
|------|------|--------------|
| T+1 | 当日买入次日才能卖 | 止损依赖次日执行；日内止损缺口风险要在风控中写明 |
| 主板涨跌停 | ±10% | 跌停无法成交——止损价在跌停下可能失效，需假设滑点 |
| 创业板/科创板 | ±20%（科创板前 5 日无涨跌幅） | 高波动板块止损距离要求更宽 |
| ST/*ST | ±5% + 退市风险 | resolve 阶段已告警；风控默认建议回避 |
| 整手 | 100 股及整数倍 | 仓位公式必须 floor 到整手 |
| 分红除权 | 现金分红/送股 | 技术分析用前复权价；股息率在 digest.fundamentals.dividends |
| 北交所 | ±30%，代码 .BJ | 默认支持但流动性差，报告中提示 |

## 5. 反模式清单（违者即错）

1. **跳过纠错直接分析**——用户说"茅台"你没跑 resolve_ticker 就开拉数据：错。
2. **拿模糊匹配第一名硬当答案**——ambiguous 时必须问用户，不允许自选。
3. **编造数字**——快照/digest 没有的价格、财务、估值一律写「数据缺失」。
4. **给 SHORT 评级**——A 股个股框架内没有做空；看空 = REDUCE 或 WAIT + 理由。
5. **quality.ok=false 仍给 BUY**——只允许「仅结构参考」的降级结论。
6. **股数不取整手**——shares 必须是 100 的整数倍（journal 会拦，但报告里就要对）。
7. **忘写 `## 投资决策` 段或字段格式错**——归档会 needs_manual；标签与数值必须同行。
8. **用日内思维给中长线建议**——"今天突破可以追" 这类话不允许；一切以日线级别结构表达。
9. **归档后不复述 provenance_echo**——多标的多数据源时无法对账。
10. **样本不足谈胜率**——settle 结果 <10 笔时禁止给百分比结论。
11. **不问画像就用默认资金拍股数**——profile.is_default=true 时必须先问（用户拒绝才用默认档并注明）。
12. **报告没有 AI 风险横幅**——Markdown/HTML 报告开头与交付回复都必须带 AI 理财建议风险提示。
13. **交付只有 Markdown 没有 HTML**——standard/deep 模式必须额外生成 report.html 仪表盘并帮用户打开。
14. **无 Key 只回一句"请去申请"**——必须拉起签发页面（--open-admin）+ 给出步骤，有截图再 --guide。
15. **「不可执行」只丢一句就完事**——sizing.shares<100 时必须复述门槛与三条出路，并主动问
    用户是否改画像；用户给了新数值要当场 profile.py --set 并重出股数/报告。
16. **让用户敲命令 / 贴终端命令给用户**——引导与配置全程对话式：拉起浏览器、保存 Key、
    验证、更新画像都由 AI 执行命令；用户最多粘贴一次 Key 或口述数值。终端命令只出现在
    AI 的工具调用里，不出现在给用户看的话术里。
17. **配好 Key 后不验证、不欢迎**——save-key 后必须 --verify 真实验证，成功后原文播报
    欢迎语（能力清单 + 示例问法），把球交给用户。
