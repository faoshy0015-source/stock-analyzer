"""HanaV 20-point valuation model with independent data-coverage accounting.

Four slots: peer PER (6), five-year history (5 = PER 3 + PBR 2),
ROE-adjusted peer PBR (5) and forward PER against comparable consensus (4).

Missing evidence is never treated as an average score or zero. No company
is called undervalued unless source metrics are actually available.
"""
from __future__ import annotations

from math import isfinite
from statistics import median
from datetime import datetime
from zoneinfo import ZoneInfo


VALUATION_WEIGHTS = {
    "동종업종 PER 비교": 6,
    "과거 5년 PER·PBR 밴드": 5,
    "3개년 ROE 지속성": 5,
    "Forward PER 비교": 4,
}


def pos(value):
    try:
        num = float(value)
        return num if isfinite(num) and num > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def ratio_score(observed, benchmark):
    observed = pos(observed)
    benchmark = pos(benchmark)
    if observed is None or benchmark is None:
        return None
    ratio = observed / benchmark
    return round(max(0.0, min(100.0, (1.5 - ratio) * 100)), 1)


def percentile_score(current, historical, minimum=24):
    current = pos(current)
    valid = [pos(x) for x in (historical or [])]
    valid = [x for x in valid if x is not None]
    if current is None or len(valid) < minimum:
        return None
    below=sum(x < current for x in valid)
    equals=sum(x == current for x in valid)
    percentile=(below + 0.5 * equals) / len(valid)
    return round(max(0.0, min(100.0, 100.0 * (1.0 - percentile))), 1)


def _component(name, weight, score=None, evidence="", source="", covered_weight=None):
    covered = weight if score is not None else 0
    if covered_weight is not None:
        covered = float(covered_weight)
    earned = round(score * covered / 100, 3) if score is not None and covered else None
    return {
        "name": name,
        "weight": weight,
        "covered_weight": covered,
        "score": round(score, 1) if score is not None else None,
        "earned": earned,
        "status": "평가" if covered == weight else ("부분 평가" if covered else "미산출"),
        "evidence": evidence,
        "source": source,
    }


def _sustainable_roe(annual):
    """Score durable ROE from 3 consecutive filed fiscal years, not PER/PBR.

    This evaluates whether earnings on equity persist. It avoids the
    tautology PBR/ROE = PER by using 3-year ROE stability, not a price ratio.
    ROE approximates consolidated net income / year-end equity.
    """
    if annual is None or annual.empty:
        return None, "연간 DART 순이익·자본총계 최근 3개년 자료가 필요"
    if not {"period", "net_income", "equity"} <= set(annual.columns):
        return None, "연간 DART 순이익·자본총계 최근 3개년 자료가 필요"
    items = []
    for _, row in annual.iterrows():
        year = str(row.get("period") or "")
        if not (len(year) == 4 and year.isdigit()):
            continue
        ni = _signed(row.get("net_income"))
        eq = pos(row.get("equity"))
        if ni is None or eq is None:
            continue
        roe = ni / eq
        if not isfinite(roe) or abs(roe) > 3:
            continue
        items.append((int(year), roe))
    by_year = {year: roe for year, roe in items}
    if not by_year:
        return None, "유효한 순이익·자본총계가 없습니다."
    latest=max(by_year)
    now=datetime.now(ZoneInfo("Asia/Seoul")).year
    if latest > now-1 or latest < now-2:
        return None, "최근 확정 연간보고서가 충분하지 않습니다."
    selected_years=[latest-2, latest-1, latest]
    if any(year not in by_year for year in selected_years):
        return None, "최근 3개년 연속 순이익·자본총계가 필요합니다."
    three=[by_year[y] for y in selected_years]
    med=float(median(three))
    positive_years=sum(r > 0 for r in three)
    spread=max(three)-min(three)
    profitability=max(0.0,min(100.0,(med+0.05)*100/0.25))
    continuity=positive_years/3*100
    stability=max(0.0,min(100.0,100-(spread/0.25)*100))
    score=0.65*profitability+0.20*continuity+0.15*stability
    if positive_years==0:
        score=0
    elif positive_years==1:
        score=min(score,35)
    elif positive_years==2:
        score=min(score,70)
    return round(score,1), (
        f"{selected_years[0]}~{latest}년 연간 간이 ROE "
        f"{'/'.join(f'{r*100:+.1f}%' for r in three)} · "
        f"중앙값 {med*100:.1f}% · 흑자 {positive_years}/3년 · "
        "평가에 PER의 역산식(PBR/ROE)을 중복 사용하지 않음"
    )


