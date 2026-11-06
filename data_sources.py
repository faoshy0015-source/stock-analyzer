"""External data adapters. Every adapter fails independently; no fabricated live data."""
from __future__ import annotations
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
import re
import zipfile
import xml.etree.ElementTree as ET
from urllib.parse import quote

import pandas as pd
import requests

DART = 'https://opendart.fss.or.kr/api'
# OpenDART 공식 개발가이드에 확인 가능한 상장사 고유번호만 긴급 대체 매핑.
DART_KNOWN_CORP_CODES = {'005930': '00126380'}
HEADERS = {'User-Agent': 'HanaVStockAnalyzer/1.0 (private research application)'}
SEED = {
 '005930': ('삼성전자','KOSPI'), '000660': ('SK하이닉스','KOSPI'),
 '035420': ('NAVER','KOSPI'), '035720': ('카카오','KOSPI'),
 '005380': ('현대차','KOSPI'), '000270': ('기아','KOSPI'),
 '051910': ('LG화학','KOSPI'), '373220': ('LG에너지솔루션','KOSPI'),
 '207940': ('삼성바이오로직스','KOSPI'), '006400': ('삼성SDI','KOSPI'),
 '105560': ('KB금융','KOSPI'), '055550': ('신한지주','KOSPI'),
 '086790': ('하나금융지주','KOSPI'), '012330': ('현대모비스','KOSPI'),
 '028260': ('삼성물산','KOSPI'), '068270': ('셀트리온','KOSPI'),
 '247540': ('에코프로비엠','KOSDAQ'), '086520': ('에코프로','KOSDAQ'),
 '196170': ('알테오젠','KOSDAQ'), '042700': ('한미반도체','KOSPI'),
 '009540': ('HD한국조선해양','KOSPI'), '010140': ('삼성중공업','KOSPI'),
 '034020': ('두산에너빌리티','KOSPI'), '267260': ('HD현대일렉트릭','KOSPI'),
 '298040': ('효성중공업','KOSPI'), '012450': ('한화에어로스페이스','KOSPI'),
 '047810': ('한국항공우주','KOSPI'), '035900': ('JYP Ent.','KOSDAQ'),
 '263750': ('펄어비스','KOSDAQ'), '035760': ('CJ ENM','KOSDAQ'),
}


def clean_code(code):
    result = re.sub(r'\D', '', str(code or ''))
    return result.zfill(6) if 0 < len(result) <= 6 else ''


def get_listing():
    """Optional FinanceDataReader listing. Can fail due to external endpoint changes."""
    try:
        import FinanceDataReader as fdr
        raw = fdr.StockListing('KRX')
        if raw is None or raw.empty:
            return pd.DataFrame()
        code_col = next((x for x in ['Code','Symbol','종목코드'] if x in raw.columns), None)
        name_col = next((x for x in ['Name','종목명'] if x in raw.columns), None)
        market_col = next((x for x in ['Market','시장구분'] if x in raw.columns), None)
        if not code_col or not name_col:
            return pd.DataFrame()
        out = pd.DataFrame({'code': raw[code_col].astype(str).str.extract(r'(\d{6})')[0],
                            'name': raw[name_col].astype(str),
                            'market': raw[market_col].astype(str) if market_col else 'KRX'})
        return out.dropna(subset=['code']).drop_duplicates('code')
    except Exception:
        return pd.DataFrame()


def seed_listing():
    return pd.DataFrame([{'code':c,'name':v[0],'market':v[1]} for c,v in SEED.items()])


DART_STATUS_MESSAGES = {
    '010': '등록되지 않은 OpenDART 인증키입니다.',
    '011': 'OpenDART에서 사용할 수 없는 인증키입니다.',
    '012': 'OpenDART 접근 제한 IP입니다.',
    '013': '조회된 데이터가 없습니다.',
    '014': 'DART 파일이 존재하지 않습니다.',
    '020': 'OpenDART API 요청 한도 초과입니다.',
    '800': 'OpenDART 시스템 점검 중입니다.',
    '901': 'OpenDART 인증키 사용자 정보 갱신이 필요합니다.',
}


