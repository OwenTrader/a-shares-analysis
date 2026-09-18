# AGENTS.md — Agent 使用指南（安装后从这里开始）

本仓库是一个 [Agent Skill](https://agentskills.io)：`a-shares-analysis`——
A 股 / ETF / 美股 / 港股的**多智能体中长线分析**（纠错闸门 → 数据接地 →
11-agent 团队研判 → HTML 仪表盘 → 决策闭环）。人类用户说明见 [README.md](README.md)。

## 你（Agent）已安装本 skill 后，从这里开始

**主指令文件**：[`skills/a-shares-analysis/SKILL.md`](skills/a-shares-analysis/SKILL.md)。
它包含完整的流程编排与硬性纪律，**执行任何分析前必须完整阅读它**；
标准/深度模式还需先读
[`skills/a-shares-analysis/references/agent_team.md`](skills/a-shares-analysis/references/agent_team.md)
与 [`skills/a-shares-analysis/references/agent_guide.md`](skills/a-shares-analysis/references/agent_guide.md)。

## 首次运行顺序（用户零命令零安装，全部由你执行）

```text
1. 环境自举   powershell -NoProfile -ExecutionPolicy Bypass
              -File skills/a-shares-analysis/scripts/setup_env.ps1 -CheckOnly
              （incomplete → 去掉 -CheckOnly 重跑；自动装 uv+托管 Python，
               用户机器无需预装 Python/uv；failed = 网络问题，重跑即可）
2. Key 检查   skills/a-shares-analysis/scripts/ash_env.py --check
              （美股/港股可跳过 Key 直接分析；A 股 no_key 时走对话式三步引导：
               --open-admin 拉起签发页 → 用户粘贴 Key → --save-key → --verify 播报欢迎语）
3. 用户画像   skills/a-shares-analysis/scripts/profile.py --show
              （is_default=true 时先询问总资金/仓位上限/风险%，默认 10万/10%/2%）
4. 之后每次分析：纠错闸门 → 快照 → digest → 团队流水线 → HTML 报告 → 归档
   （完整流程与纪律见 SKILL.md 第一步至第六步）
```

## 命令速查（Windows；全部由你执行，用户不敲命令）

```bash
PY="skills/a-shares-analysis/.venv/Scripts/python.exe"
S="skills/a-shares-analysis/scripts"

"$PY" "$S/resolve_ticker.py" 贵州茅台                          # 纠错（强制闸门）
"$PY" "$S/resolve_ticker.py" AAPL --type us-stock              # 美股（零Key）
"$PY" "$S/fetch_snapshot.py" --thscode 600519.SH --bars 600    # 数据快照
"$PY" "$S/make_digest.py" "<snapshot.json>"                    # 精简 digest
"$PY" "$S/generate_html.py" --digest ... --snapshot ... \
      --decision ... --team team.json                          # HTML 仪表盘（自动开窗）
"$PY" "$S/journal.py" record --decision decision.json          # 决策归档
"$PY" "$S/journal.py" settle --thscode 600519.SH --latest      # 真实行情结算
```

## 硬性纪律（详见 SKILL.md 与 agent_guide.md 反模式清单）

- 未过纠错闸门不分析；歧义必须问用户；快照没有的数字一律「数据缺失」
- 报告第一元素是 AI 理财建议风险横幅；评级仅 BUY/HOLD/REDUCE/WAIT
- HTML 报告固定产出于 `skills/a-shares-analysis/reports/`，生成后附路径并开窗
- 「不可执行」必须给量化出路并主动询问是否调整画像
- 绝不向用户展示终端命令；绝不建议用户手动安装任何东西

## 示例输出

[`examples/`](examples/README.md) 内置三份真实生成的仪表盘（茅台 BUY 门控 /
苹果 WAIT / 特斯拉 WAIT 事件门控）及截图。

---
免责声明：本 skill 输出仅供研究与教育目的，不构成投资建议。
开发者微信：tradinginfinity ｜ 完全免费开源（Apache-2.0）。
