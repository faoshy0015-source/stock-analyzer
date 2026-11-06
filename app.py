"""HanaV Stock Analyzer v1.0 — Korea equity research, transparent sources."""
from __future__ import annotations
import json
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data_sources import (SEED, seed_listing, get_listing, get_corp_codes,
                          find_instrument, clean_code, get_prices, get_profile,
                          get_investor_flows, dart_disclosures, dart_financials, get_news,
                          get_corp_codes_diagnostic, DART_KNOWN_CORP_CODES,
                          get_kis_access_token, get_kis_quote)
from scoring import evaluate, explain, pct_change, number
from report import render_html, snapshot

st.set_page_config(page_title='HanaV Stock Analyzer', page_icon='📊', layout='wide',
                   initial_sidebar_state='expanded')
COLORS={'navy':'#123452','teal':'#008b83','muted':'#6b7c91','green':'#008b83','red':'#d55055'}
st.markdown('''<style>
html,body,[class*="css"]{font-family:"Pretendard","Noto Sans KR","Malgun Gothic",sans-serif}
.block-container{padding-top:1.6rem;max-width:1400px;padding-bottom:3rem}
[data-testid="stSidebar"]{background:#f1f5f9}
.brand{padding:22px 25px;background:linear-gradient(115deg,#102942,#1b4a6a);border-radius:15px;color:white;margin-bottom:14px}
.brand h1{margin:4px 0 4px;font-size:28px;font-weight:800;letter-spacing:-.7px;color:white}
.brand p{margin:2px 0;color:#cde0ea;font-size:13px}
.brand .eyebrow{font-size:11px;letter-spacing:2px;color:#77d6ce;font-weight:700}
.slim{background:#eaf6f5;color:#086760;padding:6px 10px;border-radius:8px;display:inline-block;font-size:12px;font-weight:700}
.stTabs [data-baseweb="tab-list"]{gap:8px}
.stTabs [data-baseweb="tab"]{background:#f1f5f9;border-radius:8px;padding:8px 15px}
.stTabs [aria-selected="true"]{background:#d5eeeb!important;color:#0b6d68!important}
[data-testid="stMetric"]{background:white;border:1px solid #e3eaf0;border-radius:12px;padding:16px}
.tiny{font-size:12px;color:#6b7c91}
.notes{border-left:4px solid #008b83;background:#f0f8f7;border-radius:7px;padding:13px 17px;line-height:1.7}
[data-testid="stAlert"]{border-radius:10px}
</style>''',unsafe_allow_html=True)


def secret(name):
    try:return str(st.secrets.get(name,'') or '')
    except Exception:return ''

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

@st.cache_data(ttl=3600,show_spinner=False)
def cached_flow(code):return get_investor_flows(code)

@st.cache_data(ttl=10800,show_spinner=False)
def cached_fin(key,corp):return dart_financials(key,corp)

@st.cache_data(ttl=1800,show_spinner=False)
def cached_news(name):return get_news(name)

@st.cache_data(ttl=3600,show_spinner=False)
def cached_disclosures(key,corp):return dart_disclosures(key,corp)


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
                                 line={'color':['#008b83','#e5a642','#4c70c5','#9d79b6'][i%4], 'width':2.4}))
    fig.update_layout(title=title,template='plotly_white',height=365,
                      margin=dict(l=12,r=12,t=42,b=15),legend=dict(orientation='h',y=-.18),
                      xaxis_title='',yaxis_title=ytitle,hovermode='x unified')
    return fig


def narrative_ai(key, instrument, score, source_text):
    from openai import OpenAI
    client=OpenAI(api_key=key,timeout=25,max_retries=1)
    payload={'company':instrument,'score':score['total'],'coverage_percent':score['coverage'],
             'categories':[{k:v for k,v in row.items() if k in ('category','score','notes','confidence')} for row in score['rows']],
             'data_asof':source_text}
    answer=client.chat.completions.create(model='gpt-4o-mini',temperature=0.2,
       max_tokens=650,messages=[
        {'role':'system','content':'당신은 한국 주식 리서치 담당 분석가입니다. 입력된 사실만 사용하세요. 추정 수치, 목표주가, 허구의 컨센서스, 출처 없는 사실을 만들지 마세요. 뉴스 제목의 키워드 점수는 낮은 신뢰도라고 표시하세요. 정확한 정보의 기준일, 누락 데이터, 투자 위험을 설명하세요. 매수·매도 확정 권유 금지. 4개 짧은 문단: 종합/강점/위험/체크포인트. 한국어.'},
        {'role':'user','content':json.dumps(payload,ensure_ascii=False,default=str)}])
    return answer.choices[0].message.content or ''


