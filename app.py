"""Stock Analyzer v1.3 — independent Korea equity research, transparent sources."""
from __future__ import annotations
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data_sources import (SEED, seed_listing, get_listing, get_corp_codes,
                          find_instrument, clean_code, get_prices, get_profile,
                          get_investor_flows, dart_disclosures, dart_financials, dart_full_fy_metrics, get_news,
                          get_corp_codes_diagnostic, diagnose_dart, DART_KNOWN_CORP_CODES,
                          get_kis_access_token, get_kis_quote)
from scoring import evaluate, explain, diagnostic_summary, pct_change, number
from report import render_html, snapshot
from trade_plan import conditional_trade_plan
from proposal_visuals import png_summary
from valuation_sources import krx_company_marketcap, fill_valuation, positive, display_valuation_ratios
from valuation_context import fetch_valuation_context
from analyst_reports import get_analyst_reports, HANKYUNG_PORTAL, NAVER_RESEARCH, NAVER_ITEM_RESEARCH
from flow_model import fetch_krx_turnover_context
from consensus_targets import summarize_targets, naver_published_consensus
from access_gate import require_login
from approved_email_gate import require_approved_email
from app_navigation import render_navigation
from admin_tools import render_admin_controls
from provider_resilience import optional_fetch
from score_table import render_score_table

st.set_page_config(page_title='Stock Analyzer · K.H.AHN', page_icon='📊', layout='wide',
                   initial_sidebar_state='expanded')
COLORS={'ink':'#203d35','teal':'#008878','orange':'#e87d31','amber':'#ecad4c','mint':'#e9f6ee','cream':'#fffaf3','red':'#c95b55'}
st.markdown('''<style>
:root{
  --stock-cream:#f4f8f7;--stock-paper:#ffffff;--stock-mint:#e3f1eb;
  --stock-orange:#e87d31;--stock-teal:#008878;--stock-ink:#203d35;
  --stock-border:#cfdfd9;
}
html,body,[class*="css"]{font-family:"Pretendard","Noto Sans KR","Malgun Gothic",sans-serif}
[data-testid="stAppViewContainer"]{
  background:linear-gradient(150deg,#f7fcfa 0%,#f4f8f7 48%,#edf6f0 100%);
}
.block-container{padding-top:1.6rem;max-width:1400px;padding-bottom:3rem}
[data-testid="stSidebar"]{
  background:linear-gradient(175deg,#edf5f2 0%,#f4f8f7 56%,#eef6f1 100%)!important;
  border-right:1px solid #cfdfd9;
}
[data-testid="stSidebar"] h1,[data-testid="stSidebar"] h2{
  color:#345a4b!important;
}
[data-testid="stSidebar"] [data-testid="stButton"] button{
  border:1px solid #c8dbd3!important;
  border-radius:10px!important;
  color:#365b4a!important;
  background:#ffffff!important;
  font-weight:620!important;
}
[data-testid="stSidebar"] [data-testid="stButton"] button:hover{
  border-color:#008878!important;background:#e5f2ec!important;color:#006f62!important;
}
[data-testid="stSidebar"] [data-testid="stTextInput"] input{
  border:1px solid #c8dbd3!important;
  background:#fffefa!important;border-radius:10px!important;
}
[data-testid="stSidebar"] hr{border-color:#d5e6dc}
.brand{
  position:relative;overflow:hidden;
  padding:24px 27px 23px;
  background:linear-gradient(112deg,#dcefe6 0%,#f8fcfa 65%,#edf7f1 100%);
  border:1px solid #c8e3d6;
  border-left:5px solid #008878;
  border-radius:16px;
  box-shadow:0 7px 24px rgba(26,97,78,.065);
  margin-bottom:15px;
}
.brand:after{
  content:"";position:absolute;width:190px;height:190px;
  right:-48px;top:-100px;border:1px solid rgba(0,136,120,.21);
  border-radius:50%;box-shadow:0 0 0 34px rgba(0,136,120,.045),
    0 0 0 68px rgba(19,140,120,.045);pointer-events:none;
}
.brand h1{
  position:relative;margin:8px 0 6px;font-size:29px;
  font-weight:820;letter-spacing:-.8px;color:#164b42;
}
.brand p{position:relative;margin:3px 0;color:#64776a;font-size:13px}
.brand .eyebrow{
  position:relative;font-size:10px;letter-spacing:1.8px;
  color:#c66d27;font-weight:800;
}
.slim{background:#e6f3ed;color:#126958;padding:6px 10px;
  border-radius:8px;display:inline-block;font-size:12px;font-weight:700}
.stTabs [data-baseweb="tab-list"]{gap:7px;flex-wrap:wrap}
.stTabs [data-baseweb="tab"]{
  background:#f6faf8;border:1px solid #d4e7dc;border-radius:9px;
  padding:8px 13px;color:#536d5e;
}
.stTabs [aria-selected="true"]{
  background:#dcefe6!important;color:#006f62!important;
  border:1px solid #a8d0bf!important;font-weight:740!important;
}
.stTabs [data-baseweb="tab-highlight"]{background:#008878!important}
[data-testid="stMetric"]{
  position:relative;overflow:hidden;background:#fffefa;
  border:1px solid #cfdfd9;border-top:3px solid #008878;
  border-radius:13px;padding:16px;
  box-shadow:0 3px 15px rgba(18,94,76,.05);
}
[data-testid="stMetricLabel"]{color:#5b6d5e!important}
[data-testid="stMetricValue"]{
  font-size:clamp(1.15rem,1.8vw,1.75rem)!important;
  color:#2d5748!important;font-weight:720!important;
}
[data-testid="stMetricDelta"]{font-weight:700}
[data-testid="stMain"] [data-testid="stButton"] button[kind="primary"],
[data-testid="stMain"] [data-testid="stBaseButton-primary"]{
  background:#008878!important;border:1px solid #008878!important;
  color:#fff!important;font-weight:750!important;
}
[data-testid="stMain"] [data-testid="stButton"] button[kind="primary"]:hover,
[data-testid="stMain"] [data-testid="stBaseButton-primary"]:hover{
  background:#006f62!important;border-color:#006f62!important;
}
[data-testid="stMain"] [data-testid="stButton"] button[kind="primary"] p{
  color:#fff!important;
}

[data-testid="stExpander"]{border-color:#d0e1d7!important;border-radius:11px}
[data-testid="stDataFrame"]{border:1px solid #cfdfd9;border-radius:9px}
[data-testid="stMain"] [data-testid="stButton"] button:hover,
[data-testid="stMain"] [data-testid="stLinkButton"] a:hover{
  border-color:#008878!important;
}
input:focus-visible,button:focus-visible{
  outline-color:#008878!important;
}
.tiny{font-size:12px;color:#758274}
.notes{
  border-left:4px solid #df913c;background:#fff4e5;
  border-radius:8px;padding:14px 18px;line-height:1.75;color:#405347;
}
[data-testid="stAlert"]{border-radius:11px}
/* Fit the entire evidence table into its column without cutting off trust text. */
.score-table-wrap{width:100%;margin-top:8px;border:1px solid #e9dccb;
  border-radius:10px;overflow:hidden;background:#fffefa}
.score-compact-table{width:100%;table-layout:fixed;border-collapse:collapse;
  font-size:12px;line-height:1.5;color:#354e41}
.score-compact-table th,.score-compact-table td{
  padding:9px 5px;border-bottom:1px solid #f0e6da;
  overflow-wrap:anywhere;word-break:keep-all;vertical-align:middle;
  white-space:normal;text-align:left;
}
.score-compact-table thead th{background:#fff1df;color:#76532f;font-weight:740}
.score-compact-table tbody th{font-weight:650;color:#315a49}
.score-compact-table tbody tr:last-child>*{border-bottom:0}
.score-compact-table td.score-number{text-align:center;font-variant-numeric:tabular-nums;
  white-space:nowrap;padding-left:2px;padding-right:2px}
.score-compact-table td.score-full{color:#157d68;font-weight:700}
.score-compact-table td.score-partial{color:#ad6429;font-weight:700}
.score-compact-table td.score-missing{color:#8c8c84}
.score-compact-table td.score-trust{color:#5e7061;font-size:11px}
h2,h3{color:#345348}
@media(max-width:760px){
  .brand{padding:18px 20px}
  .brand h1{font-size:25px}
  [data-testid="stMetric"]{padding:12px}
}
</style>''',unsafe_allow_html=True)