def get_corp_codes_diagnostic(api_key):
    """(상장법인 목록, 비밀키를 포함하지 않는 오류 설명)."""
    if not api_key:
        return pd.DataFrame(), 'DART_API_KEY가 Secrets에 없습니다.'
    try:
        resp = requests.get(f'{DART}/corpCode.xml', params={'crtfc_key':api_key},
                            timeout=(8, 35), headers=HEADERS)
        resp.raise_for_status()
        stream = BytesIO(resp.content)
        if not zipfile.is_zipfile(stream):
            # DART API 오류는 정상 ZIP 대신 XML 메시지로 돌아올 수 있습니다.
            try:
                error = ET.fromstring(resp.content)
                code = (error.findtext('status') or error.findtext('.//status') or '').strip()
                reason = DART_STATUS_MESSAGES.get(code, 'OpenDART에서 기업코드 ZIP 대신 오류 응답을 반환했습니다.')
                return pd.DataFrame(), f'{reason} (DART 코드 {code or "미확인"})'
            except ET.ParseError:
                return pd.DataFrame(), 'OpenDART 기업코드 응답이 ZIP 형식이 아닙니다.'
        with zipfile.ZipFile(stream) as z:
            xml_file = next((n for n in z.namelist() if n.lower().endswith('.xml')), None)
            if not xml_file:
                return pd.DataFrame(), 'OpenDART ZIP 안에 기업코드 XML이 없습니다.'
            root = ET.fromstring(z.read(xml_file))
        rows = []
        for element in root.findall('.//list'):
            code = (element.findtext('stock_code') or '').strip()
            corp = (element.findtext('corp_code') or '').strip()
            if re.fullmatch(r'\d{6}', code) and re.fullmatch(r'\d{8}', corp):
                rows.append({'code':code,'corp_code':corp,
                             'name':(element.findtext('corp_name') or '').strip()})
        if not rows:
            return pd.DataFrame(), 'OpenDART 기업 목록에서 상장사 종목코드를 찾지 못했습니다.'
        return pd.DataFrame(rows).drop_duplicates('code'), ''
    except requests.exceptions.Timeout:
        return pd.DataFrame(), 'OpenDART 기업코드 요청 시간이 초과되었습니다.'
    except requests.exceptions.RequestException as exc:
        # Requests의 오류 문자열에는 인증키를 포함한 URL이 들어갈 수 있어 노출 금지.
        return pd.DataFrame(), f'OpenDART 기업코드 연결 오류 ({type(exc).__name__}).'
    except (OSError, ValueError, ET.ParseError, zipfile.BadZipFile, StopIteration) as exc:
        return pd.DataFrame(), f'OpenDART 기업코드 해석 오류 ({type(exc).__name__}).'


def get_corp_codes(api_key):
    """기존 호출용 호환 인터페이스."""
    return get_corp_codes_diagnostic(api_key)[0]



