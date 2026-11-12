"""HanaV Trading sidebar features ported to Stock Analyzer.

Source: hanavtrading-khahn/app.py; retains the prior
KIS master (top 40) -> traded value (top 20) -> WiseReport earnings
momentum (top 5) ranking methodology. No trading/orders or auto-trading.
The data is public/delayed; output is a sample ranking, not a KRX universe.
"""
from __future__ import annotations

import html
import io
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st

from data_sources import get_kis_access_token


MASTER_URLS = {
    "KOSPI": "https://new.real.download.dws.co.kr/common/master/kospi_code.mst.zip",
    "KOSDAQ": "https://new.real.download.dws.co.kr/common/master/kosdaq_code.mst.zip",
}

# KIS 공식 종목 마스터 파일의 고정폭 정의.
KOSPI_WIDTHS = [2,1,4,4,4,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,9,5,5,1,1,1,2,1,1,1,2,2,2,3,1,3,12,12,8,15,21,2,7,1,1,1,1,1,9,9,9,5,9,8,9,3,1,1,1]
KOSPI_COLS = ['그룹코드','시가총액규모','지수업종대분류','지수업종중분류','지수업종소분류','제조업','저유동성','지배구조지수종목','KOSPI200섹터업종','KOSPI100','KOSPI50','KRX','ETP','ELW발행','KRX100','KRX자동차','KRX반도체','KRX바이오','KRX은행','SPAC','KRX에너지화학','KRX철강','단기과열','KRX미디어통신','KRX건설','Non1','KRX증권','KRX선박','KRX섹터_보험','KRX섹터_운송','SRI','기준가','매매수량단위','시간외수량단위','거래정지','정리매매','관리종목','시장경고','경고예고','불성실공시','우회상장','락구분','액면변경','증자구분','증거금비율','신용가능','신용기간','전일거래량','액면가','상장일자','상장주수','자본금','결산월','공모가','우선주','공매도과열','이상급등','KRX300','KOSPI','매출액','영업이익','경상이익','당기순이익','ROE','기준년월','시가총액','그룹사코드','회사신용한도초과','담보대출가능','대주가능']
KOSDAQ_WIDTHS = [2,1,4,4,4,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,9,5,5,1,1,1,2,1,1,1,2,2,2,3,1,3,12,12,8,15,21,2,7,1,1,1,1,9,9,9,5,9,8,9,3,1,1,1]
KOSDAQ_COLS = ['증권그룹구분코드','시가총액 규모 구분 코드 유가','지수업종 대분류 코드','지수 업종 중분류 코드','지수업종 소분류 코드','벤처기업 여부 (Y/N)','저유동성종목 여부','KRX 종목 여부','ETP 상품구분코드','KRX100 종목 여부 (Y/N)','KRX 자동차 여부','KRX 반도체 여부','KRX 바이오 여부','KRX 은행 여부','기업인수목적회사여부','KRX 에너지 화학 여부','KRX 철강 여부','단기과열종목구분코드','KRX 미디어 통신 여부','KRX 건설 여부','(코스닥)투자주의환기종목여부','KRX 증권 구분','KRX 선박 구분','KRX섹터지수 보험여부','KRX섹터지수 운송여부','KOSDAQ150지수여부 (Y,N)','주식 기준가','정규 시장 매매 수량 단위','시간외 시장 매매 수량 단위','거래정지 여부','정리매매 여부','관리 종목 여부','시장 경고 구분 코드','시장 경고위험 예고 여부','불성실 공시 여부','우회 상장 여부','락구분 코드','액면가 변경 구분 코드','증자 구분 코드','증거금 비율','신용주문 가능 여부','신용기간','전일 거래량','주식 액면가','주식 상장 일자','상장 주수(천)','자본금','결산 월','공모 가격','우선주 구분 코드','공매도과열종목여부','이상급등종목여부','KRX300 종목 여부 (Y/N)','매출액','영업이익','경상이익','단기순이익','ROE(자기자본이익률)','기준년월','전일기준 시가총액 (억)','그룹사 코드','회사신용한도초과여부','담보대출가능여부','대주가능여부']

