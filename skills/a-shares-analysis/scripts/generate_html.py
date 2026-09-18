#!/usr/bin/env python3
"""Render the final analysis as a self-styled HTML dashboard (Chart.js only for charts).

  python generate_html.py --digest digest.json --snapshot snapshot.json \
      [--decision decision.json] [--team team.json] [--out report.html] [--title "..."]

Layout (first screen = decision):
  risk banner -> header (identity + verdict + profile chip)
  -> FIRST SCREEN: decision hero card (verdict / entry / stop / TPs / sizing)
                    + team-view card (each agent's <=40-char take, color-coded)
  -> KPI strip -> price chart + status zone-bars (250d position / RSI / ADX)
  -> volume + monthly returns -> fundamentals + market context -> footer.

Design: hand-rolled clean-dashboard CSS (no CSS framework CDN); charts use
Chart.js CDN. Numbers come verbatim from digest/snapshot/decision/profile/team.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
from pathlib import Path

from ash_common import SKILL_DIR, emit, force_utf8_stdout, load_json, now_cst

CHARTJS = "https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"

# fixed deliverable directory — every report lands here so the user can always
# find past analyses in one place; index.html (auto-maintained) lists them all
REPORTS_DIR = SKILL_DIR / "reports"
MANIFEST_PATH = REPORTS_DIR / "index.json"

# developer / project attribution — shown in every report & index footer
DEV_WECHAT = "tradinginfinity"
REPO_URL = "https://github.com/OwenTrader/a-shares-analysis"
FOOTER_NOTE = (
    f"开发者微信：{DEV_WECHAT} ｜ 本项目完全免费开源（Apache-2.0）：{REPO_URL}"
)

AI_RISK_BANNER = (
    "⚠️ AI 生成内容风险提示：本报告由多智能体 AI 流水线自动生成，属于研究演示，"
    "<b>不是持牌投资顾问服务，不构成任何投资建议</b>。AI 结论可能出错、数据可能滞后或缺失，"
    "历史表现不代表未来收益；据此操作风险自负。市场有风险，投资需谨慎。"
)

C_BULL, C_BEAR, C_NEUT = "#16a34a", "#dc2626", "#64748b"
ROLE_TONES = {"bull": C_BULL, "bear": C_BEAR, "neutral": C_NEUT}
VERDICT_STYLE = {
    "BUY": ("buy", C_BULL), "HOLD": ("hold", "#2563eb"),
    "REDUCE": ("reduce", "#d97706"), "WAIT": ("wait", "#64748b"),
}


def esc(v) -> str:
    return html.escape("" if v is None else str(v))


def fnum(v, nd=2, suffix="") -> str:
    if v is None:
        return "--"
    try:
        return f"{float(v):,.{nd}f}{suffix}"
    except (TypeError, ValueError):
        return esc(v)


# --------------------------------------------------------------------------
# building blocks
# --------------------------------------------------------------------------
def zone_bar(label: str, value: float | None, vmax: float, zones: list[dict],
             unit: str = "", lo_label: str = "", hi_label: str = "") -> str:
    """Horizontal zone bar with a position marker — the right component for
    'where does the current reading sit in its canonical range' metrics."""
    if value is None:
        return (f'<div class="zbar"><div class="zbar-head"><span>{esc(label)}</span>'
                f'<b class="muted">--</b></div><div class="zbar-track muted-track"></div></div>')
    pos = max(0.0, min(value / vmax * 100, 100.0))
    zone_tag = next((z["tag"] for z in zones if z["from"] <= value < z["to"]), "")
    zone_color = next((z["color"] for z in zones if z["from"] <= value < z["to"]), C_NEUT)
    segs = "".join(
        f'<i style="left:{z["from"] / vmax * 100:.1f}%;'
        f'width:{(z["to"] - z["from"]) / vmax * 100:.1f}%;background:{z["color"]}"></i>'
        for z in zones)
    return f"""
<div class="zbar">
  <div class="zbar-head"><span>{esc(label)}</span>
    <b>{fnum(value, 1)}{unit} <em style="color:{zone_color}">{esc(zone_tag)}</em></b></div>
  <div class="zbar-track">{segs}<span class="zmark" style="left:{pos:.1f}%"></span></div>
  <div class="zbar-scale"><span>{esc(lo_label)}</span><span>{esc(hi_label)}</span></div>