def diagnose_dart(api_key, corp_code='00126380'):
    """On-demand connection check. Safe for UI: never returns API keys, URLs or payload data."""
    if not api_key:
        return {'상태':'설정 안 됨','상세':'Streamlit Secrets에 DART_API_KEY가 없습니다.'}
    key = str(api_key).strip()
    if len(key) != 40:
        return {'상태':'키 형식 확인 필요',
                '상세':f'OpenDART 키는 공식적으로 40자리여야 합니다. 현재 Secrets 값의 길이는 {len(key)}자리입니다.'}
    try:
        response = requests.get(f'{DART}/company.json',
                                params={'crtfc_key':key,'corp_code':corp_code},
                                headers=HEADERS,timeout=(8,15))
        if response.status_code != 200:
            return {'상태':'HTTP 접속 오류','상세':f'DART 서버 HTTP {response.status_code} 응답'}
        result=response.json()
        status=str(result.get('status',''))
        if status != '000':
            return {'상태':'API 거부', '코드':status,
                    '상세':DART_STATUS_MESSAGES.get(status,'OpenDART가 요청을 거부했습니다.')}
    except requests.exceptions.Timeout:
        return {'상태':'연결 시간 초과','상세':'Streamlit Cloud에서 DART 요청이 제한시간을 초과했습니다.'}
    except requests.exceptions.RequestException as exc:
        return {'상태':'통신 오류','상세':f'요청 오류 유형: {type(exc).__name__}'}
    except (ValueError,TypeError):
        return {'상태':'응답 오류','상세':'DART 기업개황 응답이 JSON 형식이 아닙니다.'}

    # 기업개황 성공과 재무제표 조회 성공은 별개이므로 각각 확인한다.
    try:
        r=requests.get(f'{DART}/fnlttSinglAcnt.json',
                       params={'crtfc_key':key,'corp_code':corp_code,
                               'bsns_year':'2024','reprt_code':'11011'},
                       headers=HEADERS,timeout=(8,15))
        if r.status_code != 200:
            return {'상태':'인증 성공·재무 조회 실패',
                    '상세':f'기업개황 API 정상, 재무제표 API HTTP {r.status_code}'}
        body=r.json()
        status=str(body.get('status',''))
        if status == '000':
            count=len(body.get('list') or [])
            return {'상태':'정상','상세':f'기업개황 인증 성공 · 2024년 연간 재무계정 {count}건 응답'}
        return {'상태':'인증 성공·재무 조회 제한','코드':status,
                '상세':DART_STATUS_MESSAGES.get(status,'재무제표 API 오류')}
    except requests.exceptions.Timeout:
        return {'상태':'인증 성공·재무 시간 초과',
                '상세':'기업개황은 정상이나 재무제표 API 요청 시간이 초과되었습니다.'}
    except requests.exceptions.RequestException as exc:
        return {'상태':'인증 성공·재무 통신 오류',
                '상세':f'재무제표 API 요청 오류 유형: {type(exc).__name__}'}
    except (ValueError,TypeError):
        return {'상태':'인증 성공·재무 응답 오류',
                '상세':'재무제표 API 응답이 JSON 형식이 아닙니다.'}


def find_instrument(search, listing):
    """Returns {code,name,market} or None. Exact codes do not require a listing."""
    q = str(search).strip()
    code = clean_code(q) if re.fullmatch(r'\d{1,6}', q) else ''
    if code:
        matches = listing[listing['code'].eq(code)] if not listing.empty else pd.DataFrame()
        if not matches.empty:
            return matches.iloc[0][['code','name','market']].to_dict()
        name, market = SEED.get(code, (f'종목 {code}','미확인'))
        return {'code':code, 'name':name, 'market':market}
    if listing.empty:
        return None
    matches = listing[listing['name'].str.casefold().eq(q.casefold())]
    if len(matches) == 1:
        return matches.iloc[0][['code','name','market']].to_dict()
    return None


def get_prices(code, market=''):
    """Try Yahoo both suffixes; then FinanceDataReader as a fallback. Historical close can be delayed."""
    import yfinance as yf
    suffixes = ['.KQ','.KS'] if 'KOSDAQ' in market.upper() else ['.KS','.KQ']
    problems=[]
    for suff in suffixes:
        symbol = code + suff
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period='3y', auto_adjust=False, timeout=12)
            if hist is not None and not hist.empty and 'Close' in hist:
                hist = hist.copy()
                hist.index = pd.DatetimeIndex(hist.index).tz_localize(None).normalize()
                hist = hist[~hist.index.duplicated(keep='last')].sort_index()
                hist = hist.dropna(subset=['Close'])
                if len(hist) >= 5:
                    return hist, symbol, 'Yahoo Finance (지연 시세)', None
        except Exception as exc:
            problems.append(str(exc)[:100])
    try:
        import FinanceDataReader as fdr
        df = fdr.DataReader(code, (datetime.now()-timedelta(days=1095)).strftime('%Y-%m-%d'))
        if df is not None and not df.empty and 'Close' in df:
            df = df.copy()
            df.index = pd.DatetimeIndex(df.index).tz_localize(None).normalize()
            return df.sort_index(), code, 'FinanceDataReader (일별 종가)', None
    except Exception as exc:
        problems.append(str(exc)[:100])
    return pd.DataFrame(), '', '', '; '.join(problems[:2]) or '시세 제공처 응답 없음'


def get_profile(yahoo_symbol):
    if not yahoo_symbol.endswith(('.KS','.KQ')):
        return {}
    try:
        import yfinance as yf
        info = yf.Ticker(yahoo_symbol).info
        return dict(info) if isinstance(info, dict) else {}
    except Exception:
        return {}