@st.cache_data(ttl=21600, show_spinner=False)
def load_stock_master():
    """KIS 공식 KOSPI/KOSDAQ 마스터에서 종목명 + ROE + 전일거래량을 읽는다."""
    frames=[]
    for market,url in MASTER_URLS.items():
        r=requests.get(url,timeout=20); r.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            mst_name=next(n for n in zf.namelist() if n.lower().endswith('.mst'))
            text=zf.read(mst_name).decode('cp949',errors='replace')
        suffix_len=228 if market=='KOSPI' else 222
        widths=KOSPI_WIDTHS if market=='KOSPI' else KOSDAQ_WIDTHS
        cols=KOSPI_COLS if market=='KOSPI' else KOSDAQ_COLS
        items=[]; suffixes=[]
        for row in text.splitlines():
            if len(row)<=suffix_len: continue
            prefix=row[:-suffix_len]; suffix=row[-suffix_len:]
            short_code=prefix[:9].strip(); std_code=prefix[9:21].strip(); stock_name=prefix[21:].strip()
            code=short_code[-6:] if len(short_code)>=6 else short_code.zfill(6)
            if len(code)==6 and code.isdigit() and stock_name:
                items.append({'code':code,'name':stock_name,'market':market,'std_code':std_code})
                suffixes.append(suffix)
        if not items: continue
        meta=pd.read_fwf(io.StringIO('\n'.join(suffixes)),widths=widths,names=cols,dtype=str)
        base=pd.DataFrame(items).reset_index(drop=True)
        if market=='KOSPI':
            base['roe']=pd.to_numeric(meta['ROE'],errors='coerce')
            base['prev_volume']=pd.to_numeric(meta['전일거래량'],errors='coerce')
            base['master_cap']=pd.to_numeric(meta['시가총액'],errors='coerce')
        else:
            base['roe']=pd.to_numeric(meta['ROE(자기자본이익률)'],errors='coerce')
            base['prev_volume']=pd.to_numeric(meta['전일 거래량'],errors='coerce')
            base['master_cap']=pd.to_numeric(meta['전일기준 시가총액 (억)'],errors='coerce')
        frames.append(base)
    if not frames:
        return pd.DataFrame(columns=['code','name','market','std_code','roe','prev_volume','master_cap'])
    master=pd.concat(frames,ignore_index=True)
    return master.drop_duplicates(subset=['code','market']).sort_values(['name','code']).reset_index(drop=True)