def secret(name):
    try:return str(st.secrets.get(name,'') or '').strip()
    except Exception:return ''


# Authenticate before rendering the dashboard or contacting external APIs.
# Password is read only from Streamlit Secrets, never from GitHub files.
require_approved_email(st, "stock-analyzer", "Stock Analyzer")
require_login(st)

from krx_auth import configure_streamlit_krx
KRX_LOGIN_READY = configure_streamlit_krx(st)
render_navigation(st)


@st.cache_data(ttl=21600,show_spinner=False)
def cached_kis_token(appkey,secret):return get_kis_access_token(appkey,secret)

@st.cache_data(ttl=45,show_spinner=False)
def cached_kis_quote(code,appkey,secret,token):return get_kis_quote(code,appkey,secret,token)

@st.cache_data(ttl=86400,show_spinner=False)
def cached_listing():return get_listing()

@st.cache_data(ttl=86400,show_spinner=False)
def cached_corp_codes(key):return get_corp_codes_diagnostic(key)

@st.cache_data(ttl=1800,show_spinner=False)
def cached_price(code,market):return get_prices(code,market)

@st.cache_data(ttl=7200,show_spinner=False)
def cached_profile(symbol):return get_profile(symbol)

@st.cache_data(ttl=43200,show_spinner=False)
def cached_krx_valuation(code,market,key):return krx_company_marketcap(code,market,key)

@st.cache_data(ttl=1800,show_spinner=False)
def cached_valuation_context(code,market):return fetch_valuation_context(code,market)

@st.cache_data(ttl=3600,show_spinner=False)
def cached_flow(code):return get_investor_flows(code)

@st.cache_data(ttl=3600,show_spinner=False)
def cached_turnover(code):return fetch_krx_turnover_context(code)

@st.cache_data(ttl=10800,show_spinner=False)
def cached_fin(key,corp):return dart_financials(key,corp)

@st.cache_data(ttl=10800,show_spinner=False)
def cached_full_fy(key,corp,year,scope):return dart_full_fy_metrics(key,corp,year,scope)

@st.cache_data(ttl=1800,show_spinner=False)
def cached_news(name):return get_news(name)

@st.cache_data(ttl=3600,show_spinner=False)
def cached_disclosures(key,corp):return dart_disclosures(key,corp)

@st.cache_data(ttl=3600,show_spinner=False)
def cached_analyst_reports(code,name):return get_analyst_reports(code,name,limit=18)

@st.cache_data(ttl=3600,show_spinner=False)
def cached_published_consensus(code):return naver_published_consensus(code)


def fmt(v, unit='', decimal=1):
    x=number(v)
    return f'{x:,.{decimal}f}{unit}' if x is not None else '—'


def won(v):
    x=number(v)
    if x is None:return '—'
    if abs(x)>=1e12:return f'{x/1e12:,.2f}조원'
    if abs(x)>=1e8:return f'{x/1e8:,.0f}억원'
    return f'{x:,.0f}원'


def line_chart(df, cols, title='', ytitle=''):
    fig=go.Figure()
    for i,(column,label) in enumerate(cols):
        if column not in df:continue
        fig.add_trace(go.Scatter(x=df.index,y=df[column],mode='lines',name=label,
                                 line={'color':['#138c78','#e87d31','#c06f4d','#90a654'][i%4], 'width':2.4}))
    fig.update_layout(title=title,template='plotly_white',height=365,
                      margin=dict(l=12,r=12,t=42,b=15),legend=dict(orientation='h',y=-.18),
                      xaxis_title='',yaxis_title=ytitle,hovermode='x unified')
    return fig


st.markdown('''<div class="brand"><div class="eyebrow">INDEPENDENT STOCK RESEARCH · VERSION 1.3</div>
<h1>Stock Analyzer</h1><p>주가 · 기업실적 · 밸류에이션 · 수급 · 뉴스 · 종합 평가 &nbsp; · &nbsp; CREATED BY K.H.AHN</p></div>''',unsafe_allow_html=True)

with st.sidebar:
    st.title('🔎 종목 분석')
    st.caption('국내 KOSPI · KOSDAQ 주식')
    q=st.text_input('종목명 또는 6자리 종목코드',value=st.session_state.get('query','005930'),
                    placeholder='예: 삼성전자 또는 005930')
    api_key=secret('DART_API_KEY')
    kis_key=secret('KIS_APP_KEY')
    kis_secret=secret('KIS_APP_SECRET')
    krx_key=(secret('KRX_API_KEY') or secret('KRX_AUTH_KEY') or
             secret('KRX_OPEN_API_KEY') or secret('KRX_OPENAPI_KEY') or
             secret('KRX_KEY') or secret('AUTH_KEY'))
    st.divider()
    st.caption('종목 검색 범위 갱신 · 관리자 전용')
    def _admin_refresh_krx():
        with st.spinner('KRX 종목 목록을 확인하는 중...'):
            st.session_state['krx_listing'] = cached_listing()

    def _admin_refresh_dart():
        with st.spinner('DART 기업코드 ZIP 읽는 중...'):
            st.session_state['dart_listing'], st.session_state['dart_load_error'] = (
                cached_corp_codes(api_key)
            )

    render_admin_controls(
        st, krx_loader=_admin_refresh_krx,
        dart_loader=_admin_refresh_dart if api_key else None,
    )
    st.divider()
    with st.expander('🔧 DART 연결 진단',expanded=False):
        st.caption('DART 키는 Secrets에서만 읽으며, 진단 결과에 키 값을 표시하지 않습니다.')
        st.caption('DART 인증키: ' + ('등록 확인' if api_key else '미등록'))
        if st.button('DART 연결 진단 실행',key='dart_connection_test',use_container_width=True):
            with st.spinner('기업개황·재무 API 상태 확인 중...'):
                st.session_state['dart_connection_diagnostic']=diagnose_dart(api_key)
        diag=st.session_state.get('dart_connection_diagnostic')
        if diag:
            msg=f"{diag.get('상태','확인 불가')}: {diag.get('상세','')}"
            if diag.get('코드'): msg+=f" (DART 상태코드 {diag['코드']})"
            if diag.get('상태')=='정상':st.success(msg)
            else:st.warning(msg)
    st.divider()
    if st.button('🔒 로그아웃', use_container_width=True):
        st.session_state.pop('_hanav_stock_authenticated',None)
        st.rerun()
    st.caption('• OpenDART·KIS 인증정보는 Streamlit Secrets에서 관리합니다.')
    st.caption('• 데이터는 실시간 체결 시세가 아닐 수 있습니다.')
    st.caption('• 투자 권유가 아닌 참고용 리서치 도구입니다.')

base=seed_listing()
extra=st.session_state.get('krx_listing',pd.DataFrame())
dart_list=st.session_state.get('dart_listing',pd.DataFrame())
if not extra.empty:
    base=pd.concat([base,extra],ignore_index=True).drop_duplicates('code',keep='last')
if not dart_list.empty:
    dl=dart_list.copy();dl['market']='DART 상장기업'
    base=pd.concat([base,dl[['code','name','market']]],ignore_index=True).drop_duplicates('code',keep='first')

