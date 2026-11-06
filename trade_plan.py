"""Data-evidenced, conditional investor discussion prompts.

These are illustrative risk-review scenarios, not recommendations to trade,
not customized for an individual's investment objectives or risk tolerance.
Any numeric levels come only from actual observed closing prices.
"""
from __future__ import annotations

from math import isfinite
import pandas as pd


def _num(v):
    try:
        n=float(v)
        return n if isfinite(n) else None
    except (TypeError,ValueError,OverflowError):
        return None


def price_context(prices, current_price=None):
    result={"ma20":None,"ma60":None,"high20":None,"low20":None,
            "high60":None,"low60":None,"close":None,"asof":None,"observations":0}
    if not isinstance(prices,pd.DataFrame) or prices.empty or "Close" not in prices:
        return result
    d=prices.copy().sort_index()
    d["Close"]=pd.to_numeric(d["Close"],errors="coerce")
    d=d[d["Close"]>0].dropna(subset=["Close"])
    if d.empty:
        return result
    x=d["Close"]
    result["close"]=round(float(x.iloc[-1]),2)
    try:result["asof"]=pd.Timestamp(d.index[-1]).strftime("%Y-%m-%d")
    except (ValueError,TypeError):pass
    result["observations"]=len(x)
    for period in (20,60):
        if len(x)>=period:
            subset=x.iloc[-period:]
            result[f"ma{period}"]=round(float(subset.mean()),2)
            result[f"high{period}"]=round(float(subset.max()),2)
            result[f"low{period}"]=round(float(subset.min()),2)
    # Use the last official closing price for technical signals; a fresh KIS
    # price may be from a different session and should not be silently mixed.
    return result