@st.cache_data(ttl=3600, show_spinner=False)
def naver_fundamental_2025_2028(code):
    """Naver/WiseReport Financial Summary annual data for 2025~2028.

    Flow:
      1) Open WiseReport v2 company overview page for the selected code.
      2) Extract the fresh encparam/id generated for that company page.
      3) Call cF1001.aspx AJAX Financial Summary.
      4) Extract Operating profit (reported basis preferred), EPS, PER and ROE.

    This is a public-web HTML integration, not an official Open API. If the provider
    changes the HTML/AJAX contract this parser may need an update.
    """
    code = str(code).zfill(6)
    base = "https://navercomp.wisereport.co.kr/v2"
    parent_url = f"{base}/company/c1010001.aspx"
    ajax_url = f"{base}/company/ajax/cF1001.aspx"

    sess = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.7,en;q=0.5",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    parent = sess.get(parent_url, params={"cmp_cd": code, "cn": ""}, headers=headers, timeout=20)
    parent.raise_for_status()
    parent.encoding = parent.apparent_encoding or "utf-8"
    html = parent.text

    # WiseReport creates these values on the parent page. Do not hard-code them.
    enc_patterns = [
        r"encparam\s*:\s*['\"]([^'\"]+)['\"]",
        r"encparam\s*=\s*['\"]([^'\"]+)['\"]",
        r"['\"]encparam['\"]\s*:\s*['\"]([^'\"]+)['\"]",
    ]
    id_patterns = [
        r"\bid\s*:\s*['\"]([A-Za-z0-9+/=_-]+)['\"]",
        r"\bid\s*=\s*['\"]([A-Za-z0-9+/=_-]+)['\"]",
        r"['\"]id['\"]\s*:\s*['\"]([A-Za-z0-9+/=_-]+)['\"]",
    ]
    def first_match(patterns, text):
        for pat in patterns:
            m = re.search(pat, text, re.I)
            if m:
                return m.group(1)
        return None

    encparam = first_match(enc_patterns, html)
    encid = first_match(id_patterns, html)
    if not encparam or not encid:
        raise RuntimeError("WiseReport 종목별 인증 파라미터(encparam/id)를 찾지 못했습니다.")

    ajax_headers = {
        **headers,
        "Referer": parent.url,
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "text/html, */*; q=0.01",
    }

    def clean(x):
        return re.sub(r"\s+", " ", str(x).replace("\xa0", " ")).strip()

    def flatten_col(col):
        if isinstance(col, tuple):
            parts=[]
            for x in col:
                z=clean(x)
                if z and not z.lower().startswith("unnamed") and z not in parts:
                    parts.append(z)
            return " ".join(parts)
        return clean(col)

    def fetch_summary(freq_typ):
        params = {
            "cmp_cd": code,
            "fin_typ": "0",       # 주재무제표
            "freq_typ": freq_typ, # Y=annual; A is fallback for some layouts
            "encparam": encparam,
            "id": encid,
        }
        rr = sess.get(ajax_url, params=params, headers=ajax_headers, timeout=20)
        rr.raise_for_status()
        rr.encoding = rr.apparent_encoding or "utf-8"
        if len(rr.text.strip()) < 100:
            raise RuntimeError(f"Financial Summary 응답이 비어 있습니다. (freq={freq_typ})")
        try:
            tabs = pd.read_html(io.StringIO(rr.text))
        except Exception as e:
            raise RuntimeError(f"Financial Summary HTML 파싱 실패 (freq={freq_typ}): {e}")
        return tabs

    tables=[]
    errors=[]
    for freq in ("Y", "A"):
        try:
            tables.extend(fetch_summary(freq))
            if tables:
                break
        except Exception as e:
            errors.append(str(e))
    if not tables:
        raise RuntimeError("Financial Summary AJAX 조회 실패: " + " / ".join(errors[-2:]))

    # Pick the table containing the four target metrics and annual year headers.
    candidates=[]
    for t in tables:
        if t is None or t.empty:
            continue
        d=t.copy()
        d.columns=[flatten_col(c) for c in d.columns]
        blob=(" ".join(d.columns)+" "+" ".join(clean(x) for x in d.astype(str).values.ravel()[:5000])).upper()
        metric_score=sum(k in blob for k in ["영업이익","EPS","PER","ROE"])
        year_score=sum(str(y) in blob for y in [2025,2026,2027,2028])
        candidates.append((metric_score*10+year_score,d))
    candidates.sort(key=lambda x:x[0], reverse=True)
    if not candidates or candidates[0][0] < 30:
        raise RuntimeError("Financial Summary 표에서 영업이익/EPS/PER/ROE를 찾지 못했습니다.")
    d=candidates[0][1]

    # Identify year columns from the flattened MultiIndex header.  A header such as
    # '연간 2026/12(E) (IFRS연결)' maps to 2026.
    year_cols={}
    for c in d.columns:
        m=re.search(r"(2025|2026|2027|2028)\s*[/.-]?\s*\d{0,2}", clean(c))
        if m:
            year_cols[int(m.group(1))]=c
    # Some pandas versions keep the period labels in the first data row.
    if len(year_cols)<2:
        for ridx in range(min(3,len(d))):
            for c in d.columns:
                m=re.search(r"(2025|2026|2027|2028)\s*[/.-]?\s*\d{0,2}", clean(d.iloc[ridx][c]))
                if m:
                    year_cols[int(m.group(1))]=c
    if not year_cols:
        raise RuntimeError("Financial Summary에서 2025~2028 연간 열을 찾지 못했습니다.")

    # The first column is normally 주요재무정보.  Search every cell in the first
    # few columns so minor layout changes do not break the row lookup.
    search_cols=list(d.columns)[:min(3,len(d.columns))]
    row_labels=[]
    for idx,row in d.iterrows():
        label=" ".join(clean(row[c]) for c in search_cols)
        row_labels.append((idx,label))

    def find_metric_row(metric):
        normalized=[(idx,re.sub(r"\s+","",lab).upper()) for idx,lab in row_labels]
        if metric=="영업이익":
            # Naver Financial Summary shows a separate 발표기준 row when consensus exists.
            for idx,lab in normalized:
                if "영업이익(발표기준)" in lab:
                    return idx
            for idx,lab in normalized:
                if "영업이익" in lab and "영업이익률" not in lab:
                    return idx
        targets={"EPS":["EPS(원)","EPS"],"PER":["PER(배)","PER"],"ROE":["ROE(%)","ROE"]}[metric]
        for target in targets:
            z=target.replace(" ","").upper()
            for idx,lab in normalized:
                if z in lab:
                    return idx
        return None

    rows={m:find_metric_row(m) for m in ["영업이익","EPS","PER","ROE"]}
    if rows["영업이익"] is None or rows["EPS"] is None:
        raise RuntimeError("Financial Summary에서 영업이익 또는 EPS 행을 찾지 못했습니다.")

    def parse_num(v):
        z=clean(v).replace(",","").replace("원","").replace("배","").replace("%","")
        z=z.replace("−","-")
        if z.lower() in ("","-","--","nan","none","n/a"):
            return float("nan")
        neg=z.startswith("(") and z.endswith(")")
        z=z.strip("()")
        # Keep only a normal signed decimal number; footnote text is discarded.
        m=re.search(r"[-+]?\d+(?:\.\d+)?",z)
        if not m:
            return float("nan")
        val=float(m.group(0))
        return -abs(val) if neg else val

    out=[]
    for year in [2025,2026,2027,2028]:
        col=year_cols.get(year)
        rec={"연도":year,"구분":"A" if year==2025 else "E"}
        for metric,ridx in rows.items():
            rec[metric]=parse_num(d.loc[ridx,col]) if col is not None and ridx is not None else float("nan")
        out.append(rec)
    result=pd.DataFrame(out)
    if result[["영업이익","EPS","PER","ROE"]].isna().all().all():
        raise RuntimeError("2025~2028 Financial Summary 값이 모두 비어 있습니다.")
    return result

