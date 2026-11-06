"""Evidence-aware 20-point operating-company financial-health model.

Available subweights, not every unknown solvency metric, contribute to the
overall 100-point screen. Financial institutions are deferred to a separately
calibrated regulatory-capital model. This is NOT a credit-rating system.
"""
from __future__ import annotations

from math import isfinite

FINANCIAL_WEIGHTS = {
    "부채비율": 5,
    "영업현금흐름 전환율": 6,
    "이자보상배율": 5,
    "유동비율": 4,
}


def numeric(v):
    try:
        value=float(v)
        return value if isfinite(value) else None
    except (TypeError, ValueError, OverflowError):
        return None


def scale(value, bad, good):
    val=numeric(value)
    if val is None:
        return None
    return round(max(0.0, min(100.0, (val-bad) * 100/(good-bad))), 1)


def is_financial_company(profile):
    fields = " ".join(str((profile or {}).get(k, "")) for k in
                      ("industry", "sector", "__name__")).casefold()
    words = ("bank", "insurance", "financial services", "financial holding",
             "capital markets", "asset management", "은행", "보험", "증권",
             "금융지주", "금융", "카드", "캐피탈")
    return any(word in fields for word in words)


def _component(label, score, details, source="", withheld=""):
    weight = FINANCIAL_WEIGHTS[label]
    available = weight if score is not None else 0
    return {
        "name": label, "weight": weight, "covered_weight": available,
        "score": score if score is not None else None,
        "earned": round(score * weight / 100, 3) if score is not None else None,
        "status": "평가" if score is not None else "미산출",
        "evidence": details if score is not None else (withheld or details),
        "source": source,
    }


def _annual_latest(annual):
    if annual is None or annual.empty or "period" not in annual:
        return {}
    d=annual.copy()
    d["period"]=d["period"].astype(str)
    d=d[d["period"].str.fullmatch(r"20\d{2}")]
    if d.empty:
        return {}
    return d.sort_values("period").iloc[-1].to_dict()


def evaluate_financial_health(annual, context=None, profile=None):
    context=context or {}
    profile=profile or {}
    latest=_annual_latest(annual)
    result=[]
    if is_financial_company(profile):
        for name in FINANCIAL_WEIGHTS:
            result.append(_component(name,None,"금융업은 일반 제조업의 부채·유동비율 기준을 적용하지 않습니다.",
                                     "금융업 별도 건전성 지표 필요"))
        return {"weight":20, "covered_weight":0, "score":None, "earned":0,
                "components":result, "confidence":"미산출 · 금융업 전용 평가 미구현",
                "note":"은행·증권·보험 등의 규제자본비율, 유동성커버리지, 자산건전성을 별도로 평가해야 합니다."}

    period=str(latest.get("period") or "")
    valid_detail = (context.get("year") == period and
                   context.get("fs_scope") in ("CFS", "OFS"))
    # Context is only accepted from the SAME audited fiscal year. Incomplete
    # DART full-report responses leave these components unavailable.
    full = context if valid_detail else {}

    eq=numeric(latest.get("equity"))
    debt=numeric(latest.get("liabilities"))
    if eq is not None and eq > 0 and debt is not None and debt>=0:
        leverage=100*debt/eq
        debt_score=scale(leverage,260,35)
        leverage_note=f"{period}년 부채비율 {leverage:.1f}%"
    elif eq is not None and eq<=0 and debt is not None and debt>=0:
        debt_score=0.0
        leverage_note=f"{period}년 자본총계가 0 이하: 심각한 재무위험"
    else:
        debt_score=None
        leverage_note="자본·부채 원자료가 누락되었습니다."
    result.append(_component("부채비율",debt_score,leverage_note,
                             "DART 연간 재무제표"))

    operating_profit=numeric(latest.get("operating_profit"))
    cash_flow=numeric(full.get("operating_cash_flow"))
    if cash_flow is not None and operating_profit is not None and operating_profit>0:
        conversion=cash_flow/operating_profit
        cash_score=scale(conversion,0,1.3)
        cash_note=f"{period}년 영업현금흐름/영업이익 {conversion:.2f}배"
    elif cash_flow is not None and operating_profit is not None and operating_profit<=0 and cash_flow<0:
        cash_score=0.0
        cash_note=f"{period}년 영업이익·영업현금흐름 모두 적자"
    else:
        cash_score=None
        cash_note="DART 연간 전체 재무제표의 영업현금흐름 및 흑자 영업이익이 필요합니다."
    result.append(_component("영업현금흐름 전환율",cash_score,cash_note,
                             "DART 연간 전체 재무제표 (CF)"))

    interest=numeric(full.get("interest_expense"))
    if interest is not None and interest > 0 and operating_profit is not None:
        coverage=operating_profit/interest
        interest_score=scale(coverage,1,8)
        interest_note=f"{period}년 영업이익/이자비용 {coverage:.2f}배"
    else:
        interest_score=None
        interest_note=("영업이익 또는 '이자비용'이 확인되지 않았습니다. "
                       "전체 금융비용을 이자비용으로 대신하지 않습니다.")
    result.append(_component("이자보상배율",interest_score,interest_note,
                             "DART 연간 전체 재무제표 (손익계산서)"))

    current_assets=numeric(full.get("current_assets"))
    current_liabilities=numeric(full.get("current_liabilities"))
    if (current_assets is not None and current_assets>=0 and
            current_liabilities is not None and current_liabilities>0):
        current_ratio=current_assets/current_liabilities
        liquidity_score=scale(current_ratio,0.7,2.0)
        liquidity_note=f"{period}년 유동비율 {current_ratio*100:.1f}%"
    else:
        liquidity_score=None
        liquidity_note="동일 연도 유동자산·유동부채가 필요합니다."
    result.append(_component("유동비율",liquidity_score,liquidity_note,
                             "DART 연간 전체 재무제표 (BS)"))

    covered=sum(r["covered_weight"] for r in result)
    earned=sum(r["earned"] or 0 for r in result)
    return {
        "weight":20,
        "covered_weight":covered,
        "score":round(100*earned/covered,1) if covered else None,
        "earned":round(earned,2),
        "components":result,
        "confidence":("보통 · 전체 4개 지표 확인" if covered==20
                      else "낮음 · 확인된 건전성 지표만 부분 평가"),
        "note":("일반 비금융기업을 대상으로 4개 서로 다른 재무위험 축을 평가합니다. "
                "일부 수치 미확보 시 나머지를 0점·50점으로 대체하지 않습니다.")
    }