def _signed(value):
    try:
        result=float(value)
        return result if isfinite(result) else None
    except (ValueError, TypeError, OverflowError):
        return None


def evaluate_valuation(profile, context=None, annual=None):
    """Return weight-aware valuation subscore ready for scoring.evaluate()."""
    profile = profile or {}
    context = context or {}
    result = []
    date = str(context.get("date") or "기준일 미확인")
    sector = str(context.get("sector_name") or "업종 미확인")

    # 1. Sector PER: same provider/current date, >=5 other listed peers.
    per = pos(context.get("krx_per"))
    peer_per = pos(context.get("peer_median_per"))
    count = int(context.get("peer_per_count") or 0)
    if per and peer_per and count >= 5:
        score=ratio_score(per,peer_per)
        detail=f"{sector} PER 중앙값 {peer_per:.2f}배 대비 대상 {per:.2f}배 · 비교종목 {count}개 · {date}"
    else:
        score=None
        detail="동일 KRX 업종의 비교기업 5개 이상 및 최신 동기준 PER이 필요"
    result.append(_component("동종업종 PER 비교",6,score,detail,"KRX/pykrx 업종분류·PER"))

    # 2. History: each of PER(3) and PBR(2) retains its own evidence/coverage.
    span=float(context.get("history_span_years") or 0)
    per_hist = context.get("historical_per") or []
    pbr_hist = context.get("historical_pbr") or []
    hp=percentile_score(context.get("krx_per"),per_hist) if span>=3 else None
    hb=percentile_score(context.get("krx_pbr"),pbr_hist) if span>=3 else None
    covered=(3 if hp is not None else 0)+(2 if hb is not None else 0)
    earned=(hp*3/100 if hp is not None else 0)+(hb*2/100 if hb is not None else 0)
    hist_score=round(earned/covered*100,1) if covered else None
    history_desc=(
        f"과거 약 {span:.1f}년 · PER {len(per_hist)}개월"
        f"({'평가' if hp is not None else '미산출'}), PBR {len(pbr_hist)}개월"
        f"({'평가' if hb is not None else '미산출'}) · "
        "현재 값이 과거 분포에서 낮을수록 높은 점수"
    )
    if not covered:
        history_desc="같은 KRX 기준의 3년 이상·최소 24개월 PER/PBR 이력이 필요"
    result.append(_component("과거 5년 PER·PBR 밴드",5,hist_score,
                             history_desc,"KRX/pykrx 과거 월말 PER·PBR",covered))

    # 3. Multi-year ROE persistence avoids tautological PBR/ROE = PER.
    # Current PBR is shown for context, but is not double-counted here.
    score, detail = _sustainable_roe(annual)
    pbr = pos(context.get("krx_pbr"))
    if pbr is not None:
        detail += f" · 현재 KRX PBR {pbr:.2f}배는 가격 참고자료(점수 중복 제외)"
    result.append(_component("3개년 ROE 지속성",5,score,detail,
                             "OpenDART 확정 연간 순이익·기말 자본 3개년"))

    # 4. Forward PER: do not compare an unaudited forecast with a broad
    # industry trailing multiple. No peer consensus -> no 4-point credit.
    forward=pos(profile.get("forwardPE"))
    peer_forward=pos(context.get("peer_forward_per_median"))
    fcount=int(context.get("peer_forward_per_count") or 0)
    if forward and peer_forward and fcount>=3 and context.get("forward_period_matched") is True:
        score=ratio_score(forward,peer_forward)
        detail=(f"동일 전망기간 Forward PER {forward:.2f}배 / "
                f"비교기업 중앙값 {peer_forward:.2f}배 · {fcount}개")
    else:
        score=None
        detail="동일 전망기간의 증권사 Forward PER 컨센서스와 동종기업 3개 이상 필요"
    result.append(_component("Forward PER 비교",4,score,detail,
                             "전망 컨센서스 (정식 데이터 확보 시)"))

    used=sum(x["covered_weight"] for x in result)
    earned=sum(x["earned"] or 0 for x in result)
    return {
        "weight":20, "covered_weight":round(used,2), "earned":round(earned,2),
        "score":round(100*earned/used,1) if used else None,
        "components":result,
        "confidence": "보통 · 업종·과거비교는 원천 지표와 회계기간 확인 필요",
        "note":"KRX 업종은 넓은 분류입니다. ROE 지속성 5점은 다년 수익의 안정성을 별도로 평가해 PBR/ROE를 다시 PER로 중복 채점하지 않습니다."
    }
