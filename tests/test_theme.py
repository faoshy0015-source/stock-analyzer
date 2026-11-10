"""Presentation regression: theme stays light, branded as independent research.

Tests inspect static templates, no Streamlit server or external API needed.
"""
from pathlib import Path

from report import render_html

ROOT = Path(__file__).resolve().parents[1]


def test_main_header_is_bright_and_independent():
    source=(ROOT / "app.py").read_text(encoding="utf-8")
    assert "INDEPENDENT STOCK RESEARCH · VERSION 1.3" in source
    assert "CREATED BY K.H.AHN" in source
    assert "HANAV INVESTMENT INTELLIGENCE" not in source
    assert "background:linear-gradient(112deg,#dcefe6" in source
    assert "border-left:5px solid #008878" in source
    assert "#102942" not in source


def test_metric_tab_and_sidebar_use_green_first_palette():
    source=(ROOT / "app.py").read_text(encoding="utf-8")
    assert "[data-testid=\"stMetric\"]" in source
    assert "border-top:3px solid #008878" in source
    assert "background:#dcefe6!important" in source
    assert "background:linear-gradient(175deg,#edf5f2" in source
    assert "#008878" in source
    assert "#e87d31" in source


def test_exported_html_matches_green_first_theme_and_author():
    report=render_html(
        {"name":"테스트","code":"005930"},
        {"rows":[],"total":60.0,"coverage":25,"label":"중립"},
        "단순 참고자료", 1000, "2026-11-06", {"price":"test"},
    )
    assert "CREATED BY K.H.AHN" in report
    assert "HanaV" not in report and "HANAV" not in report
    assert "background:#f4f8f7" in report
    assert "border-left:4px solid var(--orange)" in report
    assert "border-left:5px solid var(--teal)" in report
    assert "<title>테스트 | Stock Analyzer 리서치 제안서</title>" in report


def test_streamlit_theme_uses_green_primary_orange_as_accent():
    config=(ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")
    assert 'primaryColor = "#008878"' in config
    assert 'backgroundColor = "#F4F8F7"' in config
    source=(ROOT / "app.py").read_text(encoding="utf-8")
    assert "--stock-teal:#008878" in source
    assert "--stock-orange:#e87d31" in source
    assert "background:#008878!important" in source