st.markdown('''<div class="brand"><div class="eyebrow">HANAV INVESTMENT INTELLIGENCE · VERSION 1.0</div>
<h1>Stock Analyzer</h1><p>주가 · 기업실적 · 밸류에이션 · 수급 · 뉴스 · 종합 평가</p></div>''',unsafe_allow_html=True)

with st.sidebar:
    st.title('🔎 종목 분석')
    st.caption('국내 KOSPI · KOSDAQ 주식')
    q=st.text_input('종목명 또는 6자리 종목코드',value=st.session_state.get('query','005930'),
                    placeholder='예: 삼성전자 또는 005930')
    api_key=secret('DART_API_KEY')
    openai_key=st.text_input('OpenAI API 키 (선택)',value=secret('OPENAI_API_KEY'),
                             type='password',help='AI 의견 버튼을 눌렀을 때만 유료 API가 호출됩니다.')
    kis_key=secret('KIS_APP_KEY')
    kis_secret=secret('KIS_APP_SECRET')
    st.divider()
    st.caption('종목 검색 범위')
    if st.button('KRX 전체 종목 목록 불러오기',use_container_width=True):
        with st.spinner('KRX 종목 목록을 확인하는 중...'):
            st.session_state['krx_listing']=cached_listing()
    if api_key and st.button('DART 상장사 목록 불러오기',use_container_width=True):
        with st.spinner('DART 기업코드 ZIP 읽는 중...'):
            st.session_state['dart_listing'],st.session_state['dart_load_error']=cached_corp_codes(api_key)
    if st.button('새로고침 (캐시 초기화)',use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.divider()
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

if api_key and dart_list.empty:
    # Fetch once when the user starts analyzing a listed stock, no prior manual setup.
    with st.spinner('DART 기업코드 확인...'):
        dart_list,dart_error=cached_corp_codes(api_key)
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
    prices,symbol,price_source,price_error=cached_price(resolved['code'],resolved['market'])
    profile=cached_profile(symbol) if symbol.endswith(('.KS','.KQ')) else {}
    profile['__name__']=resolved['name']
    kis_snapshot={}
    if kis_key and kis_secret:
        st.write('KIS 현재가 REST 조회')
        token=cached_kis_token(kis_key,kis_secret)
        kis_snapshot=cached_kis_quote(resolved['code'],kis_key,kis_secret,token) if token else {}
    st.write('외국인·기관 수급 / 뉴스 로드')
    flows,flow_error=cached_flow(resolved['code'])
    news=cached_news(resolved['name'])
    if api_key and corp_code:
        st.write('OpenDART 공시·재무제표 로드')
        annual,quarterly,fs_scope=cached_fin(api_key,corp_code)
        disclosures=cached_disclosures(api_key,corp_code)
    else:
        annual,quarterly,fs_scope,disclosures=pd.DataFrame(),pd.DataFrame(),'',pd.DataFrame()
    status.update(label='분석 데이터 준비 완료',state='complete',expanded=False)

scores=evaluate(prices,annual,quarterly,flows,news,profile)
indicator=scores['indicators']
price=indicator.get('last')
prev=indicator.get('prev')
change=pct_change(price,prev)
price_date=indicator.get('asof','확인 불가')

st.subheader(f"{resolved['name']}  ·  {resolved['code']}")
st.caption(f"{resolved['market']}  |  최종 확인 종가일 {price_date}  |  시세: {price_source or '연동 불가'}  |  분석 실행: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

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
    if annual.empty and disclosures.empty:
        st.warning('고유번호를 확인했지만 DART 재무·공시 응답이 없습니다. Secrets의 DART_API_KEY 유효성·접근 권한·호출 제한을 확인하세요.')
if flow_error:st.caption(f'참고: {flow_error}')

m1,m2,m3,m4=st.columns([1.1,1,1,1])
m1.metric('KIS 조회 현재가' if kis_snapshot else '최근 확인 종가',
          fmt(kis_snapshot.get('price') if kis_snapshot else price,'원',0),
          fmt(kis_snapshot.get('delta') if kis_snapshot else change,'%',2) if (kis_snapshot.get('delta') if kis_snapshot else change) is not None else None)
m2.metric('종합 점수',fmt(scores['total'],' / 100점',1),help='실제 데이터가 있는 항목의 가중평균. 투자 수익률 예측치가 아닙니다.')
m3.metric('평가 데이터 충족률',f"{scores['coverage']}%",help='전체 100점 배점 중 점수를 산출한 항목의 배점 합계입니다.')
m4.metric('종합 의견',scores['label'])
if scores['partial']:
    st.warning(f"산출 가능한 평가영역 배점이 {scores['coverage']}%로 제한됩니다. 종합 점수는 잠정치이며 모든 항목이 있는 종목과 직접 비교하지 마세요.")

st.markdown('### 종합 분석')
st.info(explain(scores))

score_df=pd.DataFrame(scores['rows'])
left,right=st.columns([1.15,1])
with left:
    chart=go.Figure()
    for row in scores['rows']:
        chart.add_trace(go.Bar(x=[row['score'] if row['score'] is not None else 0],y=[row['category']],
                               name=row['category'],orientation='h',marker_color='#008b83' if row['score'] is not None else '#dde4ec',
                               text=(f"{row['score']:.1f}" if row['score'] is not None else '미산출'),textposition='inside',
                               showlegend=False,hovertemplate='%{y}: %{text}<extra></extra>'))
    chart.update_layout(height=330,template='plotly_white',margin=dict(l=0,r=0,t=15,b=15),
                        xaxis=dict(range=[0,100],title='각 영역 점수 (0~100)'),
                        yaxis=dict(autorange='reversed'))
    st.plotly_chart(chart,use_container_width=True)
with right:
    st.markdown('**항목별 배점과 근거**')
    st.dataframe(pd.DataFrame([{'영역':r['category'],'배점':r['weight'],
        '평가':f"{r['score']:.1f}" if r['score'] is not None else '미산출',
        '신뢰도':r['confidence']} for r in scores['rows']]),hide_index=True,use_container_width=True)
    with st.expander('점수 계산 원칙 · 산출 근거',expanded=True):
        st.write('점수는 규칙 기반 계산이며 OpenAI 모델이 산출하지 않습니다. 결측 영역은 0점으로 간주하지 않고 남은 영역의 배점을 재정규화합니다.')
        for r in scores['rows']:
            st.markdown(f"**{r['category']} · {fmt(r['score'],'점')} / 배점 {r['weight']}**")
            for note in r['notes'][:5]:st.caption('• '+note)
            if not r['notes']:st.caption('• 확인 가능한 평가 데이터 없음')

if openai_key:
    if st.button('✨ 선택: OpenAI로 종합 의견 다시 작성 (API 비용 발생)',type='primary'):
        with st.spinner('근거 기반 문장 생성 중...'):
            try:
                st.session_state['ai_narrative']=(resolved['code'],narrative_ai(openai_key,resolved,scores,price_date))
            except Exception as exc:
                st.error(f'AI 호출 실패: {exc}')
else:
    st.caption('기본 종합 의견은 무료 규칙 기반입니다. OpenAI API 키를 입력하면 실제 생성형 AI 분석을 선택적으로 실행할 수 있습니다.')
if st.session_state.get('ai_narrative',(None,None))[0] == resolved['code']:
    st.success('OpenAI 생성 종합 의견 (정량 점수는 변경하지 않음)')
    st.write(st.session_state['ai_narrative'][1])

t1,t2,t3,t4,t5=st.tabs(['📉 주가·기술적','📊 실적·재무','🏛️ 가치평가·수급','📰 뉴스·공시','📥 리포트·기록'])

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
                                       name='OHLC',increasing_line_color='#d55055',decreasing_line_color='#287bba'))
        else:f.add_trace(go.Scatter(x=z.index,y=z['Close'],name='종가',line=dict(color='#123452',width=2)))
        for ma,col in ((20,'#008b83'),(60,'#d7a248'),(120,'#a178c7')):
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
            for c,cc in [('revenue','#1d5e82'),('operating_profit','#008b83'),('net_income','#d7a248')]:
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

