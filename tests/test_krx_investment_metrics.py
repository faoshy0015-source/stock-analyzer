"""KRX per-share and dividend values from existing official fundamental feed."""
from pathlib import Path

import pandas as pd

from valuation_context import _issuer_indicators, _raw_finite, _per_and_pbr
from valuation_sources import display_valuation_ratios


def test_extract_krx_fields_from_matching_issuer_only():
    frame=pd.DataFrame(
        {"PER":[14.74,28.0],"PBR":[0.96,4.5],
         "EPS":[12885,1000],"BPS":[197188,20000],
         "DIV":[1.39,0.7],"DPS":[2630,300]},
        index=["035420","005930"],
    )
    result=_issuer_indicators(frame,"035420")
    assert result=={
        "krx_eps":12885.0,
        "krx_bps":197188.0,
        "krx_dps":2630.0,
        "krx_dividend_yield":1.39,
    }
    assert _per_and_pbr(frame,"035420")==(14.74,0.96)
    assert _issuer_indicators(frame,"000660")=={}


def test_loss_making_eps_is_not_falsely_silenced_and_zero_dividend_is_real():
    df=pd.DataFrame({"EPS":[-800],"BPS":[12000],"DPS":[0],"DIV":[0]},
                    index=["123456"])
    indicators=_issuer_indicators(df,"123456")
    assert indicators["krx_eps"]==-800
    assert indicators["krx_dps"]==0
    assert indicators["krx_dividend_yield"]==0


def test_bad_missing_value_does_not_become_zero_or_estimate():
    df=pd.DataFrame({"EPS":["--"],"BPS":[-200],"DIV":["nan"],"DPS":[""]},
                    index=["035420"])
    assert _issuer_indicators(df,"035420")=={}
    assert _raw_finite(float("nan")) is None
    assert _raw_finite("n/a") is None


def test_app_keeps_krx_data_separate_from_npay_consensus():
    source=(Path(__file__).resolve().parents[1]/"app.py").read_text(encoding="utf-8")
    assert "valuation_context.get('krx_eps')" in source
    assert "valuation_context.get('krx_bps')" in source
    assert "valuation_context.get('krx_dps')" in source
    assert "valuation_context.get('krx_dividend_yield')" in source
    assert "KRX/pykrx · 기준일 " in source
    assert "npay.get('annual_forecasts')" in source
    assert "('추정 EPS (Yahoo 추정 · 12M)',profile.get('forwardEps')" in source
    assert "st.expander('📚 한국거래소(KRX) 투자지표" in source



def test_dated_krx_fills_lower_panel_when_yahoo_profile_has_missing_pe_pbr():
    profile={"trailingPE":None,"priceToBook":None,"forwardPE":13.51}
    context={"date":"2026-11-05","krx_per":14.21,"krx_pbr":1.0}
    values=display_valuation_ratios(profile,context)
    assert values["PER"]["value"]==14.21
    assert values["PBR"]["value"]==1.0
    assert values["PER"]["kind"]=="krx"
    assert values["PER"]["source"]=="KRX 투자지표 · 2026-11-05"
    assert profile["trailingPE"] is None
    assert profile["forwardPE"]==13.51


def test_display_krx_precedence_over_mixed_yahoo_basis():
    values=display_valuation_ratios(
        {"trailingPE":23.1,"priceToBook":3.2},
        {"date":"2026-11-05","krx_per":14.21,"krx_pbr":1.0}
    )
    assert values["PER"]["value"]==14.21
    assert values["PBR"]["value"]==1.0
    assert all(v["kind"]=="krx" for v in values.values())


def test_undated_krx_is_not_passed_as_verified():
    values=display_valuation_ratios(
        {"trailingPE":11,"priceToBook":None},
        {"krx_per":14.21,"krx_pbr":1.0},
    )
    assert values["PER"]["value"]==11
    assert values["PER"]["kind"]=="external"
    assert values["PBR"]["value"] is None
    assert values["PBR"]["kind"]=="missing"


def test_dart_krx_approximation_stays_explicitly_approximate():
    values=display_valuation_ratios(
        {"trailingPE":12.1,"priceToBook":0.8,"__valuation_approx":["PER","PBR"]},{}
    )
    assert "간이" in values["PER"]["source"]
    assert "간이" in values["PBR"]["source"]


def test_app_lower_panel_uses_same_krx_values_as_top_panel():
    app=(Path(__file__).resolve().parents[1]/"app.py").read_text(encoding="utf-8")
    assert "display_ratios=display_valuation_ratios(profile,valuation_context)" in app
    assert "display_ratios['PER']['value']" in app
    assert "display_ratios['PBR']['value']" in app
    assert "PER 출처:" in app and "PBR 출처:" in app
