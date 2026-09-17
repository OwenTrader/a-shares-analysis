"""generate_html.py — dashboard structure, first-screen decision & team views (offline)."""
from __future__ import annotations

from datetime import datetime

from conftest import FakeProvider

from ash_common import CST, dump_json
from fetch_snapshot import build_snapshot
from generate_html import build_page
from make_digest import build_digest
from profile import DEFAULTS

NOW = datetime(2026, 9, 17, 15, 0, tzinfo=CST)
TEAM = [{"role": "技术分析师", "tone": "bear", "view": "中性偏空：支撑1218，阻力1362"}]


def _make(tmp_path):
    provider = FakeProvider()
    snap = build_snapshot(provider, "600519.SH", "a-share", 300, "forward",
                          "000300.SH", set(), NOW)
    snap_path = dump_json(tmp_path / "snapshot.json", snap)
    digest = build_digest(snap_path)
    decision = {
        "thscode": "600519.SH", "name": "贵州茅台", "date": "2026-09-17",
        "verdict": "BUY",
        "plans": [{"entry": 10.2, "entry_low": 10.0, "entry_high": 10.4, "stop": 9.6,
                   "tp1": 11.5, "tp2": 12.0, "tp3": 12.5, "shares": 1000,
                   "rrr_tp1": 1.81, "horizon": "6-18个月", "invalidation": "跌破9.6"}],
    }
    return digest, snap, decision


def _page(tmp_path, decision=None, team=TEAM):
    digest, snap, own_decision = _make(tmp_path)
    from profile import position_plan

    decision = decision or own_decision
    sizing = (position_plan(10.2, 9.6) if (decision.get("plans") or [{}])[0].get("stop")
              else {})
    return build_page(digest, snap, decision, team,
                      {**DEFAULTS, "is_default": True}, sizing, "测试报告")


def test_risk_banner_and_no_css_framework(tmp_path):
    page = _page(tmp_path)
    assert "AI 生成内容风险提示" in page and "不构成任何投资建议" in page
    assert "chart.umd.min.js" in page          # charts still via Chart.js CDN
    assert "tabler" not in page.lower()        # no framework css dependency


def test_footer_carries_developer_and_repo_info(tmp_path):
    page = _page(tmp_path)
    assert "开发者微信：tradinginfinity" in page
    assert "完全免费开源" in page and "Apache-2.0" in page
    assert "https://github.com/OwenTrader/a-shares-analysis" in page


def test_decision_is_in_first_screen_before_charts(tmp_path):
    page = _page(tmp_path)
    assert page.index("最终决策") < page.index("priceChart") < page.index("成交量")
    assert '<span class="verdict buy">BUY</span>' in page
    assert "hero-grid" in page and "失效条件" in page


def test_team_views_rendered_with_tone_colors(tmp_path):
    page = _page(tmp_path)
    assert "团队观点" in page
    assert "技术分析师" in page and "中性偏空：支撑1218，阻力1362" in page
    assert 'style="background:#dc2626"' in page   # bear tone dot
    for m in TEAM:
        assert len(m["view"]) <= 40


def test_decision_hero_leads_the_masonry(tmp_path):
    page = _page(tmp_path)
    m0 = page.index('class="masonry"')
    # hero is the first card; all sections live inside the single two-column masonry
    order = ["最终决策", "团队观点", "关键指标", "priceChart", "状态读数",
             "成交量", "月度收益", "基本面", "市场环境"]
    positions = [page.index(marker) for marker in order]
    assert all(p > m0 for p in positions)
    assert positions == sorted(positions)          # DOM order preserved
    assert '<span class="verdict buy">BUY</span>' in page
    assert "失效条件" in page


def test_kpis_are_one_card_with_2x3_grid(tmp_path):
    page = _page(tmp_path)
    assert page.count('class="card kpi-card"') == 1     # single wrapper card
    assert "关键指标" in page
    assert page.count('<div class="kpi">') == 6         # six internal cells
    # fixed 3-column grid (2 rows x 3 cols), not auto-fit full width
    kpi_css = page.split(".kpi-card .kpis")[1][:220]
    assert "repeat(3,minmax(0,1fr))" in kpi_css and "auto-fit" not in kpi_css


def test_hero_cells_use_three_column_grid(tmp_path):
    page = _page(tmp_path)
    css = page.split(".hero-grid")[1][:200]
    assert "repeat(3,minmax(0,1fr))" in css


def test_whole_page_is_two_column_masonry(tmp_path):
    page = _page(tmp_path)
    assert page.count('class="masonry"') == 1        # single masonry zone
    assert "columns:2" in page and "break-inside:avoid" in page
    # old grid spans are gone — every card is half width
    for gone in ("span-8", "span-4", "span-7", "span-5", "grid-template-columns:repeat(12"):
        assert gone not in page


def test_zone_bars_replace_doughnut_gauges(tmp_path):
    page = _page(tmp_path)
    assert "zbar" in page and "zmark" in page
    assert "250日区间位置" in page and "RSI-14" in page and "ADX-14 趋势强度" in page
    assert "gauge_" not in page                    # old doughnut ids gone


def test_sizing_alerts(tmp_path):
    page = _page(tmp_path)
    assert "按当前画像可执行" in page            # cheap fixture price -> executable
    digest, snap, decision = _make(tmp_path)
    decision["plans"][0].update({"entry": 1215.7, "stop": 1146.5})
    from profile import position_plan

    sizing = position_plan(1215.7, 1146.5, {**DEFAULTS})  # explicit: never read stored profile
    page2 = build_page(digest, snap, decision, TEAM, {**DEFAULTS, "is_default": True},
                       sizing, "测试报告")
    assert "不可执行" in page2 and "不足一手" in page2
    # the alert must be actionable: quantified ways out + how to change the profile
    assert "三条出路" in page2
    assert "如何更新画像" in page2 and "profile.py --set" in page2
    assert "不可行" in page2                    # cap route honestly marked infeasible (>100%)
    assert "1,215,700" in page2                 # min capital under both constraints


