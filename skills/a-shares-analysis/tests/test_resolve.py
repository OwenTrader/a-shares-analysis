"""resolve_ticker — matching, normalization, warnings (pure logic, no network)."""
from __future__ import annotations

from datetime import date

from resolve_ticker import match, normalize_query, warnings_for, resolve

MAOTAI = {"thscode": "600519.SH", "ticker": "600519", "name": "贵州茅台",
          "exchange": "SH", "asset_type": "a-share"}
PINGAN_BANK = {"thscode": "000001.SZ", "ticker": "000001", "name": "平安银行",
               "exchange": "SZ", "asset_type": "a-share"}
PINGAN_GROUP = {"thscode": "601318.SH", "ticker": "601318", "name": "中国平安",
                "exchange": "SH", "asset_type": "a-share"}


def test_normalize_fullwidth_and_prefixes():
    assert normalize_query("６００５１９") == "600519"
    assert normalize_query("sh600519") == "600519.SH"
    assert normalize_query(" 600519.sh ") == "600519.SH"
    assert normalize_query("茅台") == "茅台"


def test_exact_thscode_verified():
    out = match("600519.SH", [MAOTAI, PINGAN_BANK])
    assert out["status"] == "verified"
    assert out["target"]["thscode"] == "600519.SH"


def test_exact_name_verified():
    out = match("贵州茅台", [MAOTAI, PINGAN_BANK])
    assert out["status"] == "verified"


def test_exact_ticker_verified():
    out = match("600519", [MAOTAI, PINGAN_BANK])
    assert out["status"] == "verified"
    assert out["target"]["thscode"] == "600519.SH"


def test_sole_substring_hit_verified_with_note():
    out = match("茅台", [MAOTAI])
    assert out["status"] == "verified"
    assert "唯一子串匹配" in out["note"]


def test_ambiguous_when_two_substring_hits():
    out = match("平安", [PINGAN_BANK, PINGAN_GROUP])
    assert out["status"] == "ambiguous"
    assert len(out["candidates"]) == 2


def test_not_found_gives_suggestions():
    out = match("不存在的股票", [MAOTAI])
    assert out["status"] == "not_found"
    assert out["candidates"] == []  # low-similarity hits dropped from target list


def test_not_found_with_close_fuzzy_suggestion():
    typo = {"thscode": "600519.SH", "ticker": "600519", "name": "贵州茅台",
            "exchange": "SH", "asset_type": "a-share"}
    out = match("贵卅茅台", [typo])   # 错别字：卅 vs 州 -> difflib 分数低于 60
    assert out["status"] == "not_found"
    assert out["candidates"][0]["thscode"] == "600519.SH"
    assert out["candidates"][0]["similarity"] > 0


def test_delisted_and_st_warnings():
    today = date(2026, 9, 17)
    assert any("退市" in w for w in warnings_for(
        {"name": "XX退", "end_date": "2026-06-30"}, today))
    assert any("风险警示" in w for w in warnings_for(
        {"name": "*ST左江", "end_date": None}, today))
    assert any("上市不足一年" in w for w in warnings_for(
        {"name": "新股", "list_date": "2026-03-01"}, today))
    assert warnings_for({"name": "贵州茅台", "list_date": "2001-08-27"}, today) == []


def test_resolve_via_fake_provider_asks_on_ambiguity():
    from conftest import FakeProvider

    provider = FakeProvider()
    out = resolve(provider, "平安", "a-share")   # matches 平安银行 + 中国平安
    assert out["status"] == "ambiguous"
    out2 = resolve(provider, "600519.SH", "a-share")
    assert out2["status"] == "verified"
    assert out2["target"]["name"] == "贵州茅台"


def test_resolve_index_type():
    from conftest import FakeProvider

    provider = FakeProvider()
    out = resolve(provider, "上证指数", "a-share-index")
    assert out["status"] == "verified"
    assert out["target"]["thscode"] == "000001.SH"