</div>"""


def kpi_card_all(digest: dict) -> str:
    """All key metrics in ONE card (internal grid) — avoids six tiny cards."""
    t = digest.get("technical") or {}
    quote = digest.get("quote") or {}
    f = digest.get("fundamentals") or {}
    ma = t.get("moving_averages") or {}
    r250 = t.get("range_250d") or {}

    def updown(v):
        try:
            return "up" if float(v) >= 0 else "down"
        except (TypeError, ValueError):
            return ""

    items = [
        ("现价", fnum(t.get("last_close")), f"当日 {fnum(quote.get('chg_pct'))}%", updown(quote.get("chg_pct"))),
        ("PE (TTM)", fnum((f.get("valuation") or {}).get("pe_ttm")), "", ""),
        ("股息率 TTM", fnum((f.get("dividends") or {}).get("yield_ttm_pct"), 2, "%"), "", ""),
        ("距年线",
         fnum((t.get("last_close") / ma["ma_250"] - 1) * 100 if (t.get("last_close") and ma.get("ma_250")) else None, 1, "%"),
         f"MA250 {fnum(ma.get('ma_250'), 0)}", ""),
        ("250日回撤", fnum(r250.get("drawdown_from_high_pct"), 1, "%"),
         f"区间位置 {fnum(r250.get('position_pct'), 1)}%", ""),
        ("ATR%", fnum((t.get("atr") or {}).get("atr_pct"), 2, "%"),
         f"20日波动 {fnum((t.get('volatility') or {}).get('realized_vol_20d_ann_pct'), 1)}%", ""),
    ]
    cells = "".join(
        f'<div class="kpi"><div class="kpi-label">{esc(k)}</div>'
        f'<div class="kpi-value {cls}">{v}</div>'
        + (f'<div class="kpi-sub">{esc(s)}</div>' if s else "") + "</div>"
        for k, v, s, cls in items)
    return (f'<div class="card kpi-card"><div class="card-title">关键指标'
            f'<small>现价 · 估值 · 股息 · 趋势位置 · 波动</small></div>'
            f'<div class="kpis">{cells}</div></div>')


def _not_executable_alert(sizing: dict, profile: dict) -> str:
    """Not-executable must be actionable: quantified ways out + how to change the profile."""
    import math

    max_pos = fnum(profile.get("max_position_pct"), 0)
    risk_p = fnum(profile.get("risk_pct"), 1)
    cap_pct = sizing.get("cap_pct_1lot")
    if cap_pct is not None and cap_pct <= 100:
        opt_cap = (f"① <b>放宽仓位上限</b>：一手占总资金 {fnum(cap_pct, 1)}%，高于当前上限 {max_pos}%——"
                   f"把单次仓位上限调到 ≥ {math.ceil(cap_pct)}% 即可买一手（是否值得请自行权衡风险）")
    else:
        opt_cap = (f"① <b>放宽仓位上限</b>：<u>不可行</u>——一手成本已达总资金的 {fnum(cap_pct, 0)}%，"
                   f"超出任何合理仓位上限")
    opt_capital = (f"② <b>提高总资金</b>：一手需 ≥ {fnum(sizing.get('required_capital_by_cap'), 0)} 元"
                   f"（仓位上限 {max_pos}% 口径）且 ≥ {fnum(sizing.get('required_capital_by_risk'), 0)} 元"
                   f"（单笔风险 {risk_p}% 口径）→ <b>总资金 ≥ {fnum(sizing.get('min_capital_1lot'), 0)} 元</b>")
    opt_giveup = "③ <b>放弃本标的</b>：等回调降低一手成本、换低价标的，或保持观望（不建议融资凑仓）"
    howto = ("<b>如何更新画像（二选一）</b>：直接对 AI 助手说「把总资金改为 XX 万」或"
             "「单次仓位上限改为 XX%」；或自行运行<br>"
             "<code>profile.py --set --capital &lt;数值&gt; --max-position-pct &lt;数值&gt; --risk-pct &lt;数值&gt;</code>")
    return (f'<div class="alert danger"><b>⚠ 按当前画像不可执行</b>'
            f'（风险预算 {fnum(sizing.get("shares_by_risk", 0), 0)} 股 / '
            f'仓位上限 {fnum(sizing.get("shares_by_cap", 0), 0)} 股，取小后不足一手 100 股）<br>'
            f'一手（100 股）成本 ≈ {fnum(sizing.get("cost_1lot"), 0)} 元。三条出路：<br>'
            f'{opt_cap}<br>{opt_capital}<br>{opt_giveup}<br>'
            f'<span class="howto">{howto}</span></div>')


def decision_hero(decision: dict | None, sizing: dict, digest: dict,
                  profile: dict | None = None) -> str:
    if not decision:
        return ('<div class="card hero"><div class="card-title">最终决策</div>'
                '<p class="muted">未提供 decision.json（fast 模式或未归档）。</p></div>')
    verdict = decision.get("verdict", "--")
    if verdict == "WAIT":
        plan = (decision.get("plans") or [{}])[0]
        return (f'<div class="card hero"><div class="card-title">最终决策</div>'
                f'<span class="verdict wait">WAIT 观望</span>'
                f'<p class="muted mt8">{esc(plan.get("invalidation") or "")}</p></div>')
    cls, color = VERDICT_STYLE.get(verdict, ("wait", C_NEUT))
    plan = (decision.get("plans") or [{}])[0]
    entry = plan.get("entry")
    cells = [("建仓区间", f'{fnum(plan.get("entry_low"), 0)}–{fnum(plan.get("entry_high"), 0)}'),
             ("综合成本", fnum(entry, 1)),
             ("止损", fnum(plan.get("stop"), 1)),
             ("RRR (TP1)", fnum(plan.get("rrr_tp1"), 2))]
    for i in (1, 2, 3):
        tp = plan.get(f"tp{i}")
        if tp and entry:
            cells.append((f"TP{i}", f'{fnum(tp, 0)} <small>+{(float(tp) / float(entry) - 1) * 100:.1f}%</small>'))
    shares = sizing.get("shares")
    if shares is None:
        cells.append(("股数", "按画像反推"))
    else:
        cells.append(("股数(画像)", f"{shares:,}" if shares >= 100 else "0（不可执行）"))
    grid = "".join(f'<div class="hero-cell"><span>{esc(k)}</span><b>{v}</b></div>' for k, v in cells)

    if shares is not None and shares >= 100:
        sizing_html = (f'<div class="alert ok">✓ 按当前画像可执行 <b>{shares:,} 股</b>'
                       f'（{fnum(sizing.get("position_value"), 0)} 元 · 仓位 {fnum(sizing.get("position_pct"), 1)}%'
                       f' · 止损损失 {fnum(sizing.get("risk_amount_at_stop"), 0)} 元 = {fnum(sizing.get("risk_pct_actual"), 2)}%'
                       f' · 约束：{esc(sizing.get("binding_constraint"))}）</div>')
    elif shares is not None:
        sizing_html = _not_executable_alert(sizing, profile or {})
    else:
        sizing_html = ""
    horizon = plan.get("horizon") or "--"
    return f"""
