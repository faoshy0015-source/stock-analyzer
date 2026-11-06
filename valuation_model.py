"""HanaV 20-point valuation model with independent data-coverage accounting.

Four slots: peer PER (6), five-year history (5 = PER 3 + PBR 2),
ROE-adjusted peer PBR (5) and forward PER against comparable consensus (4).

Missing evidence is never treated as an average score or zero. No company
is called undervalued unless source metrics are actually available.
"""
from __future__ import annotations

from math import isfinite


VALUATION_WEIGHTS = {
    "동종업종 PER 비교": 6,
    "과거 5년 PER·PBR 밴드": 5,
    "ROE 보정 PBR": 5,
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


def evaluate_valuation(profile, context=None):
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

    # 3. PBR relative to same industry peer ROE: EPS/BPS is used consistently
    # across ticker and sector. Correlated with PER: note to user.
    target_pbr = pos(context.get("krx_pbr"))
    target_roe = pos(context.get("krx_roe_proxy"))
    median_price_to_roe = pos(context.get("peer_median_pbr_roe"))
    roe_count=int(context.get("peer_pbr_roe_count") or 0)
    if target_pbr and target_roe and median_price_to_roe and roe_count>=5:
        pbr_to_roe=target_pbr/target_roe
        score=ratio_score(pbr_to_roe,median_price_to_roe)
        detail=(f"{sector} PBR/ROE 중앙값 {median_price_to_roe:.2f}, "
                f"대상 {pbr_to_roe:.2f}, ROE(EPS/BPS) {target_roe*100:.1f}%, 비교종목 {roe_count}개")
    else:
        score=None
        detail="같은 업종의 EPS/BPS·PBR 유효 기업 5개 이상이 필요"
    result.append(_component("ROE 보정 PBR",5,score,detail,
                             "KRX/pykrx EPS·BPS·PBR (간이 ROE)"))

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
        "confidence": "낮음 · 업종 PER·PBR 관련 지표 간 상관성 주의",
        "note":"비교기업은 KRX의 넓은 업종분류이며 수익성·회계기간이 완벽히 일치하지 않을 수 있습니다."
    }