def earnings_momentum(df):
    """2025A~2028E 영업이익/EPS/PER/ROE 흐름을 정량 요약한다.

    반환: (라벨, 점수, 근거문구)
    - 영업이익/EPS 성장 방향을 가장 크게 반영
    - ROE 개선은 보조 가점/감점
    - PER은 이익/EPS가 성장하는 상황에서 부담 완화 여부만 보조 반영
    """
    if df is None or df.empty:
        return "⚪ 데이터부족", 0, "재무 컨센서스 데이터 없음"
    x=df.copy().sort_values('연도')
    for c in ['영업이익','EPS','PER','ROE']:
        x[c]=pd.to_numeric(x[c],errors='coerce')

    score=0
    reasons=[]

    def direction(col, weight_up, weight_down, label):
        nonlocal score
        v=x[col].dropna()
        if len(v)<2: return None
        first,last=float(v.iloc[0]),float(v.iloc[-1])
        if first == 0: return None
        chg=(last-first)/abs(first)*100
        # 작은 변동은 중립 처리
        if chg >= 5:
            score += weight_up
            reasons.append(f"{label} 증가")
            return 'up'
        if chg <= -5:
            score -= weight_down
            reasons.append(f"{label} 감소")
            return 'down'
        reasons.append(f"{label} 보합")
        return 'flat'

    op_dir=direction('영업이익',2,2,'영업이익')
    eps_dir=direction('EPS',2,2,'EPS')
    roe_dir=direction('ROE',1,1,'ROE')

    per=x['PER'].dropna()
    if len(per)>=2 and op_dir=='up' and eps_dir=='up':
        p0,p1=float(per.iloc[0]),float(per.iloc[-1])
        if p0>0 and p1>0:
            if p1 <= p0*0.95:
                score += 1
                reasons.append('Forward PER 부담 완화')
            elif p1 >= p0*1.15:
                score -= 1
                reasons.append('Forward PER 상승')

    # 핵심 이익지표가 서로 반대면 과도한 분류를 피한다.
    if op_dir=='up' and eps_dir=='down': score=min(score,1)
    if op_dir=='down' and eps_dir=='up': score=max(score,-1)

    if score >= 3:
        label='📈 실적개선'
    elif score <= -3:
        label='📉 실적둔화'
    else:
        label='➡️ 중립'
    return label, score, ' · '.join(reasons) if reasons else '판단 데이터 부족'

