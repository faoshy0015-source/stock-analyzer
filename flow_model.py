"""Investor-flow scoring normalized to KRX stock turnover and market cap.

Data used:
- KRX daily institution/foreign *net trading values* (KRW)
- KRX daily stock turnover and listed-common-share market cap (KRW)
A Yahoo close*volume proxy is used only when official turnover is missing,
explicitly marked approximate. Missing context leaves subweights unassessed.
"""
from __future__ import annotations
from datetime import datetime, timedelta
from math import isfinite
from zoneinfo import ZoneInfo

import pandas as pd

FLOW_WEIGHTS = {
    "5거래일 거래대금 대비 순매수": 4,
    "20거래일 거래대금 대비 순매수": 5,
    "20거래일 시총 대비 순매수": 4,
    "10거래일 매수 지속성": 2,
}


def _finite(v):
    try:
        n = float(v)
        return n if isfinite(n) else None
    except (ValueError, TypeError, OverflowError):
        return None


def fetch_krx_turnover_context(code, days=125):
    """Get official daily common-share turnover/cap via pykrx (if permitted)."""
    if not (isinstance(code,str) and code.isascii() and code.isdigit() and len(code)==6):
        return pd.DataFrame(), "종목코드 오류"
    try:
        from pykrx import stock
        end=datetime.now(ZoneInfo("Asia/Seoul")).date()
        start=end-timedelta(days=int(days))
        table=stock.get_market_cap_by_date(start.strftime("%Y%m%d"),
                                           end.strftime("%Y%m%d"),code)
        if table is None or table.empty or not {"거래대금","시가총액"}<=set(table.columns):
            return pd.DataFrame(), "KRX 일별 거래대금·시가총액 응답 없음"
        table=table[["거래대금","시가총액"]].copy()
        table.index=pd.to_datetime(table.index,errors="coerce").tz_localize(None).normalize()
        table=table.loc[table.index.notna()]
        for col in table:
            table[col]=pd.to_numeric(table[col],errors="coerce")
        table=table.sort_index()
        table=table[(table["거래대금"]>0) & (table["시가총액"]>0)]
        return table, "" if not table.empty else "KRX 유효 거래대금·시가총액이 없습니다."
    except Exception as exc:
        return pd.DataFrame(), f"KRX 거래대금 조회 실패: {type(exc).__name__}"


def _daily_context(daily_krx, prices, price_cap):
    """Return normalized date-indexed turnover context and source labels."""
    if isinstance(daily_krx,pd.DataFrame) and not daily_krx.empty:
        data=daily_krx[["거래대금","시가총액"]].copy()
        src="KRX 공시 일별 거래대금·보통주 시총"
    elif isinstance(prices,pd.DataFrame) and not prices.empty and {"Close","Volume"}<=set(prices.columns):
        data=pd.DataFrame(index=prices.index)
        data["거래대금"]=(pd.to_numeric(prices["Close"],errors="coerce") *
                            pd.to_numeric(prices["Volume"],errors="coerce"))
        data["시가총액"]=_finite(price_cap)
        src="일별 종가×거래량 (거래대금 근사) · 공급처 시총"
    else:
        data=pd.DataFrame()
        src="거래대금 자료 없음"

    if not data.empty:
        data.index=pd.to_datetime(data.index,errors="coerce")
        data=data.loc[data.index.notna()].copy()
        if getattr(data.index,"tz",None) is not None:
            data.index=data.index.tz_localize(None)
        data.index=data.index.normalize()
        data=data[~data.index.duplicated(keep="last")].sort_index()
        data["거래대금"]=pd.to_numeric(data["거래대금"],errors="coerce")
        data["시가총액"]=pd.to_numeric(data["시가총액"],errors="coerce")
    return data,src


def _component(name,score,detail,source="",days=0):
    weight=FLOW_WEIGHTS[name]
    return {
        "name":name,"weight":weight,
        "covered_weight":weight if score is not None else 0,
        "score":round(score,1) if score is not None else None,
        "earned":round(score*weight/100,3) if score is not None else None,
        "status":"평가" if score is not None else "미산출",
        "evidence":detail,"source":source,"days":days,
    }


def _score_ratio(pct,percent_threshold):
    return round(max(0,min(100,50+50*pct/percent_threshold)),1)


