"""Transparent, missing-aware rule-based scoring; not investment advice."""
from __future__ import annotations
import math
import re
import pandas as pd
from valuation_model import evaluate_valuation
from financial_health_model import evaluate_financial_health

WEIGHTS = {'실적·성장성':25,'밸류에이션':20,'수급':15,'재무건전성':20,'주가 추세':10,'뉴스 모멘텀':10}
GOOD_WORDS = ('수주','흑자전환','증익','상향','성장','신제품','수출 증가','계약 체결','자사주 소각','신고가','실적 개선','증설')
BAD_WORDS = ('적자전환','하향','감익','실적 악화','유상증자','횡령','배임','소송','상장폐지','리콜','과징금','자금난','매출 감소')


def number(v):
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except (ValueError,TypeError): return None


def clip(x,lo=0,hi=100): return max(lo,min(hi,float(x)))


def interp(x, low_bad, high_good):
    x=number(x)
    if x is None:return None
    if low_bad==high_good:return 50.0
    return clip((x-low_bad)*100/(high_good-low_bad))


def last_pair(df,key):
    if df is None or df.empty or key not in df:return None,None
    values=[number(x) for x in df[key]]
    values=[x for x in values if x is not None]
    return (values[-1] if values else None,values[-2] if len(values)>1 else None)


def pct_change(new,old):
    if number(new) is None or number(old) in (None,0): return None
    # Baseline <= 0 is not a meaningful conventional growth rate.
    if old<=0: return None
    return (new/old-1)*100


def get_indicators(prices):
    if prices is None or prices.empty or 'Close' not in prices:return {}
    close=pd.to_numeric(prices['Close'],errors='coerce').dropna()
    if close.empty:return {}
    delta=close.diff(); gains=delta.clip(lower=0); losses=-delta.clip(upper=0)
    avg_gain=gains.ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    avg_loss=losses.ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    rs=avg_gain/avg_loss.replace(0,float('nan'))
    rsi=(100-100/(1+rs)).iloc[-1] if len(rs)>0 else None
    if len(close)>=15 and avg_loss.iloc[-1]==0:
        rsi=100 if avg_gain.iloc[-1]>0 else 50
    def ma(n): return number(close.tail(n).mean()) if len(close)>=n else None
    fast=close.ewm(span=12,adjust=False).mean()
    slow=close.ewm(span=26,adjust=False).mean()
    macd=fast-slow
    sig=macd.ewm(span=9,adjust=False).mean()
    return {
      'last':number(close.iloc[-1]),'prev':number(close.iloc[-2]) if len(close)>1 else None,
      'ma20':ma(20),'ma60':ma(60),'ma120':ma(120),
      'rsi14':number(rsi),'macd':number(macd.iloc[-1]) if len(close)>=35 else None,
      'signal':number(sig.iloc[-1]) if len(close)>=35 else None,
      'high52':number(close.tail(252).max()) if len(close)>=30 else None,
      'low52':number(close.tail(252).min()) if len(close)>=30 else None,
      'return20':pct_change(close.iloc[-1],close.iloc[-21]) if len(close)>=21 else None,
      'return60':pct_change(close.iloc[-1],close.iloc[-61]) if len(close)>=61 else None,
      'volume20':number(pd.to_numeric(prices['Volume'],errors='coerce').tail(20).mean()) if 'Volume' in prices else None,
      'asof':str(close.index[-1].date()) if hasattr(close.index[-1],'date') else str(close.index[-1])
    }


def score_record(label,points,parts,comments,confidence='보통'):
    return {'category':label,'weight':WEIGHTS[label],
            'covered_weight':WEIGHTS[label] if parts else 0,
            'score':round(sum(s*w for s,w in parts)/sum(w for _,w in parts),1) if parts else None,
            'notes':comments,'confidence':confidence if parts else '미산출', 'tests':len(parts)}