def _parse_turnover(raw):
    try:
        value = float(str(raw or "").replace(",", ""))
        return value if pd.notna(value) and value > 0 else None
    except (ValueError, TypeError):
        return None


def _fetch_kis_turnover(code, app_key, app_secret, token):
    """KIS official stock quote (not an order endpoint)."""
    try:
        response = requests.get(
            "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-price",
            params={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": str(code).zfill(6),
            },
            headers={
                "authorization": f"Bearer {token}",
                "appkey": app_key,
                "appsecret": app_secret,
                "tr_id": "FHKST01010100",
                "custtype": "P",
            },
            timeout=(4, 11),
        )
        response.raise_for_status()
        payload = response.json()
        if str(payload.get("rt_cd", "")) != "0":
            return None
        return _parse_turnover((payload.get("output") or {}).get("acml_tr_pbmn"))
    except (requests.RequestException, ValueError, TypeError, KeyError):
        return None


@st.cache_data(ttl=21600, show_spinner=False)
def auto_earnings_top5(candidate_records):
    """Six-hour snapshot, using the same 40 -> 20 -> 5 screening logic."""
    try:
        key = str(st.secrets.get("KIS_APP_KEY") or "")
        secret = str(st.secrets.get("KIS_APP_SECRET") or "")
    except Exception:
        return [], "KIS 인증정보를 읽을 수 없습니다."
    if not key or not secret:
        return [], "KIS_APP_KEY / KIS_APP_SECRET 미등록"
    token = get_kis_access_token(key, secret)
    if not token:
        return [], "KIS 인증 토큰을 확인하지 못했습니다."

    liquid = []
    # Modest concurrency avoids 40 sequential waits on cold start.
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {
            pool.submit(_fetch_kis_turnover, code, key, secret, token):
            (code, name, market, master_cap)
            for code, name, market, master_cap in candidate_records[:40]
        }
        for future in as_completed(futures):
            try:
                turnover = future.result()
            except Exception:
                continue
            if turnover is None:
                continue
            code, name, market, master_cap = futures[future]
            liquid.append({
                "code": str(code).zfill(6),
                "name": str(name),
                "market": str(market),
                "master_cap": float(master_cap) if pd.notna(master_cap) else 0.0,
                "turnover": turnover,
            })
    liquid = sorted(liquid, key=lambda row: row["turnover"], reverse=True)[:20]
    if not liquid:
        return [], "KIS 거래대금 시세를 수신하지 못했습니다."

    def analyze(record):
        try:
            financial = naver_fundamental_2025_2028(record["code"])
            label, score, reason = earnings_momentum(financial)
            if label != "📈 실적개선":
                return None
            y2028 = financial.loc[financial["연도"] == 2028]
            eps28 = float(y2028["EPS"].iloc[0]) if (
                not y2028.empty and pd.notna(y2028["EPS"].iloc[0])
            ) else None
            result = dict(record)
            result.update({
                "signal": label,
                "score": int(score),
                "reason": reason,
                "eps_2028": eps28,
            })
            return result
        except Exception:
            return None

    results = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(analyze, record) for record in liquid]
        for future in as_completed(futures):
            result = future.result()
            if result is not None:
                results.append(result)
    results.sort(
        key=lambda row: (row["score"], row["turnover"], row["master_cap"]),
        reverse=True,
    )
    if not results:
        return [], "조회된 20개 거래대금 후보 중 실적개선 조건 통과 종목이 없습니다."
    return results[:5], ""


