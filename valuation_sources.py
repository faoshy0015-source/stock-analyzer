"""Licensed-source valuation fallback for KR equities.

Source order: broker/Yahoo supplied metrics first, then KRX Open API market
capitalization combined with annual DART statements. Derived metrics are
only *rough proxies*, not KRX/analyst PER or PBR (TTM / parent-only basis differs).
Never use unapproved/private HTML screen scraping.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import re

import pandas as pd
import requests

KRX_STOCK_API = "https://data-dbg.krx.co.kr/svc/apis/sto/"
KRX_SOURCE = "KRX OPEN API"
DART_SOURCE = "OpenDART"
PREFERRED_SUFFIX = re.compile(r"^(?:[1-9]\d?)?우(?:[A-Z])?$")


def positive(value):
    try:
        n = float(str(value).replace(",", "").strip())
        return n if 0 < n < 1e18 else None
    except (ValueError, TypeError, OverflowError):
        return None


def from_krx_rows(rows, code, name=""):
    """Aggregate issuer's listed ordinary + preferred share market caps.

    If the common stock is not found, return no result; a partial match must
    not create an apparently complete issuer market cap.
    """
    common = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("ISU_CD", "")).strip() == str(code):
            common = row
            break
    if common is None:
        return {}
    marketcap = positive(common.get("MKTCAP"))
    close = positive(common.get("TDD_CLSPRC"))
    if marketcap is None or close is None:
        return {}
    common_name = str(common.get("ISU_NM") or name).strip().replace(" ", "")
    classes = [(str(code), marketcap)]
    for row in rows:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ISU_CD") or "").strip()
        title = str(row.get("ISU_NM") or "").strip().replace(" ", "")
        cap = positive(row.get("MKTCAP"))
        if ticker == code or cap is None or not title.startswith(common_name):
            continue
        suffix = title[len(common_name):]
        if PREFERRED_SUFFIX.fullmatch(suffix):
            classes.append((ticker, cap))
    d = str(common.get("BAS_DD") or "")
    if not re.fullmatch(r"20\d{6}", d):
        return {}
    return {"marketcap": sum(v for _, v in classes),
            "close": close, "date": f"{d[:4]}-{d[4:6]}-{d[6:8]}",
            "included_classes": [x for x, _ in classes],
            "source": KRX_SOURCE}


def krx_company_marketcap(code, market, key, days=9):
    """Retrieve prior business-day KRX market cap for a selected ticker.

    The user must have an independently authorized KRX OPEN API service
    subscription. Secrets are never returned or logged.
    """
    if not key:
        return {}, "KRX 인증키가 등록되지 않았습니다."
    market = str(market).upper()
    api_id = "ksq_bydd_trd" if ("KOSDAQ" in market or market == "KQ") else "stk_bydd_trd"
    url = KRX_STOCK_API + api_id
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    tried = 0
    for gap in range(1, max(2, min(int(days), 12)) + 1):
        target = today - timedelta(days=gap)
        if target.weekday() >= 5:
            continue
        tried += 1
        try:
            r = requests.get(url,params={"basDd":target.strftime("%Y%m%d")},
                             headers={"AUTH_KEY":str(key).strip(),
                                      "Accept":"application/json"},
                             timeout=(5, 11))
            if r.status_code in (401, 403):
                return {}, f"KRX API 인증·활용 신청 오류 (HTTP {r.status_code})"
            if r.status_code == 429:
                return {}, "KRX API 요청 한도 초과 (HTTP 429)"
            r.raise_for_status()
            payload = r.json()
            if not isinstance(payload, dict):
                continue
            rows = payload.get("OutBlock_1") or payload.get("output") or []
            if not isinstance(rows, list):
                continue
            matched = from_krx_rows(rows, str(code))
            if matched:
                return matched, ""
        except requests.exceptions.RequestException as exc:
            return {}, f"KRX 연결 문제: {type(exc).__name__}"
        except (TypeError, ValueError):
            return {}, "KRX 응답 형식 오류"
    return {}, f"KRX {tried}거래일 조회에서 해당 종목 시가총액 응답 없음"


def _latest_annual(annual):
    if annual is None or annual.empty or "period" not in annual:
        return {}
    today_year = datetime.now(ZoneInfo("Asia/Seoul")).year
    d = annual.copy()
    d["period"] = d["period"].astype(str)
    d = d[d["period"].str.fullmatch(r"20\d{2}")]
    if d.empty:
        return {}
    d = d.sort_values("period")
    row = d.iloc[-1]
    try:
        period = int(row["period"])
    except (ValueError, TypeError):
        return {}
    if period < today_year - 2 or period >= today_year:
        return {}
    return row.to_dict()


def fill_valuation(profile, krx_snapshot, annual, kis_snapshot=None):
    """Fill missing trailingPE / priceToBook from same-date KRX cap + DART.

    Missing metrics stay missing. Set explicit metadata flags so UI and scoring
    never mistake the proxy for an official forward/TTM PER/PBR.
    """
    result = dict(profile or {})
    result.setdefault("__valuation_source", "Yahoo Finance")
    kis_snapshot = kis_snapshot or {}
    # Broker source, if available, is more direct than a reconstructed ratio.
    for target, field in [("trailingPE", "per"), ("priceToBook", "pbr")]:
        existing = positive(result.get(target))
        if existing is None:
            kis = positive(kis_snapshot.get(field))
            if kis is not None:
                result[target] = kis
                result["__valuation_source"] = "한국투자증권 KIS REST"
    marketcap = positive(krx_snapshot.get("marketcap"))
    fy = _latest_annual(annual)
    if fy:
        ni = positive(fy.get("net_income"))
        eq = positive(fy.get("equity"))
        if not positive(result.get("returnOnEquity")) and ni and eq:
            # Last available comparable FY equity improves over single closing book.
            prev_rows = annual[annual["period"].astype(str) ==
                               str(int(fy["period"]) - 1)] if annual is not None else pd.DataFrame()
            prev_eq = positive(prev_rows.iloc[-1].get("equity")) if not prev_rows.empty else None
            denom = (eq + prev_eq) / 2 if prev_eq else eq
            if denom > 0:
                result["returnOnEquity"] = ni / denom
                result["__roe_approx"] = True
                result["__roe_approx_note"] = (
                    f"DART {fy['period']}년 당기순이익/전기말·당기말 자본 평균 기준 간이 ROE; "
                    "지배주주 귀속분 미조정"
                )
    if marketcap and fy:
        ni = positive(fy.get("net_income"))
        eq = positive(fy.get("equity"))
        approximated = []
        if not positive(result.get("trailingPE")) and ni:
            ratio = marketcap / ni
            if 0 < ratio <= 1000:
                result["trailingPE"] = ratio
                approximated.append("PER")
        if not positive(result.get("priceToBook")) and eq:
            ratio = marketcap / eq
            if 0 < ratio <= 1000:
                result["priceToBook"] = ratio
                approximated.append("PBR")
        if approximated:
            result["__valuation_approx"] = approximated
            result["__valuation_approx_note"] = (
                f"{fy['period']}년 DART 확정 재무자료와 {krx_snapshot.get('date','')} "
                "KRX 보통주·확인된 우선주 시가총액으로 계산한 간이 지표입니다. "
                "지배주주 귀속분·최근 4분기 순이익·자기주식·주식종류를 "
                "엄밀히 조정한 공식 PER/PBR과 다를 수 있습니다."
            )
            result["__valuation_source"] = (
                result["__valuation_source"] + " + KRX·DART 간이 계산"
            )
    if marketcap and (result.get("__valuation_approx") or not positive(result.get("marketCap"))):
        result["marketCap"] = marketcap
        result["__marketcap_source"] = "KRX(보통주+확인된 우선주 합산)"
    result["__krx_marketcap_date"] = str(krx_snapshot.get("date") or "")
    result["__krx_share_classes"] = krx_snapshot.get("included_classes", [])
    return result
