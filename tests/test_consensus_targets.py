"""Recent broker-unique analyst target sample and upside safeguards."""
from unittest.mock import Mock,patch

import pandas as pd

from consensus_targets import summarize_targets, target_krw, naver_published_consensus
from report import render_html


TODAY="2026-11-06"
QUOTE_DATE="2026-11-05"


def _reports():
    return pd.DataFrame([
        {"broker":"가상증권","date":"2026-11-05","target_price":"130,000원",
         "title":"삼성전자 연구 1","url":"https://stock.naver.com/research/111"},
        {"broker":"가상투자증권","date":"2026-10-17","target_price":"100,000원",
         "title":"삼성전자 과거 연구","url":"https://stock.naver.com/research/101"},
        {"broker":"하나증권","date":"2026-11-04","target_price":"150,000원",
         "title":"삼성전자 연구 2","url":"https://stock.naver.com/research/222"},
        {"broker":"다른증권","date":"2026-07-01","target_price":"300,000원",
         "title":"오래된 목표가","url":"https://stock.naver.com/research/333"},
        {"broker":"목표미제시증권","date":"2026-11-03","target_price":"",
         "title":"목표가 미제시","url":"https://stock.naver.com/research/444"},
    ])


def test_recent_latest_per_broker_average_and_upside():
    r=summarize_targets(_reports(),100000,QUOTE_DATE,TODAY)
    assert r["average"]==140000
    assert r["count"]==2
    assert r["upside_pct"]==40.0
    assert set(x["broker"] for x in r["rows"])=={"가상증권","하나증권"}
    assert r["min"]==130000 and r["max"]==150000


def test_one_broker_is_insufficient_to_call_average():
    data=_reports().iloc[[0,1]].copy()
    r=summarize_targets(data,100000,QUOTE_DATE,TODAY)
    assert r["count"]==1
    assert r["average"] is None
    assert r["upside_pct"] is None


def test_newer_report_without_target_invalidates_older_same_broker():
    rows=_reports().iloc[[0,2]].copy()
    newer=pd.DataFrame([{"broker":"가상증권","date":"2026-11-06",
        "target_price":"","title":"최신 보고서","url":"https://stock.naver.com/research/999"}])
    r=summarize_targets(pd.concat([rows,newer],ignore_index=True),100000,QUOTE_DATE,TODAY)
    assert r["average"] is None
    assert r["count"]==1


def test_future_reports_and_stale_quotes_excluded_from_upside():
    d=_reports().copy()
    d.loc[len(d)]={"broker":"다음증권","date":"2026-11-07",
                    "target_price":"900,000원","title":"미래","url":"https://example.com/r"}
    r=summarize_targets(d,100000,"2026-10-01",TODAY)
    assert r["average"]==140000
    assert r["upside_pct"] is None
    assert r["price"] is None


def test_missing_quote_date_is_not_assumed_current():
    r=summarize_targets(_reports(),100000,None,TODAY)
    assert r["average"]==140000
    assert r["upside_pct"] is None


def test_downside_is_negative_with_positive_current_price():
    r=summarize_targets(_reports(),200000,QUOTE_DATE,TODAY)
    assert r["upside_pct"]==-30.0


def test_monetary_string_parsing_rejects_ambiguous_values():
    assert target_krw("240,000원")==240000
    assert target_krw("24만원")==240000
    assert target_krw("24만5천원")==245000
    for item in ("매수", "목표 미제시", "200,000~230,000원", "0", None,""):
        assert target_krw(item) is None


@patch("consensus_targets.requests.get")
def test_naver_published_aggregate_is_separate_and_dated(mock_get):
    resp=Mock()
    resp.json.return_value={"consensusInfo":
        {"priceTargetMean":245000,"createDate":"2026-11-05"}}
    mock_get.return_value=resp
    result,err=naver_published_consensus("005930",TODAY)
    assert err==""
    assert result["target"]==245000
    assert "별도" in result["source"]


@patch("consensus_targets.requests.get")
def test_old_published_mean_rejected(mock_get):
    resp=Mock()
    resp.json.return_value={"consensusInfo":
        {"priceTargetMean":245000,"createDate":"2025-03-05"}}
    mock_get.return_value=resp
    result,err=naver_published_consensus("005930",TODAY)
    assert not result and "오래" in err


def test_html_reports_broker_aggregate_as_estimate_not_certain():
    result={"rows":[],"total":70,"coverage":90,"label":"관찰"}
    inst={"name":"삼성전자","code":"005930"}
    summary=summarize_targets(_reports(),100000,QUOTE_DATE,TODAY)
    html=render_html(inst,result,"투자 참고용",100000,QUOTE_DATE,
                     {"price":"테스트"},target_summary=summary)
    assert "140,000원" in html
    assert "40.00%" in html
    assert "수익률 예측이나 보장이 아닙니다" in html
