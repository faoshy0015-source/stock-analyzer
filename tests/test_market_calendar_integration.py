"""Market calendar integration regression tests (no external network)."""
import ast
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CAL = (ROOT / "market_calendar.py").read_text(encoding="utf-8")
PAGE = (ROOT / "pages/2_시장_대시보드.py").read_text(encoding="utf-8")
TREE = ast.parse(CAL)


def isolate(*function_names):
    functions = [
        node for node in TREE.body
        if isinstance(node, ast.FunctionDef) and node.name in function_names
    ]
    assert len(functions) == len(function_names)
    for f in functions:
        f.decorator_list = []
    module = ast.fix_missing_locations(ast.Module(body=functions, type_ignores=[]))
    import re
    scope = {"datetime": datetime, "re": re}
    exec(compile(module, str(ROOT / "market_calendar.py"), "exec"), scope)
    return scope


def test_date_label_and_macro_importance():
    helpers = isolate("_hanav_day_label", "_hanav_macro_importance")
    assert helpers["_hanav_day_label"]("2026-11-12") == "11/12(목)"
    assert helpers["_hanav_macro_importance"]("3") == ("★★★", 3)
    assert helpers["_hanav_macro_importance"]("medium") == ("★★", 2)
    assert helpers["_hanav_macro_importance"]("unknown") == ("", 0)


def test_us_macro_filter_does_not_mislabel_other_countries():
    functions = isolate("_hanav_macro_importance", "_hanav_major_macro")
    is_major = functions["_hanav_major_macro"]
    assert is_major({"country":"United States", "eventName":"CPI", "importance":"high"})
    assert not is_major({"country":"Canada", "eventName":"CPI", "importance":"high"})
    assert not is_major({"country":"United States", "eventName":"", "importance":"high"})


def test_calendar_is_on_dashboard_bottom_not_every_sidebar_page():
    assert PAGE.index('with st.expander("📋 전체 모니터링 종목 보기"') < PAGE.index(
        "render_market_calendar("
    )
    assert "from market_calendar import render_market_calendar" in PAGE
    assert "render_market_calendar" not in (
        ROOT / "app_navigation.py"
    ).read_text(encoding="utf-8")


def test_user_controls_and_source_caveats_preserved():
    assert "st.date_input(" in CAL and '"표시 기간", [3, 5, 7, 14]' in CAL
    assert "hanav_calendar_window.clear()" in CAL
    assert "hanav_korea_calendar_source.clear()" in CAL
    assert "hanav_korea_news_earnings_window.clear()" in CAL
    assert "Nasdaq Calendar" in CAL
    assert "Bullstory" in CAL
    assert "공식 확정 일정이 아닐 수 있습니다" in CAL
    assert 'st.markdown("**🏢 주요 기업 실적 발표**")' in CAL
    assert 'st.markdown("**🌐 주요 매크로 발표**")' in CAL