def get_investor_flows(code, days=115):
    """KRX-reported net trading value (KRW), pykrx uses external KRX endpoints."""
    try:
        from pykrx import stock
        end = datetime.today()
        start = end - timedelta(days=days)
        df = stock.get_market_trading_value_by_date(start.strftime('%Y%m%d'),end.strftime('%Y%m%d'),code)
        if df is None or df.empty:
            return pd.DataFrame(), 'KRX 수급 응답 없음'
        df = df.copy().sort_index()
        foreign = next((col for col in df if '외국인' in str(col)),None)
        inst = next((col for col in df if '기관합계' in str(col)),None)
        if not foreign or not inst:
            return pd.DataFrame(), '수급 컬럼 구조가 변경됨'
        out = pd.DataFrame({'외국인':pd.to_numeric(df[foreign],errors='coerce'),
                            '기관':pd.to_numeric(df[inst],errors='coerce')}).dropna(how='all')
        return out, None
    except Exception as exc:
        return pd.DataFrame(), f'KRX 수급 조회 불가: {str(exc)[:120]}'


def _dart_get(api_key, endpoint, **params):
    try:
        response = requests.get(f'{DART}/{endpoint}', params={'crtfc_key':api_key, **params},headers=HEADERS,timeout=12)
        response.raise_for_status()
        obj = response.json()
        return obj if obj.get('status') == '000' else {}
    except Exception:
        return {}


def dart_disclosures(api_key, corp_code, days=95):
    if not api_key or not corp_code:
        return pd.DataFrame()
    end=datetime.today()
    data = _dart_get(api_key,'list.json',corp_code=corp_code,bgn_de=(end-timedelta(days=days)).strftime('%Y%m%d'),
                     end_de=end.strftime('%Y%m%d'),page_count=100,sort='date',sort_mth='desc')
    items=data.get('list',[])
    out=pd.DataFrame(items)
    return out if not out.empty else pd.DataFrame()


REPORTS = [('11011','FY'),('11013','Q1'),('11012','Q2'),('11014','Q3')]


def _amount(item, field='thstrm_amount'):
    raw=str(item.get(field,'')).replace(',','').replace('△','-').strip()
    if raw in ('','-','None'):
        return None
    try: return float(raw)
    except (ValueError,TypeError): return None


def _label_account(item):
    return (item.get('account_nm') or '').strip().replace(' ','').replace('　','')


def _statement_values(items):
    """Pick income statement first, then BS. DART major accounts list may include duplicates."""
    fields = {
        'revenue': ['매출액','영업수익','수익(매출액)','매출','이자수익'],
        'operating_profit': ['영업이익','영업이익(손실)'],
        'net_income': ['당기순이익','당기순이익(손실)','분기순이익','반기순이익'],
        'assets': ['자산총계'], 'liabilities':['부채총계'], 'equity':['자본총계'],
        'operating_cash_flow':['영업활동현금흐름','영업활동으로인한현금흐름'],
    }
    results={}
    for key,names in fields.items():
        sj = ['IS','CIS'] if key in ('revenue','operating_profit','net_income') else ['BS'] if key in ('assets','liabilities','equity') else ['CF']
        candidates=[x for x in items if x.get('sj_div') in sj and x.get('fs_div') in ('CFS','OFS')]
        for name in names:
            match=next((item for item in candidates if _label_account(item)==name), None)
            if match:
                n = _amount(match)
                if n is not None:
                    results[key]=n
                    if key in ('revenue','operating_profit','net_income'):
                        results[key+'_ytd']=_amount(match,'thstrm_add_amount')
                    break
    return results