with t3:
    vc1,vc2=st.columns(2)
    with vc1:
        st.subheader('밸류에이션')
        vals=[('PER (최근 실적)',profile.get('trailingPE'),'배'),('Forward PER (외부 제공)',profile.get('forwardPE'),'배'),
              ('PBR',profile.get('priceToBook'),'배'),('ROE (외부 제공)',(number(profile.get('returnOnEquity')) or 0)*100 if profile.get('returnOnEquity') is not None else None,'%'),
              ('시가총액 (외부 제공)',profile.get('marketCap'),'원')]
        for label,val,unit in vals:
            st.write(f'**{label}:** {won(val) if unit=="원" else fmt(val,unit,2)}')
        st.caption('Yahoo Finance 제공 지표는 결측/지연 가능. Forward PER은 제공처 추정치이며 공식 증권사 컨센서스 검증을 대체하지 않습니다.')
        st.info('1.0 버전 밸류에이션 점수는 PER·PBR 절대수준과 ROE/PBR 보정의 초기 휴리스틱입니다. 과거 PER 밴드와 업종 경쟁사 비교는 후속 버전에서 정식 데이터 확보 후 제공됩니다.')
    with vc2:
        st.subheader('외국인·기관 순매수')
        if flows.empty:st.warning('KRX 수급 정보 미수신. 해당 항목은 총점 계산에서 제외됩니다.')
        else:
            ff=flows.tail(60)/1e8
            f=go.Figure()
            for name,color in [('외국인','#008b83'),('기관','#d7a248')]:
                f.add_trace(go.Bar(x=ff.index,y=ff[name],name=name,marker_color=color))
            f.update_layout(barmode='relative',template='plotly_white',height=340,
                            yaxis_title='일별 순매수 (억원)',margin=dict(l=5,r=5,t=10,b=10),legend=dict(orientation='h',y=-.18))
            st.plotly_chart(f,use_container_width=True)
            for d in (5,20,60):
                if len(flows)>=d:
                    fnet=float(flows['외국인'].tail(d).sum()); inet=float(flows['기관'].tail(d).sum())
                    st.caption(f'{d}거래일: 외국인 {won(fnet)} / 기관 {won(inet)}')
            st.caption('순매수 단위는 거래대금(원)입니다. KRX 조회 가능 범위에 따라 데이터가 달라질 수 있습니다.')