def conditional_trade_plan(scores, prices=None, target_summary=None, published_target=None):
    """Separate review logic for current holders and potential new buyers."""
    scores=scores or {}
    technical=price_context(prices)
    rows={str(r.get("category")):r for r in scores.get("rows",[])}
    coverage=_num(scores.get("coverage")) or 0
    close=technical["close"]
    ma20=technical["ma20"]
    ma60=technical["ma60"]
    trow=rows.get("주가 추세",{})
    frow=rows.get("수급",{})
    vrow=rows.get("밸류에이션",{})
    hrow=rows.get("재무건전성",{})
    momentum=rows.get("뉴스 모멘텀",{})
    holder=[]
    newbuyer=[]
    checks=[]

    if close is not None and ma20 is not None and ma60 is not None:
        if close<ma20 and close<ma60:
            holder.append(
                f"종가 {close:,.0f}원이 20일선 {ma20:,.0f}원과 60일선 "
                f"{ma60:,.0f}원을 모두 밑돕니다. 반등 시 이평선 회복 여부와 "
                "변동성 확대를 점검하고 보유 비중·손실허용범위를 재확인하세요."
            )
            newbuyer.append(
                f"단기·중기 이동평균선 아래에 있습니다. 즉시 진입 여부를 단정하기보다 "
                f"20일선({ma20:,.0f}원) 회복과 거래대금 동반 여부를 관찰하는 조건부 시나리오를 고려하세요."
            )
        elif close>=ma20 and close>=ma60:
            holder.append(
                f"종가 {close:,.0f}원이 20일선·60일선 위에 있습니다. "
                "추세 유지 여부와 실적 전망 변화를 함께 보되, 수익 실현·리밸런싱은 "
                "계좌 비중과 투자기간을 기준으로 검토하세요."
            )
            newbuyer.append(
                f"현재 종가가 20일선({ma20:,.0f}원) 및 60일선({ma60:,.0f}원) 위에 있습니다. "
                "단기 급등 추격보다는 조정 시 지지 여부와 거래대금·실적 근거를 함께 확인하세요."
            )
        else:
            holder.append(
                f"종가 {close:,.0f}원이 20일선 {ma20:,.0f}원과 "
                f"60일선 {ma60:,.0f}원 사이에 있습니다. 이평선 방향·이탈 여부를 모니터링하세요."
            )
            newbuyer.append(
                "20일선과 60일선이 엇갈린 혼조 구간입니다. "
                "추세가 명확해지고 수급·실적 근거가 확인될 때까지 진입 근거를 점검하세요."
            )
        checks.append(f"기술적: 종가 기준 {technical['asof']} · 20일선 {ma20:,.0f}원 / 60일선 {ma60:,.0f}원")
    else:
        holder.append("유효한 20·60거래일 가격 자료가 없어 기술적 기준선을 산출하지 않았습니다. 거래소 시세와 투자기간을 확인하세요.")
        newbuyer.append("20·60거래일 추세 데이터 미확보로 진입 가격을 제시할 수 없습니다. 데이터 확보 후 시나리오를 재평가하세요.")
        checks.append("기술적: 가격 이력 또는 이동평균선 미확보")

    if frow.get("score") is not None and (_num(frow.get("covered_weight")) or 0)>=9:
        flow_score=_num(frow["score"])
        if flow_score is not None and flow_score<40:
            holder.append("거래대금·시총 보정 수급점수가 낮습니다. 외국인·기관 순매도 지속 여부와 거래대금 확대를 추가 점검하세요.")
            newbuyer.append("최근 수급은 매수 우위 근거가 약합니다. 매도세 진정 및 순매수 전환 여부를 선행 확인하세요.")
        elif flow_score is not None and flow_score>=65:
            holder.append("규모 보정 수급이 비교적 양호하지만 추세 지속을 보장하지 않습니다. 순매수 강도 둔화를 추적하세요.")
            newbuyer.append("외국인·기관 매수 강도가 양호해도 단기 진입 신호는 아닙니다. 실적·가격 수준과 함께 평가하세요.")
    else:
        checks.append("수급: 거래대금 대비 순매수 강도 자료 충족 여부 확인 필요")

    if vrow.get("score") is not None and (_num(vrow.get("covered_weight")) or 0)>=10:
        val_score=_num(vrow.get("score"))
        if val_score is not None and val_score<40:
            holder.append("상대가치 점수가 낮습니다. 실적 상향이 주가에 선반영됐는지 경쟁사 PER 및 실적 추정 변화를 확인하세요.")
            newbuyer.append("현재 상대가치 부담이 관측됩니다. 목표가만 근거로 판단하지 말고 이익 전망과 업종 내 비교를 검증하세요.")
    else:
        checks.append("밸류에이션: 업종비교·과거 밴드·이익 자료의 누락 여부 확인")

    target_summary=target_summary or {}
    published_target=published_target or {}
    if target_summary.get("average") is not None:
        check=(f"최근 90일 증권사별 최신 목표가 {target_summary.get('count',0)}곳 평균 "
               f"{int(target_summary['average']):,}원")
        upside=_num(target_summary.get("upside_pct"))
        if upside is not None:check+=f" · 기준가 대비 {upside:+.1f}% (비보장)"
        checks.append(check)
        newbuyer.append("애널리스트 평균 목표가는 참고용 전망치이며 실현 가능 수익률이나 적정 매수 가격을 뜻하지 않습니다.")
    elif published_target.get("target") is not None:
        checks.append("Npay 제공 평균 목표가: 표본·집계기간 미확인, 앱의 최근 리포트 평균과 구분 필요")
    else:
        checks.append("최근 리포트 목표가: 비교 가능한 증권사 표본 부족으로 미산출")

    for key,label in ((hrow,"재무"),(momentum,"공시·뉴스")):
        weight=_num(key.get("weight")) or 0
        used=_num(key.get("covered_weight")) or 0
        if used<weight:checks.append(f"{label}: {used:g}/{weight:g}점 배점만 검증 · 미산출 근거 확인")
    checks.append("실적: 다음 분기 매출·영업이익 예상치 변경과 실제 확정 공시 확인")
    checks.append("보유전략: 매입단가·비중·투자목적·허용손실에 따라 달라지므로 고객 정보 확인 후 판단")

    if coverage<70:
        holder.insert(0,f"평가 가능 배점이 {coverage:g}%로 제한돼 강한 결론을 내리기 어렵습니다. 누락 자료와 출처부터 확인하세요.")
        newbuyer.insert(0,f"평가 가능 배점이 {coverage:g}%로 낮습니다. 자료 보완 전 매수 판단을 유보하고 근거를 점검하세요.")
    else:
        holder.insert(0,"기존 보유자: 보유기간·평단가·계좌 내 비중을 먼저 확인한 뒤 비중 조절·리밸런싱 여부를 검토하세요.")
        newbuyer.insert(0,"신규 검토자: 추격매수보다 기대수익·최대 허용손실·분할 진입 조건을 사전에 정의하세요.")

    return {
        "holder":holder[:4],"new_buyer":newbuyer[:4],"checkpoints":checks[:8],
        "technical":technical,"coverage":coverage,
        "disclaimer":("이 문구는 관측 데이터에 따른 조건부 상담 체크리스트이며 개인별 투자성향·"
                      "재산·경험을 반영한 매수·매도 추천이 아닙니다. 과거 수익률·이동평균·"
                      "증권사 목표주가가 미래 성과를 보장하지 않습니다.")
    }