def dart_financials(api_key, corp_code, years=5):
    """Annual and interim statements for CFS or OFS consistently; no guessed future filings.

    Returns (annual, quarterly, fs_scope). Quarter income uses reported 3-month amounts;
    Q4 = annual amount minus 9m cumulative amount where the source supports it.
    """
    if not api_key or not corp_code:
        return pd.DataFrame(),pd.DataFrame(),''
    curr=datetime.today()
    year_list=list(range(curr.year-years, curr.year+1))
    tasks=[]
    for year in year_list:
        tasks.append((year,'11011'))
        if year >= curr.year-3:
            tasks += [(year,'11013'),(year,'11012'),(year,'11014')]
    results={}
    def get_task(task):
        y,report=task
        data=_dart_get(api_key,'fnlttSinglAcnt.json',corp_code=corp_code,bsns_year=str(y),reprt_code=report)
        return task,data.get('list',[])
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures=[pool.submit(get_task,task) for task in tasks]
        for fut in as_completed(futures):
            try:
                task,rows=fut.result()
                results[task]=rows
            except Exception: pass
    has_cfs = any(any(x.get('fs_div')=='CFS' for x in rows) for rows in results.values())
    scope='CFS' if has_cfs else 'OFS'
    def subset(y,r):
        return [x for x in results.get((y,r),[]) if x.get('fs_div')==scope]
    annual=[]; quarterly=[]
    for year in year_list:
        fy=_statement_values(subset(year,'11011'))
        if fy:
            annual.append({'period':str(year), **{k:v for k,v in fy.items() if not k.endswith('_ytd')}})
        if year < curr.year-3: continue
        q3_ytd=None
        for report,q in [('11013','Q1'),('11012','Q2'),('11014','Q3')]:
            d=_statement_values(subset(year,report))
            if not d: continue
            row={'period':f'{year} {q}'}
            for k,v in d.items():
                if not k.endswith('_ytd'):
                    row[k]=v
            quarterly.append(row)
            if q=='Q3': q3_ytd=d
        if fy and q3_ytd:
            row={'period':f'{year} Q4'}
            for key in ('revenue','operating_profit','net_income'):
                a=fy.get(key)
                b=q3_ytd.get(key+'_ytd')
                if a is not None and b is not None:
                    row[key]=a-b
            if len(row)>1:
                quarterly.append(row)
    a=pd.DataFrame(annual).sort_values('period') if annual else pd.DataFrame()
    q=pd.DataFrame(quarterly).sort_values('period') if quarterly else pd.DataFrame()
    return a,q,scope


def get_news(query, limit=20):
    """Headline + publisher from public Google News RSS, no paywalled article scraping."""
    try:
        import feedparser
        search=quote(f'{query} 주식 OR 실적 when:30d')
        url=f'https://news.google.com/rss/search?q={search}&hl=ko&gl=KR&ceid=KR:ko'
        resp=requests.get(url,headers={'User-Agent':'Mozilla/5.0'},timeout=12)
        resp.raise_for_status()
        data=feedparser.parse(resp.content)
        rows=[]
        for e in data.entries[:limit]:
            rows.append({'title':e.get('title',''), 'link':e.get('link',''),
                        'date': e.get('published',''), 'source':e.get('source',{}).get('title','')})
        return pd.DataFrame(rows)
    except Exception:
        return pd.DataFrame()


def get_kis_access_token(app_key, app_secret):
    """KIS production OAuth access token. Never log or persist raw credentials."""
    if not app_key or not app_secret:return ''
    try:
        base='https://openapi.koreainvestment.com:9443'
        res=requests.post(base+'/oauth2/tokenP',json={
            'grant_type':'client_credentials','appkey':app_key,'appsecret':app_secret},timeout=12)
        res.raise_for_status()
        return str(res.json().get('access_token',''))
    except Exception:return ''


def get_kis_quote(code,app_key,app_secret,token):
    """KIS REST current-price snapshot, NOT a streaming WebSocket quote."""
    if not token:return {}
    try:
        url='https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-price'
        res=requests.get(url,headers={'authorization':f'Bearer {token}',
                 'appkey':app_key,'appsecret':app_secret,'tr_id':'FHKST01010100',
                 'custtype':'P'},params={'FID_COND_MRKT_DIV_CODE':'J','FID_INPUT_ISCD':code},timeout=12)
        res.raise_for_status()
        data=res.json()
        if str(data.get('rt_cd',''))!='0':return {}
        o=data.get('output') or {}
        price=float(o.get('stck_prpr',0) or 0)
        return {'price':price,'delta':number_string(o.get('prdy_ctrt')),
                'volume':number_string(o.get('acml_vol'))} if price>0 else {}
    except Exception:return {}


def number_string(raw):
    try:return float(str(raw).replace(',',''))
    except (TypeError,ValueError):return None
