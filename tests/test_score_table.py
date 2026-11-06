"""Score table UX: no clipped confidence, narrow score columns, safe HTML."""
from pathlib import Path
from html import unescape

from score_table import render_score_table

ROOT=Path(__file__).resolve().parents[1]


def test_score_table_compacts_numerics_and_wraps_confidence():
    rows=[
        {"category":"재무건전성","weight":20,"covered_weight":15,
         "score":90.3,"confidence":"낮음 · 확인된 3개 지표만 부분 평가"},
        {"category":"실적·성장성","weight":25,"covered_weight":25,
         "score":100.0,"confidence":"보통"},
        {"category":"뉴스 모멘텀","weight":10,"covered_weight":0,
         "score":None,"confidence":"미산출"}
    ]
    html=render_score_table(rows)
    assert 'style="width:9%"' in html
    assert 'style="width:10%"' in html
    assert 'style="width:14%"' in html
    assert 'style="width:43%"' in html
    assert '90.3*</td>' in html
    assert '100.0</td>' in html
    assert '미산출</td>' in html
    assert "낮음 · 확인된 3개 지표만 부분 평가" in html
    assert 'class="score-trust"' in html


def test_score_table_escapes_external_text():
    table=render_score_table([
        {"category":"<b onclick='evil()'>a</b>","weight":5,
         "covered_weight":2,"score":40,
         "confidence":"<img src=x onerror=alert(1)>"}
    ])
    assert "<img" not in table and "<b onclick" not in table
    assert "&lt;img" in table and "&lt;b" in table


def test_score_table_long_confidence_is_not_truncated():
    long_text="보통 · 시장 데이터 제공처와 회계 기준의 한계 확인 필요 " * 6
    html=render_score_table([{"category":"밸류에이션","weight":20,
                               "covered_weight":16,"score":45.2,"confidence":long_text}])
    assert long_text in unescape(html)
    assert "…" not in html


def test_score_panel_collapses_calculation_rules_by_default():
    app=(ROOT/"app.py").read_text(encoding="utf-8")
    assert "with st.expander('점수 계산 원칙 · 산출 근거',expanded=False)" in app
    assert "st.markdown(render_score_table(scores['rows']),unsafe_allow_html=True)" in app
    assert "left,right=st.columns([1,1.28]" in app
    assert "overflow-wrap:anywhere" in app
