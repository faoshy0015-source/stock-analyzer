"""OpenDART full-FY account extraction and financial-health confidence tests."""
import pandas as pd

from data_sources import _full_fy_metrics
from financial_health_model import (
    evaluate_financial_health, is_financial_company, FINANCIAL_WEIGHTS
)
from scoring import evaluate, explain, diagnostic_summary


def sample_annual():
    return pd.DataFrame([{"period":"2024","equity":100,"liabilities":50,
                          "operating_profit":20,"net_income":10,
                          "revenue":300,"assets":150},
                         {"period":"2025","equity":110,"liabilities":33,
                          "operating_profit":22,"net_income":10,
                          "revenue":330,"assets":143}])


def sample_full():
    return {"year":"2025","fs_scope":"CFS",
            "operating_cash_flow":26,"interest_expense":4,
            "current_assets":90,"current_liabilities":45}


def test_full_dart_extracts_cf_bs_interest_without_financecosts():
    lines=[
        {"sj_div":"CF","account_id":"ifrs-full_CashFlowsFromUsedInOperatingActivities",
         "account_nm":"영업활동 현금흐름","thstrm_amount":"-12,000","account_detail":"-"},
        {"sj_div":"BS","account_id":"ifrs-full_CurrentAssets","account_nm":"유동자산",
         "thstrm_amount":"90,000","account_detail":"-"},
        {"sj_div":"BS","account_id":"ifrs-full_CurrentLiabilities","account_nm":"유동부채",
         "thstrm_amount":"45,000","account_detail":"-"},
        {"sj_div":"IS","account_id":"ifrs-full_FinanceCosts","account_nm":"금융비용",
         "thstrm_amount":"20,000","account_detail":"-"},
        {"sj_div":"IS","account_id":"ifrs-full_InterestExpense","account_nm":"이자비용",
         "thstrm_amount":"4,000","account_detail":"-"},
    ]
    metrics=_full_fy_metrics(lines)
    assert metrics == {
        "operating_cash_flow":-12000,"current_assets":90000,
        "current_liabilities":45000,"interest_expense":4000,
    }


def test_wrong_statement_or_dimensions_not_used():
    rows=[
        {"sj_div":"IS","account_id":"ifrs-full_CurrentAssets","account_nm":"유동자산",
         "thstrm_amount":"9000","account_detail":"-"},
        {"sj_div":"CF","account_id":"ifrs-full_CashFlowsFromUsedInOperatingActivities",
         "account_nm":"영업활동현금흐름","thstrm_amount":"100",
         "account_detail":"특정부문"},
    ]
    assert not _full_fy_metrics(rows)


def test_partial_debt_score_is_not_full_20_weight():
    result=evaluate_financial_health(sample_annual(), {}, {"__name__":"삼성전자"})
    assert result["covered_weight"] == 5
    assert result["weight"] == 20
    assert result["score"] is not None
    assert result["components"][0]["status"]=="평가"
    assert all(p["status"]=="미산출" for p in result["components"][1:])


def test_full_evidence_counts_entire_20_weights():
    result=evaluate_financial_health(sample_annual(), sample_full(), {"__name__":"삼성전자"})
    assert sum(FINANCIAL_WEIGHTS.values()) == 20
    assert result["covered_weight"]==20
    assert all(p["status"]=="평가" for p in result["components"])
    assert 0<=result["earned"]<=20


def test_mismatched_fiscal_year_ignores_full_data():
    bad=sample_full()
    bad["year"]="2024"
    result=evaluate_financial_health(sample_annual(),bad)
    assert result["covered_weight"]==5


def test_bank_and_insurance_not_scored_under_factory_rules():
    for name in ("하나금융지주","신한은행","삼성생명보험"):
        result=evaluate_financial_health(sample_annual(),sample_full(),{"__name__":name})
        assert result["score"] is None
        assert result["covered_weight"]==0


def test_partial_high_financial_score_is_not_highlighted_in_narrative():
    annual=sample_annual()
    result=evaluate(pd.DataFrame(),annual,pd.DataFrame(),
                    pd.DataFrame(),pd.DataFrame(),{"__name__":"삼성전자"})
    f=next(x for x in result["rows"] if x["category"]=="재무건전성")
    assert f["covered_weight"] == 5
    assert "5/20점" in explain(result)
    assert "재무: 평가자료 제한" in diagnostic_summary(result)


def test_negative_cashflow_is_evidence_not_missing():
    detail=sample_full()
    detail["operating_cash_flow"]=-2
    r=evaluate_financial_health(sample_annual(),detail)
    cf=next(x for x in r["components"] if x["name"]=="영업현금흐름 전환율")
    assert cf["score"] == 0
    assert cf["covered_weight"] == 6


def test_full_score_on_15_points_is_stated_as_partial_not_complete_health():
    annual=sample_annual()
    partial=sample_full()
    partial.pop("interest_expense")
    partial["operating_cash_flow"]=40
    profile={"__name__":"삼성전자","__financial_context":partial}
    result=evaluate(pd.DataFrame(),annual,pd.DataFrame(),
                    pd.DataFrame(),pd.DataFrame(),profile)
    health=next(r for r in result["rows"] if r["category"]=="재무건전성")
    assert health["covered_weight"] == 15
    assert health["score"] == 100
    wording=explain(result)
    assert "확인 15/20점 배점" in wording
    assert "미확인된 재무 위험" in wording
    assert "재무건전성(100.0점)" not in wording
    assert "재무: 확인 지표 안정성 양호 (15/20점 배점)" in diagnostic_summary(result)


def test_complete_financial_coverage_has_no_partial_label():
    annual=sample_annual()
    profile={"__name__":"삼성전자","__financial_context":sample_full()}
    result=evaluate(pd.DataFrame(),annual,pd.DataFrame(),
                    pd.DataFrame(),pd.DataFrame(),profile)
    health=next(r for r in result["rows"] if r["category"]=="재무건전성")
    assert health["covered_weight"]==20
    assert "확인 20/20점 배점" not in explain(result)
