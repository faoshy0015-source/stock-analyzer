"""HanaV 20-point valuation regression tests.

pytest -q tests/test_valuation_model.py
"""
import pandas as pd

from scoring import evaluate, WEIGHTS
from valuation_model import evaluate_valuation, percentile_score, ratio_score, VALUATION_WEIGHTS
from valuation_context import _history_monthly, _sector_peers


def _context():
    return {
        "date":"2026-11-05", "sector_name":"전기전자",
        "krx_per":12, "peer_median_per":18, "peer_per_count":12,
        "krx_pbr":1.5, "krx_roe_proxy":0.12,
        "peer_median_pbr_roe":14.0, "peer_pbr_roe_count":10,
        "historical_per":[8+i*.15 for i in range(60)],
        "historical_pbr":[.8+i*.02 for i in range(60)],
        "history_span_years":5.0,
        "peer_forward_per_median":14, "peer_forward_per_count":4,
        "forward_period_matched":True,
    }


def test_weights_and_full_20_points_coverage():
    assert list(VALUATION_WEIGHTS.values()) == [6,5,5,4]
    assert sum(VALUATION_WEIGHTS.values()) == 20
    assert sum(WEIGHTS.values()) == 100
    r=evaluate_valuation({"forwardPE":11},_context())
    assert len(r["components"]) == 4
    assert r["covered_weight"]==20
    assert r["score"] is not None
    assert 0 <= r["earned"] <= 20
    assert all(x["status"]=="평가" for x in r["components"])


def test_missing_consensus_is_not_made_up():
    r=evaluate_valuation({},_context())
    assert r["covered_weight"]==16
    assert r["components"][-1]["score"] is None
    assert r["components"][-1]["status"]=="미산출"


def test_no_context_produces_zero_val_coverage_not_zero_score():
    r=evaluate_valuation({"trailingPE":9,"priceToBook":1.0,"returnOnEquity":.15},{})
    assert r["covered_weight"]==0
    assert r["score"] is None
    score=evaluate(pd.DataFrame(),pd.DataFrame(),pd.DataFrame(),pd.DataFrame(),pd.DataFrame(),
                   {"__valuation_context":{}})
    assert score["coverage"]==0
    assert score["rows"][1]["score"] is None


def test_missing_history_pbr_only_counts_three_of_five():
    c=_context()
    c["historical_pbr"]=[]
    c.pop("peer_median_pbr_roe")
    c.pop("peer_median_per")
    c.pop("peer_forward_per_median")
    r=evaluate_valuation({},c)
    history=r["components"][1]
    assert history["status"]=="부분 평가"
    assert history["covered_weight"]==3
    assert r["covered_weight"]==3


def test_score_weighted_by_actual_coverage():
    c=_context()
    c["historical_per"]=[]
    c["historical_pbr"]=[]
    c.pop("peer_median_pbr_roe")
    c.pop("peer_forward_per_median")
    r=evaluate(pd.DataFrame(),pd.DataFrame(),pd.DataFrame(),pd.DataFrame(),pd.DataFrame(),
               {"__valuation_context":c})
    assert r["coverage"]==6
    assert r["partial"] is True
    assert r["rows"][1]["weight"]==20
    assert r["rows"][1]["covered_weight"]==6
    assert r["total"]==r["rows"][1]["score"]


def test_roe_removed_from_financial_health_scoring():
    annual=pd.DataFrame([
        {"period":"2024","revenue":90,"operating_profit":14,"net_income":18,
         "assets":200,"liabilities":50,"equity":150},
        {"period":"2025","revenue":100,"operating_profit":15,"net_income":22,
         "assets":240,"liabilities":60,"equity":180},
    ])
    score=evaluate(pd.DataFrame(),annual,pd.DataFrame(),pd.DataFrame(),pd.DataFrame(),{})
    fin=next(x for x in score["rows"] if x["category"]=="재무건전성")
    assert not any("간이 ROE " in n for n in fin["notes"])
    assert any("중복 채점하지" in n for n in fin["notes"])


def test_history_filters_invalid_zero_and_needs_24_observations():
    d=pd.date_range("2021-01-31",periods=61,freq="ME")
    frame=pd.DataFrame({"PER":[10.0]*61,"PBR":[1.1]*61},index=d)
    summary=_history_monthly(frame)
    assert summary["history_span_years"]>=4.9
    assert len(summary["historical_per"])>=60
    assert percentile_score(10,[10]*24)==50
    assert ratio_score(10,10)==50
    assert percentile_score(10,[10]*10) is None


def test_sector_comparables_require_five_peers():
    codes=["005930","001000","001001","001002","001003","001004","002000"]
    data=pd.DataFrame({
        "PER":[12,10,11,14,16,18,50],
        "PBR":[1.2,1,1.1,1.4,1.6,1.8,5],
        "EPS":[120,100,100,100,100,100,100],
        "BPS":[1000]*7,
    },index=codes)
    sectors=pd.DataFrame({"업종명":["전기전자"]*6+["서비스업"]},index=codes)
    c=_sector_peers(data,sectors,"005930")
    assert c["peer_per_count"]==5
    assert c["peer_median_per"]==14
    assert c["peer_pbr_roe_count"]==5
    assert not _sector_peers(data,sectors,"999999")