# Allow partial names when only one match; let the user select among many.
resolved=find_instrument(q,base)
if resolved is None and q.strip():
    matches=base[base['name'].str.contains(q.strip(),case=False,regex=False,na=False)].head(100)
    if not matches.empty:
        choices=[f'{row["name"]} ({row["code"]})' for _,row in matches.iterrows()]
        selected=st.selectbox('일치하는 종목 선택',choices,index=0)
        resolved=find_instrument(selected.rsplit('(',1)[-1].rstrip(')'),base)

if not resolved:
    st.warning('종목을 찾지 못했습니다. 6자리 종목코드를 입력하거나 왼쪽에서 종목 목록을 불러오세요.')
    st.stop()

data_issues = []
if api_key and dart_list.empty:
    # DART catalogue is optional: a bad response may not prevent analysis
    # of stocks that already have a verified fallback company code.
    with st.spinner('DART 기업코드 확인...'):
        dart_list,dart_error=optional_fetch(
            "DART 상장사 목록",
            lambda: cached_corp_codes(api_key),
            lambda: (pd.DataFrame(), "DART 기업코드 응답 없음"),
            data_issues,
        )
        st.session_state['dart_load_error']=dart_error
        if not dart_list.empty:st.session_state['dart_listing']=dart_list
corp_code=DART_KNOWN_CORP_CODES.get(resolved['code'],'')
known_dart_fallback=bool(corp_code)
if not dart_list.empty:
    match=dart_list[dart_list['code']==resolved['code']]
    if not match.empty:
        corp_code=str(match.iloc[0]['corp_code'])
        known_dart_fallback=False
        if resolved['name'].startswith('종목 '):resolved['name']=str(match.iloc[0]['name'])

with st.status('시세·재무·수급·뉴스 데이터 취합',expanded=False) as status:
    st.write('주가 데이터 로드')
    prices,symbol,price_source,price_error=optional_fetch(
        "일별 주가",
        lambda: cached_price(resolved['code'],resolved['market']),
        lambda: (pd.DataFrame(),"","","시세 제공처 연결 실패"),
        data_issues)
    profile=optional_fetch(
        "기업 기본정보",
        lambda: cached_profile(symbol) if symbol.endswith(('.KS','.KQ')) else {},
        dict, data_issues,
        validator=lambda v: isinstance(v, dict))
    profile['__name__']=resolved['name']
    kis_snapshot={}
    if kis_key and kis_secret:
        st.write('KIS 현재가 REST 조회')
        token=optional_fetch(
            "KIS 접근 토큰",
            lambda: cached_kis_token(kis_key,kis_secret),
            lambda: "", data_issues)
        if token:
            kis_snapshot=optional_fetch(
                "KIS 현재가",
                lambda: cached_kis_quote(resolved['code'],kis_key,kis_secret,token),
                dict,data_issues)
    st.write('외국인·기관 수급 / 뉴스 로드')
    flows,flow_error=optional_fetch(
        "KRX 투자자 수급",
        lambda: cached_flow(resolved['code']),
        lambda: (pd.DataFrame(),"KRX 수급 제공처 연결 실패"),
        data_issues)
    daily_turnover,turnover_error=optional_fetch(
        "KRX 거래대금",
        lambda: cached_turnover(resolved['code']) if not flows.empty else (pd.DataFrame(),""),
        lambda: (pd.DataFrame(),"KRX 거래대금 제공처 연결 실패"),
        data_issues)
    profile['__daily_turnover']=daily_turnover
    news=optional_fetch(
        "뉴스",
        lambda: cached_news(resolved['name']),
        pd.DataFrame,data_issues)
    if api_key and corp_code:
        st.write('OpenDART 공시·재무제표 로드')
        annual,quarterly,fs_scope=optional_fetch(
            "DART 재무제표",
            lambda: cached_fin(api_key,corp_code),
            lambda: (pd.DataFrame(),pd.DataFrame(),""),
            data_issues)
        disclosures=optional_fetch(
            "DART 공시",
            lambda: cached_disclosures(api_key,corp_code),
            pd.DataFrame,data_issues)
    else:
        annual,quarterly,fs_scope,disclosures=pd.DataFrame(),pd.DataFrame(),'',pd.DataFrame()
    financial_detail={}
    if api_key and corp_code and not annual.empty and fs_scope in ('CFS','OFS'):
        st.write('DART 현금흐름·이자비용·유동비율 근거 조회')
        fy_year=str(annual.sort_values('period').iloc[-1]['period'])
        financial_detail=optional_fetch(
            "DART 연간 상세 계정",
            lambda: cached_full_fy(api_key,corp_code,fy_year,fs_scope),
            dict,data_issues)
    profile['__financial_context']=financial_detail
    incomplete=bool(prices.empty or (api_key and annual.empty) or flows.empty)
    krx_cap={};krx_valuation_error=''
    if krx_key and (not positive(profile.get('trailingPE')) or
                    not positive(profile.get('priceToBook'))):
        st.write('KRX 시가총액 기반 밸류에이션 대체 조회')
        krx_cap,krx_valuation_error=optional_fetch(
            "KRX 시가총액",
            lambda: cached_krx_valuation(resolved['code'],resolved['market'],krx_key),
            lambda: ({}, "KRX 시가총액 연결 실패"),
            data_issues)
    profile=fill_valuation(profile,krx_cap,annual,kis_snapshot)
    st.write('업종 PER · 과거 5년 밴드 조회')
    valuation_context=optional_fetch(
        "KRX 업종 PER·PBR 및 과거 밴드",
        lambda: cached_valuation_context(resolved['code'],resolved['market']),
        lambda: {"source":"KRX", "errors":["KRX 업종 밸류에이션 연결 실패"]},
        data_issues,
        validator=lambda value: isinstance(value,dict))
    profile['__valuation_context']=valuation_context
    display_ratios=display_valuation_ratios(profile,valuation_context)
    incomplete=(incomplete or display_ratios['PER']['value'] is None or
                display_ratios['PBR']['value'] is None)
    source_errors=list(valuation_context.get('errors') or [])
    data_issues.extend(
        "KRX 밸류에이션: " + str(msg) for msg in source_errors
    )
    status.update(
        label='일부 출처 미수신 · 사용 가능한 데이터로 분석' if (incomplete or data_issues)
              else '분석 데이터 준비 완료',
        state='complete',expanded=False)

scores=evaluate(prices,annual,quarterly,flows,news,profile,disclosures)
indicator=scores['indicators']
price=indicator.get('last')
prev=indicator.get('prev')
change=pct_change(price,prev)
price_date=indicator.get('asof','확인 불가')

# Each broker contributes no more than its most recent report within 90 days.
# Quote date is explicit because Yahoo/FDR is not a live-stream current price.
with st.spinner('최근 리포트 목표주가와 증권사별 표본 확인 중...'):
    analyst_reports,analyst_error=optional_fetch(
        "애널리스트 리포트",
        lambda: cached_analyst_reports(resolved['code'],resolved['name']),
        lambda: (pd.DataFrame(),"리포트 제공처 연결 실패"),
        data_issues)
quoted_price=kis_snapshot.get('price') if kis_snapshot else price
quoted_date=(datetime.now(ZoneInfo('Asia/Seoul')).date().isoformat()
             if kis_snapshot else price_date)
target_summary=summarize_targets(analyst_reports,quoted_price,quoted_date)
published_target={};published_target_error=''
if target_summary['average'] is None:
    published_target,published_target_error=optional_fetch(
        "목표주가 컨센서스",
        lambda: cached_published_consensus(resolved['code']),
        lambda: ({},"제공처 연결 실패"),data_issues)
    if published_target and target_summary.get('price'):
        published_target['upside_pct']=round(
            (published_target['target']/target_summary['price']-1)*100,2)

st.subheader(f"{resolved['name']}  ·  {resolved['code']}")
st.caption(f"{resolved['market']}  |  최종 확인 종가일 {price_date}  |  시세: {price_source or '연동 불가'}  |  분석 실행(KST): {datetime.now(ZoneInfo('Asia/Seoul')).strftime('%Y-%m-%d %H:%M')}")

