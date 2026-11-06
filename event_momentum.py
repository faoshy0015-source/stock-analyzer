"""Conservative 10-point event momentum: DART 6 + verifiable headlines 4.

This reads only public filing titles and news headlines, not article bodies.
A filing is not a price forecast. Absence of signal means MISSING evidence,
not neutral 50 or negative zero. Scores are heuristics, not causal estimates.
"""
from __future__ import annotations

from datetime import date, timedelta
from email.utils import parsedate_to_datetime
import re
from zoneinfo import ZoneInfo
from datetime import datetime

import pandas as pd

MOMENTUM_WEIGHTS = {"공식 공시 이벤트": 6, "최근 뉴스 교차 확인": 4}


def _today(value=None):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is not None:
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            pass
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


def _date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = str(value or "").strip()
    if re.fullmatch(r"20\d{6}", raw):
        try:
            return date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
        except ValueError:
            return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(raw).date()
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


def _norm(text):
    return re.sub(r"[ㆍ·･\W_]+", "", str(text or "")).casefold()


def _filing_type(title):
    name = _norm(title)
    # Amended filings require reading the underlying document; never treat
    # a correction as an independent new positive/negative event.
    if any(x in name[:9] for x in ("기재정정", "첨부정정", "정정신고", "정정보고")):
        return None
    high_risk = (
        "횡령배임혐의발생", "상장폐지결정", "상장폐지사유발생",
        "감사의견거절", "회생절차개시신청", "부도발생", "영업정지",
    )
    if any(term in name for term in high_risk):
        return "중대 위험 공시", 12, "중대 위험 이벤트 확인. 구체적 영향은 원문 확인 필요"
    if any(term in name for term in (
        "유상증자결정", "전환사채권발행결정", "신주인수권부사채권발행결정",
    )):
        return "잠재 희석", 38, "자본 조달·희석 가능성. 방식과 자금 사용목적 확인 필요"
    if any(term in name for term in (
        "자기주식소각결정", "자기주식취득결정",
    )):
        return "주주환원", 66, "주주환원 관련 공시. 규모·실행 여부 확인 필요"
    if any(term in name for term in (
        "단일판매공급계약체결", "공급계약체결",
    )):
        return "공급계약", 62, "공급계약 관련 공시. 매출 대비 계약 비중 확인 전 약한 긍정 신호"
    return None


# These phrases need a concrete direction or actual event; words such as
# 'growth', 'up', 'lawsuit', or 'contract' alone are not scored.
_HEADLINE_RULES = [
    ("위험", -1, ("상장폐지", "횡령", "배임 혐의", "감사의견 거절", "영업정지", "회생절차")),
    ("자금조달", -1, ("유상증자 결정", "전환사채 발행 결정", "전환사채권 발행")),
    ("실적악화", -1, ("적자전환", "실적 하향", "영업이익 급감", "영업손실 확대",
                    "목표주가 하향", "실적 전망 하향")),
    ("실적개선", +1, ("흑자전환", "실적 상향", "영업이익 급증", "영업이익 증가",
                    "실적 개선", "목표주가 상향")),
    ("공급계약", +1, ("대규모 수주", "공급계약 체결", "신규 공급계약 체결")),
    ("주주환원", +1, ("자사주 소각 결정", "자기주식 소각", "자사주 취득 결정")),
]


def _headline_type(title, company):
    t = _norm(title)
    # Prevent broad market headlines about sector peers from affecting one
    # company's score even when RSS search returns them.
    if len(_norm(company)) < 2 or _norm(company) not in t:
        return None
    # Headlines with denials, rumors and directional contradiction are not
    # reliable enough to score without reading their original articles.
    if any(term in t for term in ("사실무근", "전면부인", "오보", "아니다", "부인")):
        return None
    matches=[]
    for category, sign, terms in _HEADLINE_RULES:
        if any(_norm(term) in t for term in terms):
            matches.append((category, sign))
    if not matches or len({sign for _,sign in matches})!=1:
        return None
    category, sign = matches[0]
    return category, sign


def _component(name, weight, score, detail, evidence_count=0):
    return {
        "name": name, "weight": weight,
        "covered_weight": weight if score is not None else 0,
        "score": round(score, 1) if score is not None else None,
        "earned": round(weight*score/100, 2) if score is not None else None,
        "status": "평가" if score is not None else "미산출",
        "evidence": detail, "evidence_count": evidence_count,
    }