<div class="card hero">
  <div class="card-title">最终决策</div>
  <div class="hero-head">
    <span class="verdict {cls}">{esc(verdict)}</span>
    <span class="chip">RRR {fnum(plan.get("rrr_tp1"), 2)}</span>
    <span class="chip">持有 {esc(horizon)}</span>
    <span class="chip" style="color:{color}">做多视角 · A股无做空</span>
  </div>
  <div class="hero-grid">{grid}</div>
  {sizing_html}
  <div class="invalid"><b>失效条件</b>：{esc(plan.get("invalidation") or "--")}</div>
</div>"""


def team_card(team: list[dict] | None) -> str:
    if not team:
        return ('<div class="card"><div class="card-title">团队观点</div>'
                '<p class="muted">未提供 team.json。</p></div>')
    items = []
    for m in team:
        tone = ROLE_TONES.get(m.get("tone", "neutral"), C_NEUT)
        items.append(
            f'<li><i style="background:{tone}"></i><span class="role">{esc(m.get("role", ""))}</span>'
            f'<span class="view">{esc(m.get("view", ""))}</span></li>')
    return (f'<div class="card team"><div class="card-title">团队观点'
            f'<small>{len(team)} 个智能体 · 各≤40字</small></div>'
            f'<ul class="team-list">{"".join(items)}</ul></div>')


def status_card(digest: dict) -> str:
    t = digest.get("technical") or {}
    r250 = t.get("range_250d") or {}
    bars = [
        zone_bar("250日区间位置", r250.get("position_pct"), 100,
                 [{"from": 0, "to": 30, "color": "#93c5fd", "tag": "低位区"},
                  {"from": 30, "to": 70, "color": "#cbd5e1", "tag": "中位区"},
                  {"from": 70, "to": 100, "color": "#fca5a5", "tag": "高位区"}],
                 unit="%", lo_label="年内低点", hi_label="年内高点"),
        zone_bar("RSI-14", (t.get("rsi") or {}).get("rsi_14"), 100,
                 [{"from": 0, "to": 30, "color": "#86efac", "tag": "超卖"},
                  {"from": 30, "to": 70, "color": "#cbd5e1", "tag": "中性"},
                  {"from": 70, "to": 100, "color": "#fca5a5", "tag": "超买"}],
                 lo_label="0 超卖", hi_label="100 超买"),
        zone_bar("ADX-14 趋势强度", (t.get("adx") or {}).get("adx_14"), 60,
                 [{"from": 0, "to": 20, "color": "#cbd5e1", "tag": "无趋势"},
                  {"from": 20, "to": 40, "color": "#93c5fd", "tag": "趋势形成"},
                  {"from": 40, "to": 60, "color": "#c4b5fd", "tag": "强趋势"}],
                 lo_label="0", hi_label="60+"),
    ]
    return (f'<div class="card"><div class="card-title">状态读数'
            f'<small>区间位置类指标 · 分区刻度</small></div>'
            f'{"".join(bars)}</div>')


def market_card(digest: dict) -> str:
    t = digest.get("technical") or {}
    bench, senti = digest.get("benchmark") or {}, digest.get("sentiment") or {}
    rs60 = ((bench.get("relative_strength") or {}).get("rs_60d") or {}).get("ratio_slope_ann_pct")
    rows = [("沪深300 60日", fnum((bench.get("trend") or {}).get("ret_60d_pct"), 1, "%")
             + f'（{esc((bench.get("trend") or {}).get("ma_stack") or "--")}）'),
            ("120日超额收益", fnum((bench.get("relative_strength") or {}).get("excess_return_120d_pct"), 1, "%")),
            ("60日RS斜率(年化)", fnum(rs60, 1)),
            ("热榜排名 最新/30日均", f'{esc(senti.get("rank_latest", "--"))} / {esc(senti.get("rank_avg_30d", "--"))}'),
            ("20日已实现波动(年化)", fnum((t.get("volatility") or {}).get("realized_vol_20d_ann_pct"), 1, "%")),
            ("月度收益连续性", _month_streak(t))]
    trs = "".join(f'<div class="drow"><span>{k}</span><b>{v}</b></div>' for k, v in rows)
    return f'<div class="card"><div class="card-title">市场环境</div><div class="dgrid">{trs}</div></div>'


def _month_streak(t: dict) -> str:
    months = (t.get("monthly_returns") or [])[-3:]
    return " · ".join(f'{m["month"][2:]} {m["pct"]:+.1f}%' for m in months) or "--"


VAL_LABELS = [("pe_ttm", "PE TTM"), ("pe_mrq", "PE MRQ"), ("pe_fy", "PE(FY)"),
              ("pb_mrq", "PB"), ("ps_ttm", "PS"), ("ps_fy", "PS(FY)"),
              ("pcf_ttm", "PCF"), ("market_cap", "市值"), ("shares_outstanding", "股本")]


def fundamentals_card(digest: dict) -> str:
    f = digest.get("fundamentals") or {}
    val = f.get("valuation") or {}
    chips_val = "".join(f'<span class="chip">{label} <b>{fnum(val.get(key), 0)}</b></span>'
                        for key, label in VAL_LABELS if val.get(key) is not None)
    fin = (f.get("fin_indicators_recent") or [{}])[0]
    chips_fin = "".join(f'<span class="chip">{l} <b>{fnum(fin.get(l))}</b></span>'
                        for l in ("加权ROE%", "销售毛利率%", "销售净利率%", "资产负债率%", "净利润现金含量")
                        if fin.get(l) is not None)
    rows = "".join(
        f'<tr><td>{esc(r.get("year"))}</td><td>{fnum(r.get("revenue"), 0)}</td>'
        f'<td class="{_pc(r.get("revenue_yoy_pct"))}">{fnum(r.get("revenue_yoy_pct"))}%</td>'
        f'<td>{fnum(r.get("net_profit_parent"), 0)}</td>'
        f'<td class="{_pc(r.get("net_profit_yoy_pct"))}">{fnum(r.get("net_profit_yoy_pct"))}%</td>'
        f'<td>{fnum(r.get("eps"))}</td></tr>'
        for r in f.get("income_annual") or [])
    divs, bal = f.get("dividends") or {}, f.get("balance_latest") or {}
    mini = [("总资产", f'{fnum(bal.get("assets_total"), 0)} 元'),
            ("资产负债率", fnum(bal.get("debt_ratio_pct")) + "%"),
            ("在手现金", f'{fnum(bal.get("cash"), 0)} 元'),
            ("TTM每股分红", fnum(divs.get("ttm_per_share")) + " 元"),
            ("股息率TTM", fnum(divs.get("yield_ttm_pct")) + "%")]
    mini_html = "".join(f'<div class="drow"><span>{k}</span><b>{v}</b></div>' for k, v in mini)
    return f"""