if kis_snapshot:
    st.success('한국투자증권 KIS REST 시세가 연결되었습니다. 위 시세는 조회 시점 스냅샷이며, 기술적 점수는 별도 일별 종가를 기준으로 합니다.')
if prices.empty:
    st.error('주가 데이터 연결에 실패했습니다. 네트워크 또는 데이터 공급처 상태를 확인하세요. 종목코드가 정확한지도 확인해 주세요.')
    if price_error:st.caption(f'기술 메시지: {price_error}')
if not api_key:
    st.info('OpenDART 인증키가 Secrets에 설정되지 않았습니다. 재무제표·실적 분석·공시 항목은 미산출됩니다. Streamlit 앱 설정의 Secrets에 DART_API_KEY를 추가하세요.')
elif not corp_code:
    dart_error=st.session_state.get('dart_load_error','')
    st.warning('이 종목의 DART 고유번호를 찾지 못해 재무·공시 분석을 보류합니다.' + (f' DART 오류: {dart_error}' if dart_error else ''))
elif known_dart_fallback:
    st.info('DART 전체 기업 목록 조회가 정상 완료되지 않아, 공식 확인된 삼성전자 DART 고유번호로 재무·공시 조회를 시도합니다.')
    if st.session_state.get('dart_load_error'):
        st.caption('DART 기업 목록 상태: '+st.session_state['dart_load_error'])
    if annual.empty and disclosures.empty:
        st.warning('고유번호를 확인했지만 DART 재무·공시 응답이 없습니다. 왼쪽 「DART 연결 진단」을 열어 상세 원인을 확인하세요.')
if flow_error:st.caption(f'참고: {flow_error}')
if turnover_error:st.caption(f'참고: {turnover_error}')
if krx_valuation_error:st.caption('KRX 시가총액 참고: ' + str(krx_valuation_error))
if data_issues:
    with st.expander(f'데이터 연결 상태 · {len(data_issues)}건 확인 필요', expanded=False):
        st.warning('아래 출처는 정상 조회되지 않아 관련 지표를 미산출했습니다. '
                   '확인된 다른 데이터는 계속 표시하지만 종합 점수의 충족률을 확인하세요.')
        for issue in data_issues:
            st.caption('• ' + issue)

m1,m2,m3,m4=st.columns([1.1,1,1,1])
m1.metric('KIS 조회 현재가' if kis_snapshot else '최근 확인 종가',
          fmt(kis_snapshot.get('price') if kis_snapshot else price,'원',0),
          fmt(kis_snapshot.get('delta') if kis_snapshot else change,'%',2) if (kis_snapshot.get('delta') if kis_snapshot else change) is not None else None)
m2.metric('잠정 점수' if scores['partial'] else '종합 점수',fmt(scores['total'],' / 100점',1),help='실제 데이터가 있는 항목의 가중평균. 투자 수익률 예측치가 아닙니다.')
m3.metric('평가 데이터 충족률',f"{scores['coverage']:g}%",help='전체 100점 배점 중 실제 평가한 배점의 합계이며, 밸류에이션은 세부 항목별로 계산합니다.')
m4.metric('종합 의견','판단 보류' if scores['coverage'] < 50 else scores['label'])
if scores['partial']:
    st.warning(f"산출 가능한 평가영역 배점이 {scores['coverage']}%로 제한됩니다. 종합 점수는 잠정치이며 모든 항목이 있는 종목과 직접 비교하지 마세요.")

st.markdown('#### 증권사 목표주가 비교')
if target_summary['average'] is not None:
    a1,a2,a3=st.columns(3)
    a1.metric('최근 90일 평균 목표주가',f"{target_summary['average']:,.0f}원",
              help='증권사별 최신 1건 · 목표가를 명시한 증권사 2곳 이상')
    a2.metric('가격 대비 상승여력',
              f"{target_summary['upside_pct']:+.2f}%" if target_summary['upside_pct'] is not None else '—',
              help='(평균 목표주가 / 조회 시점 가격 - 1) × 100. 수익률 예측이 아닙니다.')
    a3.metric('반영 증권사 수',f"{target_summary['count']}곳")
    st.caption(f"목표주가 분포 {target_summary['min']:,.0f}~{target_summary['max']:,.0f}원 · "
               f"기준 가격 {fmt(target_summary.get('price'),'원',0)}"
               f" ({'KIS 조회 시점 가격' if kis_snapshot else '최종 확인 종가'}, {target_summary.get('price_asof') or '날짜 확인 불가'})"
               " · 리포트 발행 최근 90일 · 중복 증권사 제외 · 가격·목표가의 수정주가 반영 여부 주의")
elif published_target:
    a1,a2=st.columns(2)
    a1.metric('Npay 제공 평균 목표주가 (별도 집계)',f"{published_target['target']:,.0f}원",
              help='표시된 최근 리포트를 앱에서 평균 낸 값이 아닙니다. 제공처에서 집계한 별도 컨센서스입니다.')
    a2.metric('가격 대비 상승여력',
              f"{published_target['upside_pct']:+.2f}%" if published_target.get('upside_pct') is not None else '—')
    st.caption(f"공급처 집계 기준일 {published_target['date']} · 증권사 표본 수/집계기간 미확인"
               " · 앱의 최근 리포트 산술평균과 다름 · 원문·목표주가 변동 여부 확인 필요")
else:
    st.caption('목표주가를 명시한 최근 90일의 서로 다른 증권사 2곳 이상을 확인하지 못해'
               ' 평균 목표가·상승여력을 표시하지 않습니다. 리포트 탭의 원문에서 직접 확인할 수 있습니다.')

st.markdown('### 종합 분석')
st.info(explain(scores))
st.markdown('**실적·가치·수급·재무·추세 요약**')
st.caption(diagnostic_summary(scores))

score_df=pd.DataFrame(scores['rows'])
left,right=st.columns([1,1.28],gap='medium')
with left:
    chart=go.Figure()
    for row in scores['rows']:
        chart.add_trace(go.Bar(x=[row['score'] if row['score'] is not None else 0],y=[row['category']],
                               name=row['category'],orientation='h',marker_color=('#e8a15e' if row['score'] is not None and row.get('covered_weight',0)<row['weight'] else '#138c78' if row['score'] is not None else '#e5e1d8'),
                               text=(f"{row['score']:.1f}*" if row['score'] is not None
                                     and row.get('covered_weight',0)<row['weight']
                                     else f"{row['score']:.1f}" if row['score'] is not None
                                     else '미산출'),textposition='inside',
                               showlegend=False,hovertemplate='%{y}: %{text}<extra></extra>'))
    chart.update_layout(height=330,template='plotly_white',margin=dict(l=0,r=0,t=15,b=15),
                        xaxis=dict(range=[0,100],title='각 영역 점수 (0~100)'),
                        yaxis=dict(autorange='reversed'))
    st.plotly_chart(chart,use_container_width=True)
    st.caption('청록색은 해당 영역 전체 배점 평가, 황금색(*)은 일부 배점만 평가, 회색은 미산출을 의미합니다. 재무건전성 100.0*도 미확인된 위험이 없다는 뜻은 아닙니다.')
with right:
    st.markdown('**항목별 배점과 근거**')
    st.markdown(render_score_table(scores['rows']),unsafe_allow_html=True)
    st.caption('배점=전체 비중 · 반영=실제 검증한 배점 · 점수(*)=부분 평가')
    with st.expander('점수 계산 원칙 · 산출 근거',expanded=False):
        st.write('점수는 별도 API 비용 없는 규칙 기반 계산입니다. 누락 배점은 0점 또는 중립으로 채우지 않고, 검증된 배점만 재정규화합니다.')
        for r in scores['rows']:
            st.markdown(f"**{r['category']} · {fmt(r['score'],'점')} / 반영 {r.get('covered_weight',0):g}점 · 전체 배점 {r['weight']}점**")
            for note in r['notes'][:5]:st.caption('• '+note)
            if not r['notes']:st.caption('• 확인 가능한 평가 데이터 없음')