def evaluate_event_momentum(disclosures=None, news=None, company="", as_of=None):
    """Return 10-point signal with evidence list and actual covered weights.

    Disclosure window 60 days; news window 21 days, with 2 independent
    publishers minimum for the four-point news component.
    """
    now = _today(as_of)
    filings = []
    seen=set()
    if isinstance(disclosures, pd.DataFrame) and not disclosures.empty:
        for _, row in disclosures.head(150).iterrows():
            title=str(row.get("report_nm") or "")
            d=_date(row.get("rcept_dt"))
            receipt=str(row.get("rcept_no") or "")
            classified=_filing_type(title)
            if not classified or not d or d > now or (now-d).days > 60:
                continue
            if not re.fullmatch(r"\d{14}", receipt):
                continue
            cat,score,reason=classified
            ident=(cat,d.isoformat(),_norm(title))
            if ident in seen:
                continue
            seen.add(ident)
            filings.append({
                "date":d.isoformat(),"source":"OpenDART", "title":title,
                "type":cat, "score":score, "reason":reason,
                "link":"https://dart.fss.or.kr/dsaf001/main.do?rcpNo="+receipt,
            })
    filings.sort(key=lambda item:item["date"],reverse=True)
    if filings:
        weighted=[(x["score"], 1 if (now-date.fromisoformat(x["date"])).days<=21 else 0.6)
                  for x in filings[:8]]
        dscore=sum(s*w for s,w in weighted)/sum(w for _,w in weighted)
        filing_detail=f"최근 60일 분류 가능한 DART 공시 {len(filings)}건 · 공시 제목 기준; 규모·내용 확인 필요"
    else:
        dscore=None
        filing_detail="최근 60일 분류 가능한 주요 공시 미확인(공시가 없거나 조회 불가한 경우 모두 포함)"

    headlines=[]
    nseen=set()
    scored_filing_categories={x["type"] for x in filings}
    overlaps={"위험":"중대 위험 공시","자금조달":"잠재 희석",
              "공급계약":"공급계약","주주환원":"주주환원"}
    if isinstance(news,pd.DataFrame) and not news.empty:
        for _,row in news.head(40).iterrows():
            title=str(row.get("title") or "")
            d=_date(row.get("date"))
            news_cat=_headline_type(title,company)
            source=str(row.get("source") or "").strip()
            url=str(row.get("link") or "")
            if not news_cat or not d or d>now or (now-d).days>21 or not source:
                continue
            category,sign=news_cat
            if overlaps.get(category) in scored_filing_categories:
                continue  # Same event already counted via primary disclosure.
            dedup=_norm(title.split(" - ")[0])
            if dedup in nseen:
                continue
            nseen.add(dedup)
            headlines.append({
                "date":d.isoformat(),"source":source, "title":title,
                "type":category, "score":67 if sign>0 else 33,
                "reason":"제목 방향성에 근거한 약한 신호(기사 본문 미검증)",
                "link":url if url.startswith(("http://","https://")) else "",
            })
    headlines.sort(key=lambda item:item["date"],reverse=True)
    unique_publishers={h["source"].casefold() for h in headlines}
    if len(headlines)>=2 and len(unique_publishers)>=2:
        # Cap influence of repeated coverage from an individual publisher.
        newest_per_publisher={}
        for x in headlines:
            key=x["source"].casefold()
            newest_per_publisher.setdefault(key,x)
        scored=list(newest_per_publisher.values())[:5]
        nscore=sum(x["score"] for x in scored)/len(scored)
        news_detail=(f"최근 21일 관련 이벤트 제목 {len(headlines)}건 / "
                     f"서로 다른 언론사 {len(unique_publishers)}곳 · 기사 본문 미확인")
    else:
        nscore=None
        news_detail="최근 21일 독립 매체 2곳 이상의 종목 관련 이벤트성 제목 필요"

    components=[
        _component("공식 공시 이벤트",6,dscore,filing_detail,len(filings)),
        _component("최근 뉴스 교차 확인",4,nscore,news_detail,len(headlines))
    ]
    used=sum(x["covered_weight"] for x in components)
    earned=sum(x["earned"] or 0 for x in components)
    return {
        "category":"뉴스 모멘텀", "weight":10,
        "covered_weight":used,
        "score":round(earned/used*100,1) if used else None,
        "earned":round(earned,2),
        "components":components,
        "events":filings[:12]+headlines[:12],
        "confidence":"낮음 · 공시 제목 및 독립 언론사 뉴스 제목만 분석" if used else "미산출",
        "note":"이벤트 발생은 기업가치 변화의 확정 증거가 아닙니다. 공시 원문·뉴스 본문을 직접 검증해야 합니다.",
    }
