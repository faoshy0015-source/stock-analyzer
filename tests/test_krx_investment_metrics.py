"""KRX per-share and dividend values from existing official fundamental feed."""
from pathlib import Path

import pandas as pd

from valuation_context import _issuer_indicators, _raw_finite, _per_and_pbr


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


def test_app_displays_source_date_and_does_not_scrape_npay_financial_sidebar():
    source=(Path(__file__).resolve().parents[1]/"app.py").read_text(encoding="utf-8")
    assert "valuation_context.get('krx_eps')" in source
    assert "valuation_context.get('krx_bps')" in source
    assert "valuation_context.get('krx_dps')" in source
    assert "valuation_context.get('krx_dividend_yield')" in source
    assert "조회 기준일 {krx_date}" in source
    assert "('추정 EPS (Yahoo 추정 · 별도 기준)',profile.get('forwardEps')" in source
