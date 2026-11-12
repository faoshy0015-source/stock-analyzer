"""Stock Analyzer integration checks for features migrated from HanaV Trading.

Unit tests are network-independent: extract and execute the pure ranking
functions from the UI module, avoiding Streamlit app boot or remote requests.
"""
from pathlib import Path
import ast

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "trading_sidebar.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def load_pure_function(name):
    function = next(
        node for node in TREE.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )
    clean = ast.FunctionDef(
        name=function.name,
        args=function.args,
        body=function.body,
        decorator_list=[],
        returns=function.returns,
        type_comment=function.type_comment,
    )
    namespace = {"pd": pd}
    exec(compile(ast.fix_missing_locations(
        ast.Module(body=[clean], type_ignores=[])
    ), str(ROOT / "trading_sidebar.py"), "exec"), namespace)
    return namespace[name]


def test_earnings_improvement_score_moves_with_operating_profit_and_eps():
    fn = load_pure_function("earnings_momentum")
    financial = pd.DataFrame([
        {"연도": 2025, "영업이익": 100, "EPS": 100, "PER": 12, "ROE": 8},
        {"연도": 2026, "영업이익": 150, "EPS": 150, "PER": 10, "ROE": 9},
        {"연도": 2027, "영업이익": 200, "EPS": 200, "PER": 9, "ROE": 11},
        {"연도": 2028, "영업이익": 250, "EPS": 250, "PER": 8, "ROE": 13},
    ])
    label, score, reason = fn(financial)
    assert label == "📈 실적개선"
    assert score == 6
    assert "영업이익 증가" in reason and "EPS 증가" in reason


def test_no_earnings_improvement_when_profit_falls():
    fn = load_pure_function("earnings_momentum")
    financial = pd.DataFrame([
        {"연도": 2025, "영업이익": 500, "EPS": 200, "PER": 6, "ROE": 12},
        {"연도": 2026, "영업이익": 400, "EPS": 180, "PER": 7, "ROE": 10},
        {"연도": 2027, "영업이익": 300, "EPS": 150, "PER": 8, "ROE": 8},
        {"연도": 2028, "영업이익": 200, "EPS": 110, "PER": 9, "ROE": 6},
    ])
    label, score, _ = fn(financial)
    assert label == "📉 실적둔화"
    assert score < 0


def test_dashboard_sidebar_links_to_both_panels_only_after_auth():
    nav = (ROOT / "app_navigation.py").read_text(encoding="utf-8")
    assert "from trading_sidebar import render_trading_sidebar" in nav
    assert "render_trading_sidebar()" in nav
    assert "pages/2_시장_대시보드.py" in nav
    assert "st.page_link(\"app.py\"" in nav
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    assert app.index("require_login(st)") < app.index("render_navigation(st)")


def test_trading_sidebar_keeps_top40_20_5_and_no_order_endpoint():
    assert ".head(40)" in SOURCE
    assert "reverse=True)[:20]" in SOURCE
    assert "return results[:5], \"\"" in SOURCE
    assert "from hanavtrading" not in SOURCE  # independent of the old app runtime
    assert "FHKST01010100" in SOURCE
    assert "/quotations/inquire-price" in SOURCE
    assert "/trading/order" not in SOURCE
    assert '"KIS_APP_KEY"' in SOURCE and '"KIS_APP_SECRET"' in SOURCE
    assert "public_market_quote.clear()" in SOURCE
    assert "auto_earnings_top5.clear()" in SOURCE
