"""Valuation fallback regression tests. Run: pytest -q tests/test_valuation_sources.py"""
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
from valuation_sources import from_krx_rows, fill_valuation, positive, krx_company_marketcap


def _rows():
    return [
        {"BAS_DD":"20261105", "ISU_CD":"005930", "ISU_NM":"삼성전자",
         "MKTCAP":"1,000,000,000,000", "TDD_CLSPRC":"100,000"},
        {"BAS_DD":"20261105", "ISU_CD":"005935", "ISU_NM":"삼성전자우",
         "MKTCAP":"200,000,000,000", "TDD_CLSPRC":"80,000"},
        {"BAS_DD":"20261105", "ISU_CD":"000660", "ISU_NM":"SK하이닉스",
         "MKTCAP":"2,000,000,000,000", "TDD_CLSPRC":"300,000"},
    ]


def test_krx_issuer_cap_includes_pref_not_unrelated():
    snap=from_krx_rows(_rows(), "005930")
    assert snap["marketcap"] == 1_200_000_000_000
    assert snap["date"] == "2026-11-05"
    assert snap["included_classes"] == ["005930","005935"]
    assert not from_krx_rows(_rows(), "999999")


def test_fallback_multiples_are_clearly_flagged():
    year=datetime.now(ZoneInfo("Asia/Seoul")).year-1
    annual=pd.DataFrame([{"period":str(year),"net_income":100_000_000_000,
                          "equity":500_000_000_000}])
    profile=fill_valuation({},from_krx_rows(_rows(),"005930"), annual)
    assert profile["trailingPE"] == 12
    assert profile["priceToBook"] == 2.4
    assert profile["marketCap"] == 1_200_000_000_000
    assert profile["__valuation_approx"] == ["PER","PBR"]
    assert "간이" in profile["__valuation_approx_note"]
    assert profile.get("__roe_approx") is True


def test_yahoo_valid_values_are_not_overwritten():
    year=datetime.now(ZoneInfo("Asia/Seoul")).year-1
    annual=pd.DataFrame([{"period":str(year),"net_income":100_000_000_000,
                          "equity":500_000_000_000}])
    p=fill_valuation({"trailingPE":19.3,"priceToBook":3.5},
                     from_krx_rows(_rows(),"005930"),annual)
    assert p["trailingPE"] == 19.3
    assert p["priceToBook"] == 3.5
    assert not p.get("__valuation_approx")


def test_missing_cap_or_earnings_does_not_invent_per():
    year=datetime.now(ZoneInfo("Asia/Seoul")).year-1
    annual=pd.DataFrame([{"period":str(year),"net_income":-1,
                          "equity":500_000_000_000}])
    p=fill_valuation({},from_krx_rows(_rows(),"005930"),annual)
    assert "trailingPE" not in p
    assert positive(p.get("priceToBook")) == 2.4
    p2=fill_valuation({}, {}, annual)
    assert p2.get("trailingPE") is None
    assert p2.get("priceToBook") is None


def test_kis_quote_is_prioritized():
    p=fill_valuation({}, {}, pd.DataFrame(), {"per":12.4,"pbr":1.7})
    assert p["trailingPE"]==12.4
    assert p["priceToBook"]==1.7
    assert "KIS" in p["__valuation_source"]
