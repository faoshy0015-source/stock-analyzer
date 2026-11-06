"""Regression coverage for no-cost, evidence-based news event scoring."""
import pandas as pd

from event_momentum import evaluate_event_momentum, _filing_type, _headline_type
from scoring import evaluate, WEIGHTS


ASOF = "2026-11-06"


def filings(*items):
    return pd.DataFrame([
        {"rcept_no":str(20261106000000+i+1), "rcept_dt":"20261105", "report_nm":title}
        for i,title in enumerate(items)
    ])


def headlines(*rows):
    return pd.DataFrame([
        {"title":title,"source":source,"date":"Thu, 05 Nov 2026 05:00:00 GMT",
         "link":f"https://example.org/{i}"}
        for i,(title,source) in enumerate(rows)
    ])


def test_dart_material_filing_scores_only_six_of_ten():
    r=evaluate_event_momentum(
        filings("단일판매ㆍ공급계약체결"),pd.DataFrame(),"삼성전자",ASOF)
    assert r["covered_weight"]==6
    assert r["score"]==62
    assert r["components"][0]["status"]=="평가"
    assert r["components"][1]["status"]=="미산출"
    assert r["events"][0]["link"].endswith("20261106000001")


def test_negative_regulatory_event_is_not_positive():
    r=evaluate_event_momentum(
        filings("횡령ㆍ배임혐의발생"),None,"삼성전자",ASOF)
    assert r["covered_weight"]==6
    assert r["score"]==12
    assert r["events"][0]["type"]=="중대 위험 공시"


def test_corrected_and_ambiguous_filings_not_scored():
    r=evaluate_event_momentum(
        filings("기재정정 단일판매공급계약체결","분기보고서 (2026.09)"),
        None,"삼성전자",ASOF)
    assert r["score"] is None
    assert r["covered_weight"]==0


def test_news_requires_two_independent_publishers():
    one=headlines(("삼성전자 영업이익 급증","매체A"),
                  ("삼성전자 실적 개선","매체A"))
    r=evaluate_event_momentum(None,one,"삼성전자",ASOF)
    assert r["covered_weight"]==0
    news=headlines(("삼성전자 영업이익 급증","매체A"),
                   ("삼성전자 실적 개선","매체B"))
    r=evaluate_event_momentum(None,news,"삼성전자",ASOF)
    assert r["covered_weight"]==4
    assert r["score"]==67


def test_news_dart_overlap_not_double_counted():
    news=headlines(("삼성전자 대규모 수주","매체A"),
                   ("삼성전자 공급계약 체결","매체B"))
    r=evaluate_event_momentum(
        filings("단일판매ㆍ공급계약체결"),news,"삼성전자",ASOF)
    assert r["covered_weight"]==6


def test_independent_news_plus_dart_scores_full_ten():
    news=headlines(("삼성전자 영업이익 급증","매체A"),
                   ("삼성전자 실적 개선","매체B"))
    r=evaluate_event_momentum(
        filings("단일판매ㆍ공급계약체결"),news,"삼성전자",ASOF)
    assert r["covered_weight"]==10
    assert r["score"] is not None
    assert 0 <= r["earned"] <= 10


def test_news_for_other_companies_or_denied_rumors_excluded():
    news=headlines(("SK하이닉스 실적 개선","매체A"),
                   ("삼성전자 실적 상향 사실무근","매체B"))
    r=evaluate_event_momentum(None,news,"삼성전자",ASOF)
    assert r["covered_weight"]==0
    assert _headline_type("삼성전자 성장","삼성전자") is None


def test_news_future_and_old_filing_excluded():
    d=pd.DataFrame([{"rcept_no":"20261001000001","rcept_dt":"20260601",
                     "report_nm":"단일판매공급계약체결"}])
    news=pd.DataFrame([{"title":"삼성전자 영업이익 증가","date":"Fri, 06 Nov 2027 02:00:00 GMT",
                        "source":"매체A","link":"https://example.com/news"}])
    r=evaluate_event_momentum(d,news,"삼성전자",ASOF)
    assert r["covered_weight"]==0
    assert r["score"] is None


def test_integration_evaluate_preserves_all_weight_and_no_missing_fabrication():
    r=evaluate(pd.DataFrame(),pd.DataFrame(),pd.DataFrame(),
               pd.DataFrame(),pd.DataFrame(),{"__name__":"삼성전자"},
               filings("단일판매ㆍ공급계약체결"))
    newsrow=next(row for row in r["rows"] if row["category"]=="뉴스 모멘텀")
    assert newsrow["covered_weight"] == 6
    assert r["coverage"] == 6
    assert r["total"] == 62
    assert sum(WEIGHTS.values())==100


def test_absent_documents_are_not_treated_as_neutral():
    r=evaluate_event_momentum(None,None,"삼성전자",ASOF)
    assert r["score"] is None
    assert r["covered_weight"]==0