def evaluate(prices, annual, quarterly, flow, news, profile):
    profile=profile or {}; indicators=get_indicators(prices)
    results=[]
    # PERFORMANCE
    tests=[]; notes=[]
    rev,prior=last_pair(annual,'revenue'); op,opprior=last_pair(annual,'operating_profit')
    growth=pct_change(rev,prior); opgrowth=pct_change(op,opprior)
    if growth is not None:
        tests.append((interp(growth,-20,30),2));notes.append(f'연간 매출 성장률 {growth:+.1f}%')
    if opgrowth is not None:
        tests.append((interp(opgrowth,-40,50),3));notes.append(f'연간 영업이익 성장률 {opgrowth:+.1f}%')
    if rev and op is not None:
        margin=op/rev*100
        tests.append((interp(margin,-5,25),2));notes.append(f'영업이익률 {margin:.1f}%')
    qop,qopprev=last_pair(quarterly,'operating_profit')
    if qop is not None and qopprev is not None:
        # QoQ is not YoY; avoid equating seasonal changes with growth.
        notes.append(f'최근 분기 영업이익 {qop/1e8:,.0f}억원 (직전 분기 {qopprev/1e8:,.0f}억원)')
    results.append(score_record('실적·성장성',0,tests,notes))
    # VALUATION: four weighted dimensions, each scored only with real data.
    valuation=evaluate_valuation(profile,profile.get('__valuation_context') or {},annual)
    val_notes=[valuation['note']]
    for part in valuation['components']:
        val_notes.append(f"{part['name']}: {part['status']} "
                         f"({part['covered_weight']:g}/{part['weight']}점) · {part['evidence']}")
    if profile.get('__valuation_approx'):
        val_notes.append('참고용 간이 PER/PBR: '+
                         str(profile.get('__valuation_approx_note') or '공식 PER/PBR 아님'))
    results.append({
        'category':'밸류에이션','weight':WEIGHTS['밸류에이션'],
        'covered_weight':valuation['covered_weight'],
        'score':valuation['score'],'notes':val_notes,
        'confidence':valuation['confidence'] if valuation['score'] is not None else '미산출',
        'tests':sum(1 for x in valuation['components'] if x['covered_weight']>0),
        'components':valuation['components'],
        'available_points':valuation['earned']
    })
    # FLOW
    tests=[];notes=[]
    if flow is not None and len(flow)>=5 and all(k in flow for k in ('외국인','기관')):
        for period,w in ((5,1),(20,2),(60,1)):
            part=flow.tail(period)
            if len(part)<period:continue
            net=float(part[['외국인','기관']].sum().sum())
            val=55 if net>0 else 45 if net<0 else 50
            tests.append((val,w));notes.append(f'최근 {period}거래일 외국인+기관 순매수 합계 {net/1e8:+,.0f}억원')
        streak=flow[['외국인','기관']].sum(axis=1).tail(10)
        if len(streak)>=5:
            positive=int((streak>0).sum());tests.append((positive/len(streak)*100,2))
            notes.append(f'최근 {len(streak)}거래일 합산 순매수일 {positive}일')
    results.append(score_record('수급',0,tests,notes,'보통 · 순매수 규모의 시총 보정 미반영'))
    # SOLVENCY: evaluate separate leverage, cash generation, interest cost,
    # and short-term liquidity evidence. Never award a full 20-weight for just
    # a single strong debt ratio or for bank capital based on industrial rules.
    fin=evaluate_financial_health(annual,profile.get('__financial_context') or {},profile)
    fin_notes=[fin['note']]
    for part in fin['components']:
        fin_notes.append(
            f"{part['name']}: {part['status']} "
            f"({part['covered_weight']:g}/{part['weight']}점) · {part['evidence']}"
        )
    results.append({
        'category':'재무건전성','weight':WEIGHTS['재무건전성'],
        'covered_weight':fin['covered_weight'],
        'score':fin['score'],'notes':fin_notes,
        'confidence':fin['confidence'],
        'tests':sum(1 for x in fin['components'] if x['covered_weight']>0),
        'components':fin['components'],
        'available_points':fin['earned']
    })
    # TECHNICAL
    tests=[];notes=[];last=indicators.get('last')
    ma20=indicators.get('ma20');ma60=indicators.get('ma60');ma120=indicators.get('ma120')
    if last and ma20:
        tests.append((75 if last>ma20 else 25,1));notes.append(f'종가가 20일선 {"위" if last>ma20 else "아래"}')
    if ma20 and ma60:
        tests.append((75 if ma20>ma60 else 25,2));notes.append(f'20일선이 60일선 {"위" if ma20>ma60 else "아래"}')
    if ma60 and ma120:
        tests.append((75 if ma60>ma120 else 25,1))
    if indicators.get('rsi14') is not None:
        rsi=indicators['rsi14'];tests.append((50 if rsi<30 or rsi>70 else 65,1))
        notes.append(f'RSI(14) {rsi:.1f} (극단 구간은 방향성 판단 주의)')
    results.append(score_record('주가 추세',0,tests,notes))
    # NEWS: keyword-only high uncertainty; deliberately not LLM sentiment
    tests=[];notes=[]
    if news is not None and not news.empty and 'title' in news:
        titles=[str(t) for t in news['title'].head(20)]
        pos=sum(bool(any(word in t for word in GOOD_WORDS)) for t in titles)
        neg=sum(bool(any(word in t for word in BAD_WORDS)) for t in titles)
        if pos+neg>0:
            tests.append((clip(50+30*(pos-neg)/max(pos+neg,3)),1))
            notes.append(f'최근 뉴스 제목 {len(titles)}건 중 긍정 키워드 {pos}건·부정 키워드 {neg}건 (문맥 이해 X)')
        else:
            notes.append(f'뉴스 {len(titles)}건 수집, 방향성 키워드 부족 → 점수 보류')
    results.append(score_record('뉴스 모멘텀',0,tests,notes,'낮음 · 제목 키워드만 판단'))

    available=[r for r in results if r['score'] is not None and r.get('covered_weight',0)>0]
    covered=round(sum(r['covered_weight'] for r in available),1)
    total=round(sum(r['score']*r['covered_weight'] for r in available)/covered,1) if covered else None
    label=('평가 불가' if total is None else '긍정적 관심' if total>=75 else '중립·관찰' if total>=55 else '주의·재점검')
    return {'rows':results,'total':total,'coverage':covered,'label':label,'indicators':indicators,
            'partial':covered<100,'available_count':len(available)}