def _earnings_candidates():
    """Source-derived top 40 KIS master names by reported market cap."""
    master = load_stock_master()
    if master is None or master.empty or "master_cap" not in master.columns:
        return ()
    frame = master.copy()
    frame["master_cap"] = pd.to_numeric(frame["master_cap"], errors="coerce")
    frame = (
        frame.dropna(subset=["master_cap"])
        .loc[lambda x: x["master_cap"] > 0]
        .sort_values("master_cap", ascending=False)
        .head(40)
    )
    return tuple(
        (str(row.code).zfill(6), str(row.name), str(row.market),
         float(row.master_cap))
        for row in frame.itertuples(index=False)
    )


def earnings_top_panel_html(rows):
    if not rows:
        body=(
            '<div style="color:#60766E;font-size:12px;line-height:1.45;">'
            '실적개선 종목을 계산하지 못했거나 컨센서스가 부족합니다.</div>'
        )
    else:
        medals=["🥇","🥈","🥉","4","5"]
        parts=[]
        for i,r in enumerate(rows[:5]):
            parts.append(
                f'<div style="display:flex;justify-content:space-between;gap:6px;padding:4px 0;'
                f'border-bottom:1px solid #E0EBE6;">'
                f'<span style="color:#29483D;font-weight:750;">{medals[i]}&nbsp; {html.escape(str(r["name"]))}</span>'
                f'<span style="color:#D73749;font-weight:900;">+{r["score"]}점</span></div>'
            )
        body=''.join(parts)
    return (
        '<div style="background:#FFFFFF;border:1px solid #C8DBD3;border-radius:6px;'
        'padding:9px 10px;margin:8px 0 6px 0;">'
        '<div style="color:#007B69;font-size:15px;font-weight:900;margin-bottom:4px;">📈 실적개선 TOP 5</div>'
        + body +
        '<div style="color:#687E74;font-size:10px;margin-top:6px;">'
        '기준: 2025A→2028E · 시총 40→거래대금 20 · 6시간 캐시</div></div>'
    )