<div class="card">
  <div class="card-title-row"><div class="card-title">基本面</div><div>{chips_val}</div></div>
  <div class="chips">{chips_fin or '<span class="muted">财务指标数据缺失</span>'}</div>
  <div class="tbl-wrap"><table>
    <thead><tr><th>年度</th><th>营收(元)</th><th>营收YoY</th><th>归母净利(元)</th><th>净利YoY</th><th>EPS</th></tr></thead>
    <tbody>{rows}</tbody></table></div>
  <div class="hr-label">资产负债与分红</div>
  <div class="dgrid cols2">{mini_html}</div>
</div>"""


def _pc(v) -> str:
    try:
        return "down" if float(v) < 0 else "up"
    except (TypeError, ValueError):
        return ""


# --------------------------------------------------------------------------
# chart payload (same as before)
# --------------------------------------------------------------------------
def build_chart_payload(digest: dict, snapshot: dict, decision: dict | None) -> dict:
    bars = (snapshot.get("daily") or {}).get("bars") or []
    dates = [b["date"] for b in bars]
    close = [b["close"] for b in bars]
    volumes = [b.get("volume") or 0 for b in bars]

    import pandas as pd

    s = pd.Series(close, dtype=float)

    def ma(n):
        return [None if pd.isna(v) else round(float(v), 2)
                for v in s.rolling(n, min_periods=n).mean()]

    payload = {
        "dates": dates, "close": close,
        "ma20": ma(20), "ma60": ma(60), "ma250": ma(250),
        "vol_dates": dates[-120:], "volumes": volumes[-120:],
        "monthly": [{"month": m["month"], "pct": m["pct"]}
                    for m in (digest.get("technical") or {}).get("monthly_returns") or []],
    }
    if decision:
        plan = (decision.get("plans") or [{}])[0]
        if plan.get("entry"):
            payload["plan"] = {
                "entry_low": plan.get("entry_low") or plan["entry"],
                "entry_high": plan.get("entry_high") or plan["entry"],
                "stop": plan.get("stop"), "tp1": plan.get("tp1"),
                "tp2": plan.get("tp2"), "tp3": plan.get("tp3"),
            }
    return payload


CHARTS_JS = """
function mk(id, cfg) { const el = document.getElementById(id); if (el) new Chart(el, cfg); }
const D = JSON.parse(document.getElementById('chartdata').textContent);
const dl = D.dates.map(d => d.slice(5));
const grid = { color: '#eef1f5' };
mk('priceChart', {
  type: 'line',
  data: { labels: dl, datasets: [
    { label: '收盘', data: D.close, borderColor: '#2563eb', borderWidth: 1.8, pointRadius: 0, tension: .15, order: 1 },
    { label: 'MA20', data: D.ma20, borderColor: '#16a34a', borderWidth: 1, pointRadius: 0, order: 2 },
    { label: 'MA60', data: D.ma60, borderColor: '#f59e0b', borderWidth: 1, pointRadius: 0, order: 3 },
    { label: 'MA250', data: D.ma250, borderColor: '#8b5cf6', borderWidth: 1.3, pointRadius: 0, order: 4 },
    ...(D.plan ? [
      { label: '止损', data: D.dates.map(() => D.plan.stop), borderColor: '#dc2626', borderDash: [6, 4], borderWidth: 1.4, pointRadius: 0, order: 5 },
      { label: 'TP1', data: D.dates.map(() => D.plan.tp1), borderColor: '#059669', borderDash: [6, 4], borderWidth: 1.2, pointRadius: 0, order: 6 },
      { label: 'TP2', data: D.dates.map(() => D.plan.tp2), borderColor: '#059669', borderDash: [6, 4], borderWidth: 1, pointRadius: 0, order: 7 },
      { label: '建仓区', data: D.dates.map(() => D.plan.entry_high), borderColor: 'rgba(37,99,235,.5)', backgroundColor: 'rgba(37,99,235,.10)', borderWidth: 1, pointRadius: 0, fill: '-1', order: 8 },
    ] : [])
  ]},
  options: { maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
    plugins: { legend: { labels: { boxWidth: 10, usePointStyle: true, font: { size: 11 } } } },
    scales: { x: { ticks: { maxTicksLimit: 10, font: { size: 10 } }, grid: { display: false } }, y: { grid } } }
});
mk('volChart', { type: 'bar',
  data: { labels: D.vol_dates.map(d => d.slice(5)), datasets: [{ label: '成交量(股)', data: D.volumes, backgroundColor: '#b6c8e0' }] },
  options: { maintainAspectRatio: false, plugins: { legend: { display: false } },
    scales: { x: { ticks: { maxTicksLimit: 8, font: { size: 10 } }, grid: { display: false } }, y: { grid } } } });
