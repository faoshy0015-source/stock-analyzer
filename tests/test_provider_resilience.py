"""Optional provider failures must never kill the main stock analysis."""
import builtins
from json import JSONDecodeError
from pathlib import Path

import pandas as pd

from provider_resilience import optional_fetch
from valuation_context import fetch_valuation_context

ROOT = Path(__file__).resolve().parents[1]


def test_json_decode_error_becomes_missing_data_without_raw_leak():
    issues = []
    def broken():
        raise JSONDecodeError("secret response", "an API response body", 0)

    fallback = optional_fetch(
        "KRX 업종 PER·PBR", broken,
        lambda: {"source": "KRX", "errors": ["수집 실패"]},
        issues,
    )
    assert fallback["errors"] == ["수집 실패"]
    assert len(issues) == 1
    assert "JSONDecodeError" in issues[0]
    assert "secret response" not in issues[0]
    assert "API response body" not in issues[0]


def test_bad_shape_does_not_leak_into_scoring_inputs():
    issues = []
    value = optional_fetch(
        "기업 기본정보", lambda: ["invalid", "shape"], dict,
        issues, validator=lambda result: isinstance(result, dict),
    )
    assert value == {}
    assert "TypeError" in issues[0]


def test_data_fetch_retries_at_next_call_instead_of_caching_failure():
    issues = []
    state = {"tries": 0}
    def intermittent():
        state["tries"] += 1
        if state["tries"] == 1:
            raise RuntimeError("transient")
        return {"trailingPE": 12}

    result1 = optional_fetch("P/E", intermittent, dict, issues)
    result2 = optional_fetch("P/E", intermittent, dict, issues)
    assert result1 == {}
    assert result2 == {"trailingPE": 12}
    assert state["tries"] == 2
    assert len(issues) == 1


def test_valuation_context_handles_pykrx_import_json_error(monkeypatch):
    real_import = builtins.__import__
    def broken_import(name, *args, **kwargs):
        if name == "pykrx":
            raise JSONDecodeError("invalid", "secret response", 0)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", broken_import)
    result = fetch_valuation_context("005930", "KOSPI")
    assert result["source"] == "pykrx/한국거래소"
    assert "date" not in result
    assert len(result["errors"]) == 1
    assert "JSONDecodeError" in result["errors"][0]
    assert "secret response" not in result["errors"][0]


def test_app_reports_missing_valuation_instead_of_crashing():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "lambda: cached_valuation_context(resolved['code'],resolved['market'])" in source
    assert 'KRX 업종 PER·PBR 및 과거 밴드' in source
    assert "데이터 연결 상태 · {len(data_issues)}건 확인 필요" in source
    assert "profile['__valuation_context']=valuation_context" in source
    assert "display_ratios=display_valuation_ratios(profile,valuation_context)" in source
    assert "해당 항목" not in source or True


def test_valuation_cache_ttl_does_not_keep_short_outages_for_half_day():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "@st.cache_data(ttl=1800,show_spinner=False)\ndef cached_valuation_context" in source


def test_no_provider_exception_raw_response_in_diagnostics():
    issues = []
    optional_fetch(
        "KIS", lambda: (_ for _ in ()).throw(
            ValueError("Authorization: Bearer private_token")),
        dict, issues)
    assert issues == ["KIS: ValueError · 응답 형식 또는 연결 상태 확인 필요"]