def test_main_emits_reminder_when_not_executable(tmp_path, monkeypatch, capsys):
    import json as jsonlib

    import generate_html as gh
    monkeypatch.setattr(gh, "REPORTS_DIR", tmp_path / "reports")          # never touch real index
    monkeypatch.setattr(gh, "MANIFEST_PATH", tmp_path / "reports" / "index.json")
    import profile as profile_mod
    monkeypatch.setattr(profile_mod, "PROFILE_PATH", tmp_path / "absent.json")  # -> defaults
    digest, snap, decision = _make(tmp_path)
    decision["plans"][0].update({"entry": 1215.7, "stop": 1146.5})
    d_path = dump_json(tmp_path / "d.json", digest)
    s_path = dump_json(tmp_path / "s.json", snap)
    dec_path = dump_json(tmp_path / "dec.json", decision)
    dump_json(tmp_path / "team.json", TEAM)
    monkeypatch.setattr("sys.argv", [
        "generate_html.py", "--digest", str(d_path), "--snapshot", str(s_path),
        "--decision", str(dec_path), "--team", str(tmp_path / "team.json"),
        "--out", str(tmp_path / "r.html"), "--no-open"])
    import generate_html

    rc = generate_html.main()
    out = jsonlib.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert rc == 0 and out["status"] == "ok"
    assert out["reminder"]["issue"] == "position_not_executable"
    assert "要调整画像吗" in out["reminder"]["say_to_user"]
    # default profile (10万/10%/2%): cap-bound threshold dominates
    assert out["reminder"]["min_capital_1lot"] == 1215700


def test_reports_land_in_fixed_dir_with_index(tmp_path, monkeypatch, capsys):
    import json as jsonlib

    import generate_html as gh
    reports = tmp_path / "reports"
    monkeypatch.setattr(gh, "REPORTS_DIR", reports)
    monkeypatch.setattr(gh, "MANIFEST_PATH", reports / "index.json")
    import profile as profile_mod
    monkeypatch.setattr(profile_mod, "PROFILE_PATH", tmp_path / "absent.json")

    digest, snap, decision = _make(tmp_path)
    d_path = dump_json(tmp_path / "d.json", digest)
    s_path = dump_json(tmp_path / "s.json", snap)
    dec_path = dump_json(tmp_path / "dec.json", decision)

    for _ in range(2):  # two generations -> two files + two index rows
        monkeypatch.setattr("sys.argv", [
            "generate_html.py", "--digest", str(d_path), "--snapshot", str(s_path),
            "--decision", str(dec_path), "--out", str(reports / "reuse.html"),
            "--no-open"])
        assert gh.main() == 0
    out = jsonlib.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["status"] == "ok"
    assert out["report_path"].startswith(str(reports))
    assert out["browser_opened"] is False            # --no-open honoured
    assert "历史报告索引" in out["say_to_user"]

    manifest = jsonlib.loads((reports / "index.json").read_text(encoding="utf-8"))
    assert len(manifest) == 1 and manifest[0]["file"] == "reuse.html"  # same file -> replaced
    index_html = (reports / "index.html").read_text(encoding="utf-8")
    assert "reuse.html" in index_html and "600519.SH" in index_html
    # index footer carries the same developer / open-source attribution
    assert "tradinginfinity" in index_html and "OwenTrader/a-shares-analysis" in index_html


def test_default_out_lives_in_reports_dir(tmp_path, monkeypatch, capsys):
    import json as jsonlib

    import generate_html as gh
    reports = tmp_path / "reports"
    monkeypatch.setattr(gh, "REPORTS_DIR", reports)
    monkeypatch.setattr(gh, "MANIFEST_PATH", reports / "index.json")
    import profile as profile_mod
    monkeypatch.setattr(profile_mod, "PROFILE_PATH", tmp_path / "absent.json")

    digest, snap, decision = _make(tmp_path)
    d_path = dump_json(tmp_path / "d.json", digest)
    s_path = dump_json(tmp_path / "s.json", snap)
    dec_path = dump_json(tmp_path / "dec.json", decision)
    monkeypatch.setattr("sys.argv", [
        "generate_html.py", "--digest", str(d_path), "--snapshot", str(s_path),
        "--decision", str(dec_path), "--no-open"])
    assert gh.main() == 0
    out = jsonlib.loads(capsys.readouterr().out.strip().splitlines()[-1])
    # no --out: file lands under the fixed reports dir with code_name_ts naming
    rel = out["report_path"].replace(str(reports) + "\\", "").replace(str(reports) + "/", "")
    assert rel.startswith("600519_") and "_20" in rel and rel.endswith(".html")
    assert (reports / rel).is_file()


def test_wait_verdict_minimal_hero(tmp_path):
    decision = {"verdict": "WAIT", "plans": [{"invalidation": "等待放量突破年线"}]}
    page = _page(tmp_path, decision=decision)
    assert "WAIT 观望" in page and "等待放量突破年线" in page


def test_chart_payload_has_ma_and_plan(tmp_path):
    digest, snap, decision = _make(tmp_path)
    from generate_html import build_chart_payload

    payload = build_chart_payload(digest, snap, decision)
    assert len(payload["dates"]) == 300
    assert sum(v is not None for v in payload["ma250"]) > 0
    assert payload["plan"]["stop"] == 9.6
    assert payload["monthly"]