t1,t2,t3,t4,t5,t6=st.tabs(['📉 주가·기술적','📊 실적·재무','🏛️ 가치평가·수급','📰 뉴스·공시','📑 애널리스트 리포트','📥 내보내기·기록'])

with t1:
    if prices.empty:
        st.warning('주가 데이터 없음')
    else:
        span=st.radio('조회 기간',['3개월','6개월','1년','3년'],index=2,horizontal=True)
        days={'3개월':95,'6개월':190,'1년':370,'3년':1100}[span]
        z=prices.loc[prices.index>=pd.Timestamp.now()-pd.Timedelta(days=days)].copy()
        for d in (20,60,120):
            z[f'MA{d}']=pd.to_numeric(prices['Close'],errors='coerce').rolling(d,min_periods=d).mean().reindex(z.index)
        mode=st.radio('차트 유형',['캔들','종가 추이'],horizontal=True)
        f=go.Figure()
        if mode=='캔들' and all(c in z for c in ('Open','High','Low','Close')):
            f.add_trace(go.Candlestick(x=z.index,open=z['Open'],high=z['High'],low=z['Low'],close=z['Close'],
                                       name='OHLC',increasing_line_color='#d86a53',decreasing_line_color='#348c78'))
        else:f.add_trace(go.Scatter(x=z.index,y=z['Close'],name='종가',line=dict(color='#c57231',width=2)))
        for ma,col in ((20,'#138c78'),(60,'#e8a15e'),(120,'#97ab5d')):
            f.add_trace(go.Scatter(x=z.index,y=z[f'MA{ma}'],name=f'MA{ma}',line={'color':col,'width':1.5}))
        f.update_layout(height=470,template='plotly_white',xaxis_rangeslider_visible=False,hovermode='x unified',
                        margin=dict(l=10,r=10,t=12,b=10),legend=dict(orientation='h',y=-.17))
        st.plotly_chart(f,use_container_width=True)
        k1,k2,k3,k4=st.columns(4)
        k1.metric('RSI(14)',fmt(indicator.get('rsi14')))
        k2.metric('최근 20거래일 변화',fmt(indicator.get('return20'),'%'))
        k3.metric('52주 최고 종가',fmt(indicator.get('high52'),'원',0))
        k4.metric('52주 최저 종가',fmt(indicator.get('low52'),'원',0))
        st.caption('52주 고·저는 기간 내 장중 최고가/최저가가 아닌 일별 종가 기준입니다. 시세는 실시간 체결가가 아닙니다.')

with t2:
    if annual.empty:
        st.warning('OpenDART 연간 재무제표가 없습니다. DART 키, 종목코드, 해당 기업의 공시 여부를 확인하세요.')
    else:
        st.caption(f"재무제표 범위: {'연결' if fs_scope=='CFS' else '별도'} / DART 공시 수치 / 단위: 억원")
        display=annual.copy()
        for col in display.columns:
            if col!='period': display[col]=pd.to_numeric(display[col],errors='coerce')/1e8
        aliases={'period':'사업연도','revenue':'매출액','operating_profit':'영업이익','net_income':'당기순이익',
                 'assets':'자산총계','liabilities':'부채총계','equity':'자본총계','operating_cash_flow':'영업현금흐름'}
        st.dataframe(display.rename(columns=aliases).round(1),hide_index=True,use_container_width=True)
        for label,frame in (('연간',annual),('분기',quarterly)):
            if frame.empty:continue
            cols=[x for x in ('revenue','operating_profit','net_income') if x in frame]
            if not cols:continue
            g=frame[['period',*cols]].copy().set_index('period')
            for c in cols:g[c]=pd.to_numeric(g[c],errors='coerce')/1e8
            st.subheader(f'{label} 실적 추이')
            fig=go.Figure()
            for c,cc in [('revenue','#db9158'),('operating_profit','#138c78'),('net_income','#9daa59')]:
                if c in g:fig.add_trace(go.Scatter(x=g.index,y=g[c],mode='lines+markers',name=aliases[c],line=dict(color=cc,width=2)))
            fig.update_layout(height=350,template='plotly_white',margin=dict(l=8,r=8,t=15,b=25),yaxis_title='억원',legend=dict(orientation='h',y=-.2))
            st.plotly_chart(fig,use_container_width=True)
        st.subheader('영업이익 시나리오 (컨센서스 아님)')
        st.caption('확정 실적에 사용자가 지정한 성장률을 적용한 단순 민감도 계산입니다. 애널리스트 전망·시장 컨센서스가 아닙니다.')
        if 'operating_profit' in annual:
            valid=annual[['period','operating_profit']].dropna()
            if not valid.empty:
                last=valid.iloc[-1]
                if last['operating_profit']>0:
                    base_growth=st.slider('영업이익 성장률 가정 (%)',-60,100,10,5)
                    low=float(last['operating_profit'])*(1+(base_growth-15)/100)
                    mid=float(last['operating_profit'])*(1+base_growth/100)
                    hi=float(last['operating_profit'])*(1+(base_growth+15)/100)
                    s1,s2,s3=st.columns(3)
                    s1.metric('보수 (-15%p)',won(low));s2.metric('기준 가정',won(mid));s3.metric('낙관 (+15%p)',won(hi))
                    st.caption(f"산식: {last['period']}년 공시 영업이익 × (1 + 가정 성장률). 실제 다음 사업연도 전망치가 아닙니다.")
                else:st.caption('기준 연간 영업이익이 0 이하이므로 단순 성장률 외삽을 제공하지 않습니다.')
    if not quarterly.empty:
        st.caption('분기 실적은 DART 당기 3개월 금액 사용. 4분기는 사업보고서 연간 금액에서 3분기 누적을 차감해 복원할 수 있는 경우만 표시합니다.')
    st.subheader('재무건전성 검증 항목 (총 20점)')
    financial_row=next(r for r in scores['rows'] if r['category']=='재무건전성')
    financial_parts=financial_row.get('components',[])
    if financial_parts:
        st.dataframe(pd.DataFrame([{
            '평가 항목':x['name'], '배점':x['weight'],
            '검증 배점':x['covered_weight'],
            '획득 점수':f"{x['earned']:.2f}" if x['earned'] is not None else '미산출',
            '결과':x['status'],
        } for x in financial_parts]),hide_index=True,use_container_width=True)
        st.caption(f"실제 검증 {financial_row.get('covered_weight',0):g}/20점 배점 · "
                   "영업현금흐름·이자보상·유동비율을 확인할 수 없으면 20점 전체를 채운 것으로 보지 않습니다.")
        with st.expander('재무 항목 산식·데이터 출처'):
            for x in financial_parts:
                st.markdown(f"**{x['name']} · {x['status']} ({x['covered_weight']}/{x['weight']}점)**")
                st.caption(x['evidence'])
                st.caption('출처: '+x['source'])
            if profile.get('__financial_context'):
                c=profile['__financial_context']
                st.caption(f"DART 상세 재무자료: {c.get('year','')}년 "
                           f"{'연결' if c.get('fs_scope')=='CFS' else '별도'}")
        st.caption('금융업(은행·증권·보험 등)은 제조업용 건전성 기준을 적용하지 않으며 전용 평가가 마련될 때까지 보류합니다.')