mk('monthChart', { type: 'bar',
  data: { labels: D.monthly.map(m => m.month.slice(2)), datasets: [{ label: '月度收益%', data: D.monthly.map(m => m.pct), backgroundColor: D.monthly.map(m => m.pct >= 0 ? '#16a34a' : '#dc2626') }] },
  options: { maintainAspectRatio: false, plugins: { legend: { display: false } },
    scales: { x: { grid: { display: false } }, y: { grid } } } });
"""


def build_page(digest: dict, snapshot: dict, decision: dict | None, team: list | None,
               profile: dict, sizing: dict, title: str) -> str:
    ident = digest.get("identity") or {}
    quote = digest.get("quote") or {}
    t = digest.get("technical") or {}
    verdict = (decision or {}).get("verdict")
    vcls = VERDICT_STYLE.get(verdict, ("wait", C_NEUT))[0]

    profile_line = (f"总资金 {fnum(profile.get('total_capital'), 0)} 元 · 仓位上限 "
                    f"{fnum(profile.get('max_position_pct'), 0)}% · 单笔风险 {fnum(profile.get('risk_pct'), 1)}%"
                    + ("｜<b>默认档（未确认）</b>" if profile.get("is_default") else ""))
    payload = build_chart_payload(digest, snapshot, decision)

    vol_card = ('<div class="card"><div class="card-title">成交量<small>近 120 日</small></div>'
                '<div class="chartbox" style="height:190px"><canvas id="volChart"></canvas></div></div>')
    month_card = ('<div class="card"><div class="card-title">月度收益<small>近 6 个月</small></div>'
                  '<div class="chartbox" style="height:190px"><canvas id="monthChart"></canvas></div></div>')
    price_card = ('<div class="card"><div class="card-title">价格与均线'
                  '<small>MA20 / MA60 / MA250 ｜ 建仓区 · 止损 · TP 价位线</small></div>'
                  '<div class="chartbox" style="height:340px"><canvas id="priceChart"></canvas></div></div>')

    # single two-column masonry: every card is half-width (incl. hero / kpi / price)
    masonry_cards = (decision_hero(decision, sizing, digest, profile)
                     + team_card(team)
                     + kpi_card_all(digest)
                     + price_card
                     + status_card(digest)
                     + vol_card + month_card
                     + fundamentals_card(digest)
                     + market_card(digest))

    return PAGE.format(
        title=esc(title), banner=AI_RISK_BANNER, chartjs=CHARTJS,
        name=esc(ident.get("name")), thscode=esc(ident.get("thscode")),
        vcls=vcls, verdict=esc(verdict or "--"),
        last=fnum(t.get("last_close")), chg=fnum(quote.get("chg_pct"), 2, "%"),
        as_of=esc(digest.get("as_of")), quality=esc(digest.get("data_quality")),
        provider=esc(digest.get("provider")), adjust=esc(digest.get("adjust")),
        profile_line=profile_line,
        masonry_cards=masonry_cards,
        chart_data=json.dumps(payload, ensure_ascii=False),
        charts_js=CHARTS_JS,
        footer_note=FOOTER_NOTE,
    )


PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
:root {{
  --bg:#f6f8fb; --card:#fff; --line:#e6eaf1; --ink:#1e293b; --sub:#64748b;
  --blue:#2563eb; --green:#16a34a; --red:#dc2626; --amber:#d97706; --purple:#8b5cf6;
  --radius:12px;
}}
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ background:var(--bg); color:var(--ink);
  font:14px/1.65 -apple-system,"Segoe UI","Microsoft YaHei",system-ui,sans-serif; }}
.wrap {{ max-width:1240px; margin:0 auto; padding:16px 20px 40px; }}

/* banner */
.banner {{ background:#fef2f2; border:1px solid #fecaca; color:#991b1b; border-radius:10px;
  padding:10px 14px; font-size:13px; margin-bottom:14px; }}

/* header */
.topbar {{ display:flex; align-items:flex-end; justify-content:space-between; gap:16px;
  flex-wrap:wrap; margin-bottom:14px; }}
.topbar h1 {{ font-size:26px; font-weight:700; letter-spacing:.5px; }}
.topbar .code {{ color:var(--sub); font-size:17px; font-weight:500; margin:0 4px; }}
.verdict {{ display:inline-block; padding:3px 14px; border-radius:999px; color:#fff;
  font-weight:700; font-size:15px; vertical-align:middle; }}
.verdict.buy {{ background:var(--green); }} .verdict.hold {{ background:var(--blue); }}
.verdict.reduce {{ background:var(--amber); }} .verdict.wait {{ background:var(--sub); }}
.meta {{ color:var(--sub); font-size:12.5px; margin-top:3px; }}
.profile-chip {{ background:var(--card); border:1px solid var(--line); border-radius:999px;
  padding:6px 14px; font-size:12.5px; color:var(--sub); }}

/* cards */
.card {{ background:var(--card); border:1px solid var(--line); border-radius:var(--radius);
  padding:16px 18px; box-shadow:0 1px 2px rgba(15,23,42,.04); }}
.card-title {{ font-size:15px; font-weight:700; margin-bottom:12px; }}
.card-title small {{ color:var(--sub); font-weight:400; font-size:12px; margin-left:8px; }}
.card-title-row {{ display:flex; justify-content:space-between; align-items:center;
  flex-wrap:wrap; gap:8px; margin-bottom:10px; }}
.muted {{ color:var(--sub); }} .mt8 {{ margin-top:8px; }}

/* decision hero */
.hero-head {{ display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin-bottom:12px; }}
.hero-head .verdict {{ font-size:20px; padding:5px 20px; }}
.chip {{ display:inline-block; background:#f1f5f9; border:1px solid var(--line);
  border-radius:999px; padding:2px 10px; font-size:12px; color:var(--ink); }}
.chip b {{ margin-left:2px; }}
.hero-grid {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr));
  gap:10px; margin-bottom:12px; }}
.hero-cell {{ background:#f8fafc; border:1px solid var(--line); border-radius:10px;
  padding:8px 10px; }}
.hero-cell span {{ display:block; color:var(--sub); font-size:11.5px; }}
.hero-cell b {{ font-size:16px; font-weight:700; }}
.hero-cell small {{ color:var(--green); font-size:11px; }}
.alert {{ border-radius:10px; padding:8px 12px; font-size:12.5px; margin-bottom:10px; }}
.alert.ok {{ background:#f0fdf4; border:1px solid #bbf7d0; color:#166534; }}
.alert.danger {{ background:#fef2f2; border:1px solid #fecaca; color:#991b1b; line-height:1.8; }}
.alert.danger .howto {{ display:block; margin-top:6px; padding-top:6px;
  border-top:1px dashed #fecaca; color:#7f1d1d; }}
.alert code {{ background:#fee2e2; border-radius:4px; padding:1px 6px;
  font-family:Consolas,monospace; font-size:11.5px; }}
.invalid {{ font-size:12.5px; color:var(--sub); border-top:1px dashed var(--line); padding-top:8px; }}
.invalid b {{ color:var(--ink); }}

/* team list */
.team-list {{ list-style:none; }}
.team-list li {{ display:flex; align-items:flex-start; gap:8px; padding:5.5px 0;
  border-bottom:1px dashed #eef1f5; font-size:12.8px; }}
.team-list li:last-child {{ border-bottom:none; }}
.team-list i {{ width:8px; height:8px; border-radius:50%; margin-top:6px; flex:none; }}
.team-list .role {{ flex:none; width:88px; color:var(--ink); font-weight:600; }}
.team-list .view {{ color:var(--sub); }}

/* kpis — one card, fixed 2 rows x 3 cols of mini boxes */
.kpi-card .kpis {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; }}
.kpi {{ background:#f8fafc; border:1px solid var(--line); border-radius:10px;
  padding:9px 12px; min-height:62px; }}
.kpi-label {{ color:var(--sub); font-size:12px; margin-bottom:2px; }}
.kpi-value {{ font-size:20px; font-weight:700; }}
.kpi-sub {{ color:var(--sub); font-size:11.5px; margin-top:2px; }}
.up {{ color:var(--green); }} .down {{ color:var(--red); }}

/* masonry — single two-column flow; every card is half-width */
.masonry {{ columns:2; column-gap:14px; margin-bottom:14px; }}
.masonry .card {{ break-inside:avoid; margin-bottom:14px; }}
@media (max-width:960px) {{ .masonry {{ columns:1; }} }}

/* zone bars */
.zbar {{ margin:14px 0; }}
.zbar-head {{ display:flex; justify-content:space-between; font-size:12.5px; margin-bottom:6px; }}
.zbar-head b {{ font-weight:700; }} .zbar-head em {{ font-style:normal; font-size:11.5px; }}
.zbar-track {{ position:relative; height:12px; border-radius:6px; overflow:hidden;
  background:#eef1f5; }}
.zbar-track i {{ position:absolute; top:0; bottom:0; opacity:.85; }}
.zmark {{ position:absolute; top:-3px; bottom:-3px; width:3px; background:var(--ink);
  border-radius:2px; box-shadow:0 0 0 2px #fff; }}
.zbar-scale {{ display:flex; justify-content:space-between; color:var(--sub);
  font-size:11px; margin-top:3px; }}

/* data grid & table */
.dgrid {{ display:grid; gap:6px 18px; }}
.dgrid.cols2 {{ grid-template-columns:1fr 1fr; }}
.drow {{ display:flex; justify-content:space-between; gap:10px; font-size:13px;
  border-bottom:1px dashed #eef1f5; padding:5px 0; }}
.drow span {{ color:var(--sub); }}
.tbl-wrap {{ overflow-x:auto; }}
table {{ width:100%; border-collapse:collapse; font-size:12.8px; }}
th {{ text-align:right; color:var(--sub); font-weight:600; padding:6px 8px;
  border-bottom:1px solid var(--line); white-space:nowrap; }}
th:first-child, td:first-child {{ text-align:left; }}
td {{ text-align:right; padding:6px 8px; border-bottom:1px dashed #eef1f5; white-space:nowrap; }}
.hr-label {{ margin:14px 0 8px; color:var(--sub); font-size:12.5px; font-weight:600; }}
.chips {{ display:flex; flex-wrap:wrap; gap:6px; margin-bottom:12px; }}

.chartbox {{ position:relative; }}
footer {{ color:var(--sub); font-size:12px; text-align:center; margin-top:22px;
  border-top:1px solid var(--line); padding-top:14px; }}
</style>
</head>
<body>
<div class="wrap">
  <div class="banner">{banner}</div>

  <header class="topbar">
    <div>
      <h1>{name}<span class="code">{thscode}</span><span class="verdict {vcls}">{verdict}</span></h1>
      <div class="meta">现价 {last}（{chg}） ｜ 数据截至 {as_of} ｜ 质量：{quality} ｜ 源：{provider}（{adjust}复权）</div>
    </div>
    <div class="profile-chip">画像：{profile_line}</div>
  </header>

  <div class="masonry">
    {masonry_cards}
  </div>

  <footer>
    生成于 A-shares-analysis 多智能体流水线 ｜ 仅供研究与教育目的 ｜ 不构成投资建议 ｜ 股市有风险，投资需谨慎
    <br>{footer_note}
  </footer>
</div>
<script id="chartdata" type="application/json">{chart_data}</script>
<script src="{chartjs}"></script>
<script>{charts_js}</script>
</body>
</html>"""


