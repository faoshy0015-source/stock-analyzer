"""Source normalization for 15-point investor flow score."""
import pandas as pd

from flow_model import evaluate_flow_normalized, FLOW_WEIGHTS
from scoring import evaluate, WEIGHTS


def _sample(n=30,foreign=100.0,institution=0.0,turnover=1000.0,cap=500000.0):
    idx=pd.date_range("2026-09-21", periods=n, freq="B")
    flow=pd.DataFrame({"외국인":[foreign]*n,"기관":[institution]*n},index=idx)
    daily=pd.DataFrame({"거래대금":[turnover]*n,"시가총액":[cap]*n},index=idx)
    return flow,daily


def test_full_flow_uses_four_subscores_fifteen_points():
    f,d=_sample()
    r=evaluate_flow_normalized(f,d)
    assert sum(FLOW_WEIGHTS.values())==15
    assert r["covered_weight"]==15
    # Strong turnover flows need not imply maximum cap-normalized demand:
    # 20*100 / 500000 = 0.4% of market cap -> the third subscore is 70.
    assert r["score"]==92
    assert [part["weight"] for part in r["components"]]==[4,5,4,2]
    assert "거래대금" in r["components"][0]["evidence"]


def test_relative_strength_same_after_scaling_krw_amounts():
    small,smallcap=_sample(foreign=1,turnover=100,cap=50000)
    large,largecap=_sample(foreign=100,turnover=10000,cap=5000000)
    a=evaluate_flow_normalized(small,smallcap)
    b=evaluate_flow_normalized(large,largecap)
    assert a["score"]==b["score"]
    assert a["metrics"][20]["pct"]==b["metrics"][20]["pct"]


def test_negative_net_flow_scores_weaker_than_positive():
    f,cap=_sample(foreign=-50.0)
    pos,cap2=_sample(foreign=50.0)
    a=evaluate_flow_normalized(f,cap)
    b=evaluate_flow_normalized(pos,cap2)
    assert a["score"]<b["score"]
    assert a["components"][-1]["score"]==0


def test_without_turnover_only_persistence_2_of_15():
    flow,_=_sample()
    r=evaluate_flow_normalized(flow)
    assert r["covered_weight"]==2
    assert all(x["status"]=="미산출" for x in r["components"][:3])
    assert r["components"][-1]["status"]=="평가"


def test_missing_marketcap_excludes_four_point_cap_score():
    f,d=_sample()
    d["시가총액"]=pd.NA
    r=evaluate_flow_normalized(f,d)
    assert r["covered_weight"]==11
    assert r["components"][2]["status"]=="미산출"


def test_misaligned_krx_dates_must_not_use_inaccurate_ratio():
    f,d=_sample()
    d.index=d.index-pd.Timedelta(days=365)
    r=evaluate_flow_normalized(f,d)
    assert r["covered_weight"]==2
    assert r["components"][0]["score"] is None


def test_yahoo_price_volume_proxy_is_explicitly_labelled():
    f,_=_sample()
    close=pd.DataFrame({"Close":[100]*len(f),"Volume":[1000]*len(f)},index=f.index)
    r=evaluate_flow_normalized(f,prices=close,market_cap=500000)
    assert r["covered_weight"]==15
    assert "근사" in r["components"][0]["source"]


def test_evaluate_integration_uses_actual_flow_coverage():
    flow,cap=_sample()
    profile={"__daily_turnover":cap,"marketCap":500000.0}
    r=evaluate(pd.DataFrame(),pd.DataFrame(),pd.DataFrame(),
               flow,pd.DataFrame(),profile)
    item=next(x for x in r["rows"] if x["category"]=="수급")
    assert item["covered_weight"]==15
    assert item["tests"]==4
    assert r["coverage"]==15
    assert sum(WEIGHTS.values())==100