@st.cache_data(ttl=60, show_spinner=False)
def public_market_quote(symbol):
    """공개 시세 endpoint에서 최근 두 종가를 읽어 지수/환율과 등락률을 계산한다."""
    url=f"https://query1.finance.yahoo.com/v8/finance/chart/{requests.utils.quote(symbol, safe='')}"
    r=requests.get(
        url,
        params={"range":"5d","interval":"1d","includePrePost":"false","events":"div,splits"},
        headers={"User-Agent":"Mozilla/5.0"},
        timeout=10
    )
    r.raise_for_status()
    result=r.json().get("chart",{}).get("result") or []
    if not result: raise RuntimeError("시세 응답 없음")
    node=result[0]
    closes=((node.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    closes=[float(x) for x in closes if x is not None]
    if not closes: raise RuntimeError("종가 데이터 없음")
    cur=closes[-1]; prev=closes[-2] if len(closes)>=2 else None
    rate=((cur-prev)/prev*100) if prev not in (None,0) else None
    return cur,rate

def market_panel_html(items):
    # The FX rate is context, not a stock-market breadth indicator.
    valid_rates=[r for label,_,r in items if r is not None and label!="USD/KRW"]
    avg=sum(valid_rates)/len(valid_rates) if valid_rates else 0
    mood="🟢 강세" if avg>=0.5 else ("🔴 약세" if avg<=-0.5 else "⚪ 중립")
    rows=[]
    for label,value,rate in items:
        if value is None:
            value_txt="-"; rate_txt="-"; color="#536F64"
        else:
            value_txt=f"{value:,.2f}"
            rate_txt="-" if rate is None else f"{rate:+.2f}%"
            color="#536F64" if rate is None else ("#D9364B" if rate>0 else ("#2466C9" if rate<0 else "#29483D"))
        rows.append(
            f'<div style="display:flex;justify-content:space-between;gap:8px;padding:3px 0;border-bottom:1px solid #E0EBE6;">'
            f'<span style="color:#29483D;font-weight:700;">{label}</span>'
            f'<span><b style="color:#203D35;">{value_txt}</b>&nbsp;&nbsp;<b style="color:{color};">{rate_txt}</b></span></div>'
        )
    return (
        '<div style="background:#FFFFFF;border:1px solid #008878;border-radius:6px;padding:9px 10px;margin:4px 0 8px 0;">'
        '<div style="color:#007B69;font-size:15px;font-weight:900;margin-bottom:5px;">📊 오늘의 시장</div>'
        + ''.join(rows) +
        f'<div style="display:flex;justify-content:space-between;padding-top:7px;">'
        f'<span style="color:#536F64;font-weight:700;">시장 분위기</span>'
        f'<span style="color:#203D35;font-weight:900;">{mood}</span></div></div>'
    )

def render_trading_sidebar():
    """Render only after the parent page has already passed its login gate."""
    with st.sidebar:
        market_symbols = [
            ("KOSPI", "^KS11"),
            ("KOSDAQ", "^KQ11"),
            ("NASDAQ", "^IXIC"),
            ("DOW", "^DJI"),
            ("USD/KRW", "KRW=X"),
        ]
        items = []
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = {
                pool.submit(public_market_quote, symbol): label
                for label, symbol in market_symbols
            }
            received = {}
            for future in as_completed(futures):
                label = futures[future]
                try:
                    received[label] = future.result()
                except Exception:
                    received[label] = (None, None)
        for label, _ in market_symbols:
            value, change = received.get(label, (None, None))
            items.append((label, value, change))
        st.markdown(market_panel_html(items), unsafe_allow_html=True)
        if st.button(
            "🔄 오늘의 시장 새로고침",
            use_container_width=True,
            key="stock_sidebar_market_refresh",
        ):
            public_market_quote.clear()
            st.rerun()
        st.caption("Yahoo Finance 일별 시세 · 지연 가능 · 1분 캐시 · 조회시각은 체결시각 아님")

        st.divider()
        try:
            candidates = _earnings_candidates()
            if not candidates:
                ranked, error = [], "KIS 종목마스터의 시가총액 후보를 확인하지 못했습니다."
            else:
                with st.spinner("실적개선 TOP 5 데이터 조회 중..."):
                    ranked, error = auto_earnings_top5(candidates)
        except Exception as exc:
            ranked, error = [], f"실적 데이터 연결 실패 ({type(exc).__name__})"
        st.markdown(earnings_top_panel_html(ranked), unsafe_allow_html=True)
        if error:
            st.caption("조회 참고: " + error)
        st.caption("KIS 종목마스터 상위 40 → 거래대금 상위 20 → WiseReport 실적개선 점수 TOP 5 · 6시간 캐시")
        if st.button(
            "🔄 실적 TOP 새로고침",
            use_container_width=True,
            key="stock_sidebar_earnings_refresh",
        ):
            auto_earnings_top5.clear()
            naver_fundamental_2025_2028.clear()
            st.rerun()
        st.caption("컨센서스는 전망치이며 변경될 수 있습니다. 종목 5개 미만이면 조건 충족 종목만 표시합니다.")