def _sanitize(name: str) -> str:
    keep = [c for c in str(name) if c.isalnum() or c in "()-_"]
    return "".join(keep)[:12] or "标的"


def update_index(entry: dict) -> Path:
    """Append to reports/index.json and regenerate reports/index.html (复盘索引)."""
    import json as jsonlib

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    manifest = []
    if MANIFEST_PATH.is_file():
        try:
            manifest = jsonlib.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        except ValueError:
            manifest = []
    # replace an entry for the same output file, else append
    manifest = [m for m in manifest if m.get("file") != entry["file"]]
    manifest.append(entry)
    manifest.sort(key=lambda m: m.get("generated_at", ""), reverse=True)
    MANIFEST_PATH.write_text(jsonlib.dumps(manifest, ensure_ascii=False, indent=1),
                             encoding="utf-8")

    rows = []
    color = {"BUY": "#16a34a", "HOLD": "#2563eb", "REDUCE": "#d97706", "WAIT": "#64748b"}
    for m in manifest:
        c = color.get(m.get("verdict", ""), "#64748b")
        rows.append(
            f'<tr><td><a href="{m["file"]}">{m.get("name")} <span class="code">{m.get("thscode")}</span></a></td>'
            f'<td><span class="badge" style="background:{c}">{m.get("verdict") or "--"}</span></td>'
            f'<td>{m.get("as_of") or "--"}</td><td class="num">{m.get("shares")}</td>'
            f'<td>{m.get("generated_at")}</td></tr>')
    footer_note_html = (f'开发者微信：{DEV_WECHAT} ｜ 本项目完全免费开源（Apache-2.0）：'
                        f'<a href="{REPO_URL}">{REPO_URL}</a>')
    index_html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>分析报告索引 · A-shares-analysis</title><style>