def evaluate_flow_normalized(flow, daily_krx=None, prices=None, market_cap=None):
    """15pt scoring: turnover ratio(4+5), cap ratio(4), persistence(2).

    Compare foreign + institution net value only against the exact matched
    trading sessions. Never normalize raw KRW with an unaligned session.
    """
    data,context_source=_daily_context(daily_krx,prices,market_cap)
    components=[]
    f=pd.DataFrame()
    if isinstance(flow,pd.DataFrame) and not flow.empty and {"외국인","기관"}<=set(flow.columns):
        f=flow[["외국인","기관"]].copy()
        f.index=pd.to_datetime(f.index,errors="coerce")
        f=f.loc[f.index.notna()].copy()
        if getattr(f.index,"tz",None) is not None:
            f.index=f.index.tz_localize(None)
        f.index=f.index.normalize()
        f=f[~f.index.duplicated(keep="last")].sort_index()
        for col in ("외국인","기관"):
            f[col]=pd.to_numeric(f[col],errors="coerce")
        f=f.dropna(subset=["외국인","기관"])
        f["합산순매수"]=f["외국인"]+f["기관"]
    cap_market=_finite(market_cap)

    matched=pd.DataFrame()
    if not f.empty and not data.empty:
        matched=f.join(data[["거래대금","시가총액"]],how="left")
    period_metrics={}
    for period,label,threshold in (
        (5,"5거래일 거래대금 대비 순매수",10),
        (20,"20거래일 거래대금 대비 순매수",5),
    ):
        score=None
        source=context_source
        detail=f"최근 {period}거래일 수급·동일 날짜 거래대금 자료 필요"
        good=pd.DataFrame()
        if len(f)>=period and not matched.empty:
            chosen=matched.tail(period)
            good=chosen.loc[(chosen["거래대금"]>0) & chosen["합산순매수"].notna()]
            if len(good)>=int(period*.85+0.999):
                denominator=float(good["거래대금"].sum())
                net=float(good["합산순매수"].sum())
                if denominator>0:
                    pct=net/denominator*100
                    score=_score_ratio(pct,threshold)
                    period_metrics[period]={"net":net,"turnover":denominator,
                                            "pct":pct,"matched":len(good),
                                            "period":period}
                    detail=(f"{len(good)}/{period}거래일 매칭 · 순매수 {net/1e8:+,.0f}억원 / "
                            f"거래대금 {denominator/1e8:,.0f}억원 = {pct:+.2f}% "
                            f"(±{threshold:g}%에서 0/100점 포화)")
        components.append(_component(label,score,detail,source,len(good)))

    score=None
    detail="KRX 또는 공급처 시가총액과 최근 20일 동일날짜 수급 필요"
    if len(f)>=20 and not matched.empty:
        chosen=matched.tail(20)
        good=chosen.loc[(chosen["거래대금"]>0) & chosen["합산순매수"].notna()]
        if len(good)>=17:
            last=good.iloc[-1]
            cap=_finite(last.get("시가총액"))
            cap_src=context_source
            if cap is None:
                cap=cap_market
                cap_src="공급처 시가총액 (조회 시점·주식종류 차이 주의)"
            if cap and cap>0:
                net=float(good["합산순매수"].sum())
                pct=net/cap*100
                score=_score_ratio(pct,1)
                detail=(f"{len(good)}/20거래일 매칭 · 순매수 {net/1e8:+,.0f}억원 / "
                        f"시총 {cap/1e12:,.2f}조원 = {pct:+.3f}% (±1%에서 0/100점 포화)")
                context_for_cap=cap_src
            else:
                context_for_cap=context_source
        else:context_for_cap=context_source
    else:context_for_cap=context_source
    components.append(_component("20거래일 시총 대비 순매수",score,detail,context_for_cap))

    score=None
    detail="순매수 지속성 평가를 위해 최근 10거래일의 외국인·기관 수급 필요"
    if len(f)>=10:
        x=f["합산순매수"].tail(10)
        buy=int((x>0).sum())
        flat=int((x==0).sum())
        score=round((buy+0.5*flat)/10*100,1)
        detail=f"최근 10거래일 순매수 {buy}일 · 순매도 {int((x<0).sum())}일 · 중립 {flat}일"
    components.append(_component("10거래일 매수 지속성",score,detail,
                                 "KRX 투자자별 순매수",min(len(f),10)))

    used=sum(x["covered_weight"] for x in components)
    earned=sum(x["earned"] or 0 for x in components)
    return {
        "weight":15,
        "covered_weight":used,
        "score":round(100*earned/used,1) if used else None,
        "earned":round(earned,2),
        "components":components,
        "metrics":period_metrics,
        "confidence":("보통 · KRX 동일 날짜 수급·거래대금·시총 정규화" if used==15
                      else "낮음 · 사용 가능한 수급·거래대금 부분 평가" if used else "미산출"),
        "note":"외국인+기관 순매수 금액을 동일 날짜 종목 거래대금과 시가총액으로 나눈 상대강도입니다. 과거 수익률 예측지표가 아니며, 시총은 보통주 기준일 수 있습니다.",
    }