with t3:
    st.markdown('#### 한국거래소(KRX) 투자지표 · Npay와 다른 데이터 제공처')
    krx_date=str(valuation_context.get('date') or '')
    krx_specs=[
        ('PER',valuation_context.get('krx_per'),'배',2),
        ('EPS',valuation_context.get('krx_eps'),'원',0),
        ('PBR',valuation_context.get('krx_pbr'),'배',2),
        ('BPS',valuation_context.get('krx_bps'),'원',0),
        ('배당수익률',valuation_context.get('krx_dividend_yield'),'%',2),
        ('주당배당금(DPS)',valuation_context.get('krx_dps'),'원',0),
    ]
    if krx_date and any(number(value) is not None for _,value,_,_ in krx_specs):
        krx_columns=st.columns(3)
        for i,(label,value,unit,decimals) in enumerate(krx_specs):
            with krx_columns[i%3]:
                st.metric(label,fmt(value,unit,decimals) if number(value) is not None else '미확인')
        st.caption(
            f"출처: 한국거래소 투자지표(KRX/pykrx) · 조회 기준일 {krx_date}. "
            "EPS·BPS와 배당 지표는 Npay·FnGuide와 회계연도, 연결/별도, 주식수 조정, "
            "시세 기준일이 달라 수치가 일치하지 않을 수 있습니다. "
            "표시한 EPS는 애널리스트 추정 EPS가 아닙니다."
        )
    else:
        st.info('KRX PER·EPS·PBR·BPS·배당 투자지표를 확인하지 못했습니다. '
                'Npay 화면의 수치를 복사해 대신 채우지 않으며, Yahoo·DART 지표는 아래에 별도 표시합니다.')
        for error in valuation_context.get('errors') or []:
            st.caption('KRX 지표 조회 상태: '+str(error))
    st.caption('추정 EPS·PER은 별도 전망치이며 검증 가능한 제공처 값이 없으면 미산출로 유지합니다.')
    st.divider()
    vc1,vc2=st.columns(2)
    with vc1:
        st.subheader('밸류에이션')
        vals=[
              ('PER (KRX 확인값)' if display_ratios['PER']['kind']=='krx' else 'PER (별도 산출값)',
               display_ratios['PER']['value'],'배'),
              ('Forward PER (Yahoo 추정 · 별도 기준)',profile.get('forwardPE'),'배'),
              ('추정 EPS (Yahoo 추정 · 별도 기준)',profile.get('forwardEps'),'원'),
              ('PBR (KRX 확인값)' if display_ratios['PBR']['kind']=='krx' else 'PBR (별도 산출값)',
               display_ratios['PBR']['value'],'배'),
              ('ROE (DART 간이)' if profile.get('__roe_approx') else 'ROE (외부 제공)',(number(profile.get('returnOnEquity')) or 0)*100 if profile.get('returnOnEquity') is not None else None,'%'),
              ('시가총액 (외부 제공 또는 KRX)',profile.get('marketCap'),'원')]
        for label,val,unit in vals:
            st.write(f'**{label}:** {won(val) if unit=="원" and "시가총액" in label else fmt(val,unit,0 if unit=="원" else 2)}')
        st.caption('PER 출처: '+display_ratios['PER']['source']+' · PBR 출처: '+display_ratios['PBR']['source'])
        st.caption('ROE·시가총액 출처(별도): '+str(profile.get('__valuation_source') or '확인 불가')+
                   ' · 수치마다 산정 시점과 회계 기준이 다를 수 있습니다.')
        if profile.get('__krx_marketcap_date'):
            st.caption('시가총액 원천: 한국거래소 통계정보 (KRX OPEN API)')
            classes=profile.get('__krx_share_classes',[])
            st.caption('KRX 시가총액 기준일: '+profile['__krx_marketcap_date']+
                       (' · 합산 주식코드: '+', '.join(map(str,classes)) if classes else ''))
        if profile.get('__valuation_approx_note'):
            st.warning(profile['__valuation_approx_note'])
        if profile.get('__roe_approx_note'):
            st.caption('간이 ROE 참고: '+profile['__roe_approx_note'])
        if display_ratios['PER']['value'] is None or display_ratios['PBR']['value'] is None:
            st.info('KRX 투자지표와 Yahoo/KIS·DART 대체 지표에서도 PER·PBR 일부를 확인하지 못했습니다. '
                    '조회 기준일과 원천 데이터 상태를 확인하세요. 누락값은 임의로 채우지 않습니다.')
        if krx_valuation_error:
            st.caption('KRX 조회 상태: '+krx_valuation_error)
        st.caption('Yahoo Finance 제공 지표는 결측/지연 가능. Forward PER은 제공처 추정치이며 공식 증권사 컨센서스 검증을 대체하지 않습니다.')
        st.markdown('#### 밸류에이션 점수 구성 (총 20점)')
        valuation_row=next(r for r in scores['rows'] if r['category']=='밸류에이션')
        components=valuation_row.get('components',[])
        if components:
            st.dataframe(pd.DataFrame([{
                '비교 영역':part['name'],
                '배점':part['weight'],
                '반영 배점':part['covered_weight'],
                '획득 점수':f"{part['earned']:.2f}" if part['earned'] is not None else '미산출',
                '진행':part['status'],
            } for part in components]),hide_index=True,use_container_width=True)
            st.caption(f"실제 평가 {valuation_row.get('covered_weight',0):g}/20점 배점 · "
                       "누락된 세부 항목은 0점 또는 중립점으로 대체하지 않습니다.")
            with st.expander('각 항목 평가 근거 · 필요한 데이터'):
                for part in components:
                    st.markdown(f"**{part['name']} ({part['weight']}점) · {part['status']}**")
                    st.caption(part['evidence'])
                    st.caption('출처/산식: '+part['source'])
        if valuation_context.get('date'):
            st.caption('비교 데이터 기준일: '+valuation_context['date']+
                       (' · KRX 업종: '+str(valuation_context['sector_name'])
                        if valuation_context.get('sector_name') else ''))
        if valuation_context.get('errors'):
            st.caption('조회 참고: '+'; '.join(valuation_context['errors'][:3]))
        if valuation_context.get('historical_per') or valuation_context.get('historical_pbr'):
            fig=go.Figure()
            for key,label,color in [('historical_per','과거 월별 PER','#138c78'),
                                    ('historical_pbr','과거 월별 PBR','#e87d31')]:
                vals_hist=valuation_context.get(key) or []
                if vals_hist:
                    fig.add_trace(go.Box(y=vals_hist,name=label,boxpoints=False,
                                         marker_color=color))
            fig.update_layout(template='plotly_white',height=280,
                              margin=dict(l=0,r=0,t=15,b=5),
                              yaxis_title='PER·PBR (배, 서로 다른 척도)')
            st.plotly_chart(fig,use_container_width=True)
            st.caption('박스그래프는 과거 값의 분포입니다. PER과 PBR의 배수 크기는 직접 비교하지 마세요.')
        st.caption('평가기준: 업종 PER 비교 6점 + 과거 밴드 5점 + 최근 3개년 ROE 지속성 5점 + '
                   '동기준 Forward PER 4점. ROE 5점은 PER과 동치인 PBR/ROE 역산을 제거하고 '
                   '장기 수익의 안정성을 측정합니다. '
                   '전망 컨센서스 제공처가 없으면 Forward PER 4점은 평가에서 제외됩니다.')
    with vc2:
        st.subheader('외국인·기관 순매수')
        if flows.empty:st.warning('KRX 수급 정보 미수신. 해당 항목은 총점 계산에서 제외됩니다.')
        else:
            ff=flows.tail(60)/1e8
            f=go.Figure()
            for name,color in [('외국인','#138c78'),('기관','#e8a15e')]:
                f.add_trace(go.Bar(x=ff.index,y=ff[name],name=name,marker_color=color))
            f.update_layout(barmode='relative',template='plotly_white',height=340,
                            yaxis_title='일별 순매수 (억원)',margin=dict(l=5,r=5,t=10,b=10),legend=dict(orientation='h',y=-.18))
            st.plotly_chart(f,use_container_width=True)
            for d in (5,20,60):
                if len(flows)>=d:
                    fnet=float(flows['외국인'].tail(d).sum()); inet=float(flows['기관'].tail(d).sum())
                    st.caption(f'{d}거래일: 외국인 {won(fnet)} / 기관 {won(inet)}')
            st.caption('순매수 단위는 원입니다. KRX 조회 가능 범위에 따라 데이터가 달라질 수 있습니다.')
        flow_row=next(row for row in scores['rows'] if row['category']=='수급')
        st.markdown('#### 시가총액·거래대금 보정 수급점수 (15점)')
        flow_parts=flow_row.get('components',[])
        if flow_parts:
            st.dataframe(pd.DataFrame([{
                '세부 평가':part['name'],'배점':part['weight'],
                '반영 배점':part['covered_weight'],
                '점수':f"{part['score']:.1f}" if part['score'] is not None else '미산출',
            } for part in flow_parts]),hide_index=True,use_container_width=True)
            st.caption(f"평가된 배점 {flow_row.get('covered_weight',0):g}/15점 · "
                       "같은 날짜의 거래대금·시총을 기준으로 순매수 규모를 정규화합니다.")
            with st.expander('순매수 강도 계산 근거'):
                for part in flow_parts:
                    st.markdown(f"**{part['name']} ({part['covered_weight']}/{part['weight']}점 배점)**")
                    st.caption(part['evidence'])
                    st.caption('출처: '+part['source'])
                st.caption('외국인+기관 순매수는 일별 KRX 거래대금 기준. '
                           '공식 거래대금이 없을 경우 종가×거래량 근사치를 사용하고 명시합니다. '
                           '시총은 보통주 기준일 수 있으며 미수신 항목은 점수에서 제외됩니다.')

