import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pandas as pd
from scoring import evaluate, get_indicators, pct_change, explain, WEIGHTS
from data_sources import _statement_values, clean_code, find_instrument, seed_listing
from report import render_html,snapshot


def test_all_missing_is_not_zero_score():
    r=evaluate(pd.DataFrame(),pd.DataFrame(),pd.DataFrame(),pd.DataFrame(),pd.DataFrame(),{})
    assert r['total'] is None
    assert r['coverage']==0
    assert all(x['score'] is None for x in r['rows'])
    assert '부족' in explain(r)


def test_technical_coverage_without_fundamentals():
    idx=pd.date_range('2025-01-01',periods=160,freq='B')
    px=pd.DataFrame({'Close':[100+i for i in range(160)],'Volume':[10000]*160},index=idx)
    r=evaluate(px,pd.DataFrame(),pd.DataFrame(),pd.DataFrame(),pd.DataFrame(),{})
    assert r['coverage']==10
    assert r['total'] is not None
    assert r['partial']
    assert r['indicators']['ma120'] is not None


def test_perfect_missing_ratio_not_misleading():
    idx=pd.date_range('2025-01-01',periods=160,freq='B')
    px=pd.DataFrame({'Close':[100+i for i in range(160)]},index=idx)
    r=evaluate(px,pd.DataFrame(),pd.DataFrame(),pd.DataFrame(),pd.DataFrame(),{})
    assert r['coverage']==10
    assert sum(WEIGHTS.values())==100


def test_financial_source_interim_3_months_vs_cumulative():
    rows=[{'sj_div':'IS','fs_div':'CFS','account_nm':'영업이익',
           'thstrm_amount':'5,000','thstrm_add_amount':'12,000'},
          {'sj_div':'BS','fs_div':'CFS','account_nm':'부채총계','thstrm_amount':'8,000'}]
    result=_statement_values(rows)
    assert result['operating_profit']==5000
    assert result['operating_profit_ytd']==12000
    assert result['liabilities']==8000


def test_search_code_and_name():
    assert clean_code('5930')=='005930'
    assert find_instrument('삼성전자',seed_listing())['code']=='005930'
    assert find_instrument('999999',seed_listing())['name']=='종목 999999'


def test_snapshot_and_html_are_printable():
    inst={'name':'샘플 & 테스트','code':'999999','market':'KOSPI'}
    r=evaluate(pd.DataFrame(),pd.DataFrame(),pd.DataFrame(),pd.DataFrame(),pd.DataFrame(),{})
    html=render_html(inst,r,'테스트 <주의>',None,'미수신',{'price':'없음'})
    assert '샘플 &amp; 테스트' in html
    assert '&lt;주의&gt;' in html
    import json
    snap=json.loads(snapshot(inst,r,'미수신'))
    assert snap['score'] is None
    assert snap['coverage']==0


def test_growth_from_loss_is_not_percentage():
    assert pct_change(100,-20) is None
    assert pct_change(100,0) is None
    assert pct_change(110,100)==10.000000000000009