def _scope_label(row):
    """Express rating relative to validated evidence, not full domain."""
    used=float(row.get('covered_weight') or 0)
    weight=float(row.get('weight') or 0)
    score=row.get('score')
    if score is None or weight<=0:
        return f"{row.get('category', '영역')} 미산출"
    if used < weight:
        return (f"{row['category']}(확인 {used:g}/{weight:g}점 배점 · "
                f"확인 지표 평균 {score:.1f}점)")
    return f"{row['category']}({score:.1f}점)"


def explain(result):
    """Conservative executive summary when scores are based on partial evidence."""
    usable=[r for r in result.get('rows',[]) if r.get('score') is not None]
    if not usable:
        return '평가에 필요한 기초 데이터가 부족합니다. 시세 및 재무 데이터 연결 상태를 확인하세요.'
    substantial=[r for r in usable
                 if (r.get('covered_weight') or 0)>=0.60*r['weight']]
    compared=substantial if substantial else usable
    best=max(compared,key=lambda r:r['score'])
    risk=min(compared,key=lambda r:r['score']) if len(compared)>1 else None
    coverage=result.get('coverage',0)
    total=result.get('total')
    msg=(f"검증 가능한 {coverage:g}/100점 배점을 재가중한 "
         f"{'잠정 ' if coverage < 100 else ''}종합 평가: {total:.1f}/100점. "
         f"상대적으로 점수가 높은 분야는 {_scope_label(best)}입니다.")
    if risk is not None:
        msg+=f" 확인이 필요한 분야는 {_scope_label(risk)}입니다."
    else:
        msg+=" 다른 분야는 충분히 비교할 자료가 부족합니다."
    missing=[f"{r['category']} {r['weight']-r.get('covered_weight',0):g}점"
             for r in result['rows']
             if r['weight']>r.get('covered_weight',0)]
    if missing:
        msg+=' 아직 확인되지 않은 배점: '+', '.join(missing)+'.'
    finance=next((r for r in result['rows'] if r['category']=='재무건전성'),None)
    if finance and 0 < finance.get('covered_weight',0) < finance['weight']:
        msg+=(f" 재무건전성 검증 {finance.get('covered_weight',0):g}/{finance['weight']:g}점 배점: "
              "확인된 세부 지표만의 평균이며, "
              "미확인된 재무 위험까지 안전하다고 판정한 것이 아닙니다.")
    if result.get('partial'):
        msg+=' 데이터 누락이 있어 다른 종목의 완전한 평가와 직접 비교하지 마세요.'
    return msg


def diagnostic_summary(result):
    """Short investment dashboard diagnosis with explicit partial scopes."""
    by_category={r['category']:r for r in result.get('rows',[])}
    rules=[
        ('실적·성장성', '실적', (65, 40), ('성장 양호','성장 둔화','혼조')),
        ('밸류에이션', '가격', (65, 40), ('상대가격 매력','가치평가 부담','중립권')),
        ('수급', '수급', (60, 40), ('매수 우위','매도 우위','혼조')),
        ('재무건전성', '재무', (70, 35), ('안정성 양호','위험 신호','확인 필요')),
        ('주가 추세', '추세', (65, 40), ('상승 우세','약세','혼조')),
    ]
    segments=[]
    for key,label,(strong,weak),(up,down,neutral) in rules:
        r=by_category.get(key) or {}
        score=r.get('score')
        weight=float(r.get('weight') or 0)
        used=float(r.get('covered_weight') or 0)
        if score is None or weight<=0 or used/weight<0.60:
            value='평가자료 제한'
        elif score>=strong:
            value=up
        elif score<weak:
            value=down
        else:
            value=neutral
        # "안정성 양호" on a partial 15/20 could imply complete
        # solvency: explicitly distinguish checked metrics from gaps.
        if value!='평가자료 제한' and used<weight:
            if key=='재무건전성':
                value=f"확인 지표 {value} ({used:g}/{weight:g}점 배점)"
            else:
                value=f"{value} ({used:g}/{weight:g}점 배점)"
        segments.append(f'{label}: {value}')
    return '  |  '.join(segments)