with t4:
    st.subheader('공시·뉴스 기반 이벤트 모멘텀')
    event_row=next(r for r in scores['rows'] if r['category']=='뉴스 모멘텀')
    parts=event_row.get('components',[])
    if parts:
        st.dataframe(pd.DataFrame([{
            '구성':part['name'],'배점':part['weight'],
            '검증 배점':part['covered_weight'],
            '점수':f"{part['score']:.1f}" if part['score'] is not None else '미산출',
            '판정':part['status'],
        } for part in parts]),hide_index=True,use_container_width=True)
        st.caption(f"검증 {event_row.get('covered_weight',0):g}/10점 배점. "
                   "공시 제목(6점)과 서로 다른 매체의 최근 뉴스 제목(4점)으로만 평가합니다. "
                   "기사 본문을 읽거나 이벤트의 재무영향을 검증하지 않은 낮은 신뢰도의 참고 지표입니다.")
        with st.expander('모멘텀 평가 근거와 한계'):
            for part in parts:
                st.markdown(f"**{part['name']} · {part['status']}**")
                st.caption(part['evidence'])
    events=event_row.get('events',[])
    if events:
        st.markdown('**탐지된 주요 이벤트 (원문 바로가기)**')
        for item in sorted(events,key=lambda event:event.get('date',''),reverse=True)[:12]:
            link=str(item.get('link',''))
            title=str(item.get('title',''))
            if link.startswith(('https://','http://')):
                st.markdown(f"[{title}]({link})")
            else:
                st.write(title)
            st.caption(f"{item.get('date','')} · {item.get('source','')} · "
                       f"{item.get('type','')} | {item.get('reason','')}")
    else:
        st.info('평가 가능한 주요 이벤트가 확인되지 않았습니다. 이는 호재나 악재가 없다는 확정 판단이 아닙니다.')
    st.divider()
    st.subheader('최근 뉴스')
    if news.empty:st.info('뉴스 RSS 조회 결과가 없습니다. DART 공시 이벤트는 별도로 평가될 수 있습니다.')
    else:
        for _,item in news.head(16).iterrows():
            link=str(item.get('link',''))
            title=str(item.get('title',''))
            source=str(item.get('source',''))
            if link.startswith(('http://','https://')):st.markdown(f'[{title}]({link})')
            else:st.write(title)
            st.caption(f'{source} · {item.get("date","")}')
        st.caption('기사 제목은 단서일 뿐입니다. 맥락·오보·중복 기사·금액 규모는 평가하지 못하므로 반드시 원문을 확인하세요.')
    st.divider()
    st.subheader('OpenDART 주요 공시')
    if disclosures.empty:st.info('최근 조회 가능한 공시가 없거나 DART 키가 설정되지 않았습니다.')
    else:
        for _,d in disclosures.head(30).iterrows():
            no=str(d.get('rcept_no',''))
            title=str(d.get('report_nm',''))
            date=str(d.get('rcept_dt',''))
            st.markdown(f'[{title}](https://dart.fss.or.kr/dsaf001/main.do?rcpNo={no})  ·  {date}')

with t5:
    st.subheader('최근 애널리스트 리포트')
    st.caption('선택한 종목의 증권사 리포트를 코드로 조회합니다. 제목을 누르면 출처의 상세 페이지에서 원문을 확인할 수 있습니다.')
    st.link_button(f"📑 {resolved['name']} 종목 리포트 직접 보기 (Npay 증권)",
                   NAVER_ITEM_RESEARCH.format(code=resolved['code']),use_container_width=True)
    st.markdown('#### EQUITY 골드회원 리서치')
    st.link_button('🔎 EQUITY 골드회원 종목 리포트 검색',
                   'https://www.equity.co.kr/reports/company',
                   help='EQUITY에서 별도 로그인한 뒤 종목명 또는 종목코드로 검색합니다.',
                   use_container_width=True)
    st.caption(
        f"EQUITY 사이트에서 로그인 후 '{resolved['name']}'"
        f" ({resolved['code']})를 검색하세요. 계정정보를 Stock Analyzer에 입력하지 않으며, "
        "유료 리포트를 자동 수집·저장·재배포하지 않습니다. "
        "공식 데이터 제공 허가가 확인되기 전까지 검색 링크로만 연결합니다."
    )
    st.markdown('#### 최근 목표주가 집계')
    if target_summary['average'] is not None:
        cc1,cc2,cc3=st.columns(3)
        cc1.metric('최근 리포트 평균 목표주가',f"{target_summary['average']:,.0f}원")
        cc2.metric('현재 기준 가격 대비',
                   f"{target_summary['upside_pct']:+.2f}%" if target_summary['upside_pct'] is not None else '—')
        cc3.metric('반영 증권사',f"{target_summary['count']}곳")
        st.dataframe(pd.DataFrame([{
            '증권사':item['broker'],'발행일':item['date'],
            '목표주가(원)':item['target'],'제목':item['title'],'원문':item['url'],
        } for item in target_summary['rows']]),
            column_config={'원문':st.column_config.LinkColumn('원문 리포트')},
            hide_index=True,use_container_width=True)
        st.caption(f"목표주가 범위 {target_summary['min']:,.0f}~{target_summary['max']:,.0f}원 · "
                   '최근 90일, 증권사별 가장 최근 리포트 1건만 반영한 단순 산술평균입니다. '
                   '서로 다른 증권사 2곳 이상 기준이며, 수익률이나 적정가치를 보장하지 않습니다.')
    elif published_target:
        st.metric('Npay 제공 목표주가 컨센서스 (별도 집계)',
                  f"{published_target['target']:,.0f}원",
                  f"{published_target['upside_pct']:+.2f}%" if published_target.get('upside_pct') is not None else None)
        st.caption(f"기준일 {published_target['date']} · 최근 리포트의 증권사별 산술평균이 아닙니다. "
                   "집계 표본과 기준기간은 제공처가 명시하지 않아 확인할 수 없습니다.")
    else:
        st.info('목표주가 숫자가 확인된 최근 리포트 2개 증권사 이상이 없어 '
                '평균 목표주가를 산출할 수 없습니다.')
        if published_target_error:st.caption('제공처 집계 확인: '+published_target_error)
    st.divider()
    if analyst_reports.empty:
        st.info('이 종목의 리포트를 자동 조회하지 못했습니다. 위 종목 전용 Npay 리서치 링크에서 직접 확인할 수 있습니다.')
        if analyst_error:st.caption(analyst_error)
    else:
        st.caption(f"최근 6개월 내 확인된 기업 리포트 {len(analyst_reports)}건 · 발행일 최신순")
        for _,report_row in analyst_reports.iterrows():
            rpt_title=str(report_row['title'])
            rpt_link=str(report_row['url'])
            rpt_date=str(report_row['date'])
            rpt_broker=str(report_row['broker'] or '발행기관 미표기')
            rpt_analyst=str(report_row['analyst'] or '')
            rpt_target=str(report_row['target_price'] or '')
            rpt_source=str(report_row.get('source','') or '')
            if rpt_link.startswith(('https://','http://')):
                st.link_button(f"📄 {rpt_title}",rpt_link,help='원문 제공 사이트에서 열기',use_container_width=True)
            else:
                st.write(rpt_title)
            rpt_detail=f"발행 {rpt_date} · {rpt_broker}" + (f" · {rpt_source}" if rpt_source else '')
            if rpt_analyst:rpt_detail+=f" · {rpt_analyst}"
            if rpt_target:rpt_detail+=f" · 목표주가 {rpt_target}"
            st.caption(rpt_detail)
        st.caption('발행일·목표가·투자의견은 원문 작성 시점의 판단입니다. 최신 데이터·분할조정 여부는 원문에서 확인하세요.')
    st.divider()
    st.markdown('**전체 리포트 출처에서 직접 검색**')
    col_hk,col_nv=st.columns(2)
    col_hk.link_button('한경 컨센서스 리포트 검색',HANKYUNG_PORTAL,use_container_width=True)
    col_nv.link_button('Npay 증권 리서치',NAVER_ITEM_RESEARCH.format(code=resolved['code']),use_container_width=True)
    st.caption('보고서의 PDF를 앱 서버에 저장하거나 재배포하지 않습니다. 자동 수집 실패 시 원문 제공처에서 종목명을 검색하세요.')