body{{font:14px/1.7 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif;background:#f6f8fb;color:#1e293b;margin:0;padding:32px}}
.wrap{{max-width:960px;margin:0 auto}}h1{{font-size:22px}}.code{{color:#64748b;font-size:12px}}
table{{width:100%;border-collapse:collapse;background:#fff;border:1px solid #e6eaf1;border-radius:10px;overflow:hidden}}
th,td{{padding:10px 14px;border-bottom:1px solid #eef1f5;text-align:left;font-size:13px}}
th{{color:#64748b;font-weight:600;background:#f8fafc}}a{{color:#2563eb;text-decoration:none}}
a:hover{{text-decoration:underline}}.badge{{color:#fff;border-radius:999px;padding:2px 10px;font-size:12px}}
.num{{text-align:right}}p{{color:#64748b;font-size:12.5px}}
.footer-note{{margin-top:14px;font-size:12.5px}}</style></head><body>
<div class="wrap"><h1>分析报告索引</h1>
<p>共 {len(manifest)} 份报告，按生成时间倒序。点击文件名打开报告（AI 生成内容，不构成投资建议）。</p>
<table><thead><tr><th>标的</th><th>评级</th><th>数据截至</th><th>股数(画像)</th><th>生成时间</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
<p class="footer-note">{footer_note_html}</p></div></body></html>"""
    index_path = REPORTS_DIR / "index.html"
    index_path.write_text(index_html, encoding="utf-8")
    return index_path


def main() -> int:
    force_utf8_stdout()
    parser = argparse.ArgumentParser(description="HTML dashboard report (self-styled)")
    parser.add_argument("--digest", required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--decision", default=None)
    parser.add_argument("--team", default=None,
                        help="team.json: [{role, view(<=40字), tone: bull|bear|neutral}]")
    parser.add_argument("--out", default=None,
                        help="default: SKILL_DIR/reports/<code>_<name>_<ts>.html")
    parser.add_argument("--no-open", action="store_true",
                        help="do not auto-open the report in the browser")
    parser.add_argument("--title", default=None)
    args = parser.parse_args()

    digest = load_json(args.digest)
    snapshot = load_json(args.snapshot)
    decision = load_json(args.decision) if args.decision else None
    team = None
    if args.team:
        raw = load_json(args.team)
        team = raw.get("team") if isinstance(raw, dict) else raw  # accept dict or bare list

    from profile import effective_profile, position_plan

    profile = effective_profile()
    sizing = {}
    if decision and (decision.get("plans") or [{}])[0].get("entry"):
        p = decision["plans"][0]
        if p.get("stop"):
            lot = int(p.get("lot_size") or
                      (1 if (decision.get("asset_type") in ("us-stock", "hk-stock")) else 100))
            sizing = position_plan(float(p["entry"]), float(p["stop"]), lot_size=lot)

    ident = digest.get("identity") or {}
    title = args.title or f"{ident.get('name')}（{ident.get('thscode')}）中长线分析"

    page = build_page(digest, snapshot, decision, team, profile, sizing, title)

    # fixed deliverable location: SKILL_DIR/reports/<code>_<name>_<ts>.html
    ts = now_cst().strftime("%Y%m%d_%H%M%S")
    out = (Path(args.out) if args.out else
           REPORTS_DIR / f"{ident.get('ticker')}_{_sanitize(ident.get('name'))}_{ts}.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")

    # keep the review index (index.html) in sync for every generation
    entry = {
        "file": out.name, "title": title,
        "thscode": ident.get("thscode"), "name": ident.get("name"),
        "verdict": (decision or {}).get("verdict"),
        "as_of": digest.get("as_of"),
        "shares": sizing.get("shares") if sizing else None,
        "generated_at": now_cst().strftime("%Y-%m-%d %H:%M"),
    }
    index_path = update_index(entry)

    # proactively open the report in the browser (disable with --no-open or
    # ASHARES_NO_BROWSER=1, e.g. in tests / headless runs)
    opened = False
    if not args.no_open and not os.environ.get("ASHARES_NO_BROWSER"):
        import webbrowser

        try:
            opened = webbrowser.open(out.resolve().as_uri())
        except Exception:
            opened = False

    # agent-facing reminder: a not-executable sizing MUST be surfaced to the user
    reminder = None
    if sizing and sizing.get("shares", 0) < 100:
        reminder = {
            "issue": "position_not_executable",
            "say_to_user": (
                f"⚠ 按你的画像（总资金 {fnum(profile.get('total_capital'), 0)} 元 / 仓位上限 "
                f"{fnum(profile.get('max_position_pct'), 0)}% / 单笔风险 {fnum(profile.get('risk_pct'), 1)}%）"
                f"该方案买不足一手。一手成本约 {fnum(sizing.get('cost_1lot'), 0)} 元"
                f"（占资金 {fnum(sizing.get('cap_pct_1lot'), 0)}%）；"
                f"可执行门槛：总资金 ≥ {fnum(sizing.get('min_capital_1lot'), 0)} 元"
                f"（同时满足仓位与风险口径）。要调整画像吗？直接告诉我新数值，"
                f"或运行 profile.py --set --capital <数值> --max-position-pct <数值> --risk-pct <数值>"
            ),
            "min_capital_1lot": sizing.get("min_capital_1lot"),
        }
    emit({
        "status": "ok", "html": str(out), "report_path": str(out),
        "index": str(index_path), "browser_opened": opened,
        "title": title, "sizing": sizing,
        "team_members": len(team) if team else 0,
        "profile_is_default": profile.get("is_default"),
        "reminder": reminder,
        "say_to_user": (f"✓ 报告已生成：{out}\n✓ 已在浏览器打开"
                        + ("（如未弹出请手动打开上述路径）" if not opened else "")
                        + f"\n历史报告索引：{index_path}"),
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