with t4:
    st.subheader('최근 뉴스')
    if news.empty:st.info('뉴스 RSS 조회 결과 없음. 뉴스 점수는 미산출됩니다.')
    else:
        for _,item in news.head(16).iterrows():
            link=str(item.get('link',''))
            title=str(item.get('title',''))
            source=str(item.get('source',''))
            if link.startswith(('http://','https://')):st.markdown(f'[{title}]({link})')
            else:st.write(title)
            st.caption(f'{source} · {item.get("date","")}')
        st.caption('뉴스는 제목 키워드로만 자동 평가하므로 문맥·오보·중복 기사·보도의 실제 중요도를 정확히 반영하지 못합니다.')
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
    st.subheader('저장 · 보고서 내보내기')
    report_text=st.session_state.get('ai_narrative',(None,None))
    final_text=report_text[1] if report_text[0]==resolved['code'] else explain(scores)
    source_map={'price':('KIS REST 시세 + '+price_source) if kis_snapshot else (price_source or '연동 없음'),
                'financial':f'OpenDART {fs_scope}' if not annual.empty else '연동 없음',
                'flows':'KRX(pykrx)' if not flows.empty else '연동 없음',
                'news':'Google News RSS' if not news.empty else '연동 없음'}
    html=render_html(resolved,scores,final_text,kis_snapshot.get('price',price),
                     f'KIS 조회 {datetime.now().strftime("%Y-%m-%d %H:%M")} / 일별 종가 {price_date}' if kis_snapshot else price_date,source_map)
    c1,c2,c3=st.columns(3)
    c1.download_button('📄 인쇄용 HTML 리포트',html,file_name=f'HanaV_Stock_{resolved["code"]}.html',mime='text/html',use_container_width=True)
    c2.download_button('🗂️ 점수 스냅샷 JSON',snapshot(resolved,scores,price_date),file_name=f'HanaV_Snapshot_{resolved["code"]}.json',mime='application/json',use_container_width=True)
    c3.download_button('📋 평가 근거 CSV',score_df[['category','weight','score','confidence']].to_csv(index=False).encode('utf-8-sig'),file_name=f'HanaV_Scores_{resolved["code"]}.csv',mime='text/csv',use_container_width=True)
    st.caption('HTML은 브라우저에서 열어 인쇄 또는 PDF로 저장할 수 있습니다. 외부 고객 전달 전 자료 사용권과 내부 준법 절차를 검토하세요.')
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
            st.error('유효한 HanaV 스냅샷 JSON을 읽지 못했습니다.')

st.divider()
st.caption('HanaV Stock Analyzer v1.0 | 시세: Yahoo Finance/FinanceDataReader · 재무/공시: OpenDART · 수급: KRX(pykrx) · 뉴스: Google News RSS. 외부 서버·뉴스 피드 정책 변경 시 일부 항목이 중단될 수 있습니다. 정량 점수는 이익/수익률 예측, 투자자문 또는 목표주가가 아닙니다.')
