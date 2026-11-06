"""Analyst report target-price consensus from *actually retrieved* report metadata.

Not a fair-value estimate, not a guaranteed return. Use only a fresh latest
report per identifiable securities firm, with auditable dates and links.
A separate Npay publisher aggregate is a fallback and MUST NOT be represented
as the mean of the displayed report samples.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from math import isfinite
import re
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from analyst_reports import NAVER_ITEM_RESEARCH, NAVER_MOBILE_INTEGRATION, HEADERS


def _today(today=None):
    if isinstance(today,datetime):return today.date()
    if isinstance(today,date):return today
    if today is not None:
        try:return date.fromisoformat(str(today)[:10])
        except ValueError:return None
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


def target_krw(value):
    """Parse integer KRW amounts / quoted Korean 만원, reject ambiguous ranges."""
    if isinstance(value,(int,float)) and not isinstance(value,bool):
        x=float(value)
        return int(round(x)) if isfinite(x) and 100<=x<=1e9 else None
    raw=str(value or "").strip().replace(" ","")
    if not raw or raw in {"-","—","미제시","없음","N/A","0","None","nan"}:
        return None
    match=re.fullmatch(r"(\d+(?:\.\d+)?)만원",raw)
    if match:return target_krw(float(match.group(1))*10000)
    match=re.fullmatch(r"(\d+)만(\d+)천원",raw)
    if match:return target_krw(int(match.group(1))*10000+int(match.group(2))*1000)
    if not re.fullmatch(r"\d{1,3}(?:,\d{3})*(?:원)?|\d+(?:원)?",raw):
        return None
    raw=raw.removesuffix("원").replace(",","")
    try:return target_krw(float(raw))
    except ValueError:return None


def _broker_key(label):
    name=re.sub(r"[\s()（）]+","",str(label or "")).casefold()
    if not name or name in {"미표기","발행기관미표기","nan","없음","none"}:
        return ""
    # Source labels like "미래에셋증권" or "미래에셋" represent one firm.
    name=re.sub(r"(?:투자증권|증권|securities|research)$","",name)
    return name if len(name)>=2 else ""


def summarize_targets(reports,last_price,price_asof=None,today=None,days=90):
    """Use the *latest report*, at most one per brokerage, in last 90 days.

    A latest report without a verified target prevents reuse of an old target
    from that same broker. For <2 unique houses, an average is not shown.
    """
    now=_today(today)
    rows=[];latest={};n_skipped=0
    if now is None:
        return {"average":None,"upside_pct":None,"count":0,"rows":[],
                "reason":"조회 기준일을 해석할 수 없습니다."}
    if isinstance(reports,pd.DataFrame) and not reports.empty:
        for _,raw in reports.iterrows():
            broker=str(raw.get("broker") or "").strip()
            broker_key=_broker_key(broker)
            try:rdate=date.fromisoformat(str(raw.get("date") or "")[:10])
            except ValueError:
                n_skipped+=1
                continue
            if not broker_key or rdate>now or (now-rdate).days>days:
                n_skipped+=1
                continue
            title=str(raw.get("title") or "")
            link=str(raw.get("url") or "")
            if not link.startswith(("http://","https://")) or not title:
                n_skipped+=1
                continue
            record={
                "broker":broker,"date":rdate.isoformat(),
                "title":title,"url":link,
                "target":target_krw(raw.get("target_price")),
            }
            if (broker_key not in latest or
                (record["date"],bool(record["target"])) >
                (latest[broker_key]["date"],bool(latest[broker_key]["target"]))):
                latest[broker_key]=record

    rows=sorted((x for x in latest.values() if x["target"] is not None),
                key=lambda x:(x["date"],x["broker"]),reverse=True)
    count=len(rows)
    average=round(sum(r["target"] for r in rows)/count) if count>=2 else None
    price=None
    try:
        price=float(last_price)
        if not isfinite(price) or price<=0:price=None
    except (TypeError,ValueError,OverflowError):
        price=None
    pricedate=_today(price_asof) if price_asof is not None else None
    fresh_price=price is not None and pricedate is not None and 0 <= (now-pricedate).days<=7
    upside=round((average/price-1)*100,2) if average is not None and fresh_price else None
    return {
        "average":average,"upside_pct":upside,"count":count,
        "rows":rows, "min":min([x["target"] for x in rows],default=None),
        "max":max([x["target"] for x in rows],default=None),
        "price":price if fresh_price else None,
        "price_asof":pricedate.isoformat() if fresh_price else None,
        "lookback_days":int(days),"excluded_rows":n_skipped,
        "reason":(
            "" if average is not None and upside is not None
            else "시세 기준일이 오래되었거나 시세가 없습니다." if average is not None
            else "최근 90일 내 목표주가가 확인되는 서로 다른 증권사 2곳 이상이 필요합니다."
        ),
    }


def naver_published_consensus(code,today=None):
    """Optional separate provider-side consensus if report-level targets missing.

    Npay's consensusInfo.priceTargetMean is *not* a computed sample mean here.
    Uses read-only public integration JSON; format and permission can change.
    """
    if not re.fullmatch(r"\d{6}",str(code)):
        return {}, "종목코드 오류"
    try:
        r=requests.get(NAVER_MOBILE_INTEGRATION.format(code=code),
                       headers=HEADERS,timeout=(4,10))
        r.raise_for_status()
        body=r.json()
        info=body.get("consensusInfo") if isinstance(body,dict) else None
        if not isinstance(info,dict):
            return {}, "제공처 컨센서스 정보 없음"
        target=target_krw(info.get("priceTargetMean"))
        try:created=date.fromisoformat(str(info.get("createDate") or "")[:10])
        except ValueError:
            raw=str(info.get("createDate") or "")
            created=date(int(raw[:4]),int(raw[4:6]),int(raw[6:8])) if re.fullmatch(r"20\d{6}",raw) else None
        now=_today(today)
        if not target or not created or not now or (now-created).days<0 or (now-created).days>120:
            return {}, "제공처 평균 목표주가가 없거나 기준일이 120일보다 오래되었습니다."
        return {"target":target,"date":created.isoformat(),
                "source":"Npay 증권 제공 평균 (별도 집계 · 표본·기간 검증 불가)",
                "link":NAVER_ITEM_RESEARCH.format(code=code)}, ""
    except requests.RequestException as exc:
        return {},f"제공처 접속 실패: {type(exc).__name__}"
    except (ValueError,TypeError,OverflowError):
        return {}, "제공처 응답 형식 오류"
