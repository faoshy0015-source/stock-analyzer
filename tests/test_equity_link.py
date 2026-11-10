"""EQUITY Gold is a browser-only navigation, no hidden login harvesting."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_equity_gold_report_entry_is_safe_external_navigation():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "#### EQUITY 골드회원 리서치" in source
    assert "https://www.equity.co.kr/reports/company" in source
    assert "계정정보를 Stock Analyzer에 입력하지 않으며" in source
    assert "자동 수집·저장·재배포하지 않습니다" in source
    assert "st.link_button('🔎 EQUITY 골드회원 종목 리포트 검색'" in source


def test_equity_credentials_not_added_as_app_secret():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "EQUITY_PASSWORD" not in source
    assert "EQUITY_ID" not in source