with t6:
    st.subheader('저장 · 고객 설명용 리포트')
    st.caption('인쇄용 HTML에는 주가·점수 그래프와 보유자/신규 검토자별 조건부 전략이 포함됩니다. '
               'PNG는 한 장짜리 요약 이미지이며, JSON은 그림이 아닌 과거 분석 기록입니다.')
    final_text=explain(scores)
    source_map={'price':('KIS REST 시세 + '+price_source) if kis_snapshot else (price_source or '연동 없음'),
                'financial':f'OpenDART {fs_scope}' if not annual.empty else '연동 없음',
                'flows':'KRX(pykrx)' if not flows.empty else '연동 없음',
                'news':'Google News RSS + OpenDART 공시 이벤트' if not news.empty or not disclosures.empty else '연동 없음'}
    price_for_report=kis_snapshot.get('price',price)
    report_stamp=(f'KIS 조회(KST) {datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M")}'
                  f' / 일별 종가 {price_date}' if kis_snapshot else price_date)
    trade_plan=conditional_trade_plan(scores,prices,target_summary,published_target)
    html=render_html(resolved,scores,final_text,price_for_report,report_stamp,source_map,
                     target_summary=target_summary,published_target=published_target,
                     prices=prices,trade_plan=trade_plan)
    with st.expander('보고서에 포함되는 보유자·신규 매수 검토 전략 보기',expanded=False):
        p1,p2=st.columns(2)
        with p1:
            st.markdown('**기존 보유자 관점**')
            for line in trade_plan['holder']:st.write('• '+line)
        with p2:
            st.markdown('**신규 매수 검토자 관점**')
            for line in trade_plan['new_buyer']:st.write('• '+line)
        st.markdown('**주요 체크포인트**')
        for line in trade_plan['checkpoints']:st.write('• '+line)
        st.caption(trade_plan['disclaimer'])
    try:
        summary_png=png_summary(resolved,scores,price_for_report,report_stamp,
                                prices=prices,plan=trade_plan,
                                target_summary=target_summary,published_target=published_target)
    except (ImportError,OSError,ValueError,TypeError) as exc:
        summary_png=None
        st.warning(f'PNG 생성에 실패했습니다: {type(exc).__name__}. '
                   '인쇄용 HTML과 JSON은 정상적으로 내려받을 수 있습니다.')
    c1,c2=st.columns(2)
    c1.download_button('📄 차트·전략 포함 인쇄용 HTML',html,
                       file_name=f'StockAnalyzer_Proposal_{resolved["code"]}.html',
                       mime='text/html',use_container_width=True)
    if summary_png:
        c2.download_button('🖼️ 한 장 요약 이미지 PNG',summary_png,
                           file_name=f'StockAnalyzer_Summary_{resolved["code"]}.png',
                           mime='image/png',use_container_width=True)
        with st.expander('한 장 요약 이미지 미리보기',expanded=False):
            st.image(summary_png,caption='PNG 요약: 주요 지표·정량점수·주가·조건부 전략',
                     use_container_width=True)
    else:
        c2.button('🖼️ 한 장 요약 이미지 PNG 생성 불가',disabled=True,use_container_width=True)
    c3,c4=st.columns(2)
    c3.download_button('🗂️ 점수 기록 JSON (과거 비교용)',
                       snapshot(resolved,scores,price_date),
                       file_name=f'StockAnalyzer_Snapshot_{resolved["code"]}.json',
                       mime='application/json',use_container_width=True)
    c4.download_button('📋 평가 근거 CSV',
                       score_df[['category','weight','score','confidence']].to_csv(index=False).encode('utf-8-sig'),
                       file_name=f'StockAnalyzer_Scores_{resolved["code"]}.csv',
                       mime='text/csv',use_container_width=True)
    st.caption('HTML은 브라우저에서 열어 인쇄 또는 PDF로 저장하세요. SVG 차트는 HTML 안에 포함되어 '
               '오프라인에서도 보입니다. 외부 고객 제공 전 자료 이용권한과 내부 준법 절차를 확인하세요.')
    st.divider()
    st.subheader('이전 분석과 점수 변화 비교')
    old=st.file_uploader('이전에 내려받은 점수 스냅샷 JSON을 업로드하세요',type=['json'])
    if old is not None:
        try:
            prevdata=json.loads(old.getvalue().decode('utf-8'))
            if str(prevdata.get('instrument',{}).get('code',''))!=resolved['code']:
                st.error('업로드한 스냅샷과 현재 종목코드가 다릅니다.')
            elif prevdata.get('version')!=1:
                st.error('지원하지 않는 스냅샷 형식입니다.')
            else:
                old_score=number(prevdata.get('score'));new_score=scores['total']
                if old_score is not None and new_score is not None:
                    st.metric('종합 점수 변화',fmt(new_score,'점'),f'{new_score-old_score:+.1f}점')
                if prevdata.get('coverage')!=scores['coverage']:
                    st.warning(f"이전 충족률 {prevdata.get('coverage')}% → 현재 {scores['coverage']}%. 평가 가능한 항목이 달라 총점 변화에 결측 효과가 포함됩니다.")
                for row in scores['rows']:
                    prevcat=prevdata.get('categories',{}).get(row['category'],{})
                    p=number(prevcat.get('score'));n=row['score']
                    if p is not None and n is not None:
                        st.write(f"{row['category']}: {p:.1f} → {n:.1f} ({n-p:+.1f}점)")
        except Exception:
            st.error('유효한 Stock Analyzer 스냅샷 JSON을 읽지 못했습니다.')

st.divider()
st.caption('Stock Analyzer v1.3 · CREATED BY K.H.AHN | 시세: Yahoo Finance/FinanceDataReader · 재무/공시: OpenDART · 수급: KRX(pykrx) · 뉴스: Google News RSS · 증권사 리포트: Npay 증권(종목코드 조회)·한경 컨센서스(보조). 외부 서버·뉴스 피드 정책 변경 시 일부 항목이 중단될 수 있습니다. 정량 점수는 이익/수익률 예측, 투자자문 또는 목표주가가 아닙니다.')
