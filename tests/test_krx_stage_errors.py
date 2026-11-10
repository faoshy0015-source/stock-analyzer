"""KRX decoding failures are classified without leaking server response bodies."""
import pandas as pd
import pytest

import full_flow_scan
from full_flow_scan import ScanDataError


def test_collection_unexpected_json_failure_is_sanitized(monkeypatch):
    def fail(*args, **kwargs):
        raise ValueError("private token from bad server response")

    monkeypatch.setattr(full_flow_scan, "fetch_market_panels", fail)
    with pytest.raises(ScanDataError, match="KRX 데이터 수집 단계 실패: ValueError") as err:
        full_flow_scan.run_full_scan("2026-11-09", stock_module=object())
    assert "private token" not in str(err.value)


def test_analysis_failure_is_sanitized(monkeypatch):
    dates = pd.bdate_range(end="2026-11-09", periods=22)
    panel = pd.DataFrame({"market": ["KOSPI"], "code": ["005930"]})

    def fake_fetch(*args, **kwargs):
        return panel, [{"investor_coverage": {"개인": 1}}], dates

    def fail(*args, **kwargs):
        raise ValueError("private response")

    monkeypatch.setattr(full_flow_scan, "fetch_market_panels", fake_fetch)
    monkeypatch.setattr(full_flow_scan, "evaluate_market_panel", fail)
    with pytest.raises(ScanDataError, match="종목별 수급 분석 단계 실패: ValueError") as err:
        full_flow_scan.run_full_scan("2026-11-09", stock_module=object())
    assert "private response" not in str(err.value)
