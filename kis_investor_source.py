"""Optional KIS licensed daily investor-flow diagnostic independent of pykrx.

Uses the existing KIS production API credentials from Streamlit's server-side
Secrets. This is a single-ticker, read-only diagnostic, not a market-wide
replacement, not automatically invoked, and not suitable for account trading.
"""
from __future__ import annotations

import re
from datetime import date

import pandas as pd
import requests

KIS_INVESTOR_URL = (
    "https://openapi.koreainvestment.com:9443"
    "/uapi/domestic-stock/v1/quotations/investor-trade-by-stock-daily"
)
KIS_INVESTOR_TR_ID = "FHPTJ04160001"
FLOW_FIELDS = ("prsn_ntby_qty", "frgn_ntby_qty", "orgn_ntby_qty")
DATE_FIELD = "stck_bsop_date"


class KisInvestorError(RuntimeError):
    """Safe, redacted failure for a KIS market-data query."""


def normalize_kis_investor_response(data, ticker, asof):
    """Return date-aligned *quantity-only* investor trading history.

    Do not synthesize missing days, trade values, prices or investor categories.
    Official KRX and broker-derived data may differ by market/session scope.
    """
    if not isinstance(data, dict) or str(data.get("rt_cd", "")) != "0":
        raise KisInvestorError("KIS 종목별 수급 API가 요청을 승인하지 않았습니다.")
    if not re.fullmatch(r"[0-9]{6}", str(ticker)):
        raise KisInvestorError("종목코드 형식 오류")
    rows = None
    for key in ("output2", "output1"):
        candidate = data.get(key)
        if isinstance(candidate, list) and candidate:
            if all(isinstance(row, dict) for row in candidate):
                if set((DATE_FIELD, *FLOW_FIELDS)).issubset(candidate[0]):
                    rows = candidate
                    break
    if rows is None:
        raise KisInvestorError(
            "KIS 수급 응답에 필수 일별 컬럼이 없습니다. "
            "제공처 API 이용 권한과 응답 필드를 확인하세요."
        )
    frame = pd.DataFrame(rows)
    dates = pd.to_datetime(frame[DATE_FIELD], format="%Y%m%d", errors="coerce")
    frame.index = dates
    frame = frame.loc[frame.index.notna()].copy()
    frame = frame.loc[frame.index <= pd.Timestamp(asof).normalize()]
    for field in FLOW_FIELDS:
        frame[field] = pd.to_numeric(frame[field], errors="coerce")
    frame = frame.dropna(subset=list(FLOW_FIELDS))
    frame = frame[~frame.index.duplicated(keep="first")].sort_index()
    if frame.empty:
        raise KisInvestorError(f"{asof}: 해당 날짜 이전의 KIS 수급자료 없음")
    renamed = frame[list(FLOW_FIELDS)].rename(columns={
        "prsn_ntby_qty": "개인 순매수(주)",
        "frgn_ntby_qty": "외국인 순매수(주)",
        "orgn_ntby_qty": "기관 순매수(주)",
    })
    return renamed.tail(25)


def fetch_kis_investor_history(
    ticker, asof, app_key, app_secret, access_token,
    session=None,
):
    """Single supported KIS market-data query; no stock-universe fanout."""
    if not re.fullmatch(r"[0-9]{6}", str(ticker)):
        raise KisInvestorError("6자리 종목코드가 필요합니다.")
    if not all((app_key, app_secret, access_token)):
        raise KisInvestorError("KIS APP KEY, APP SECRET 또는 유효한 접근 토큰이 없습니다.")
    asof_string = pd.Timestamp(asof).strftime("%Y%m%d")
    if asof_string > date.today().strftime("%Y%m%d"):
        raise KisInvestorError("미래 날짜는 조회할 수 없습니다.")
    get = session.get if session is not None else requests.get
    try:
        response = get(
            KIS_INVESTOR_URL,
            headers={
                "authorization": "Bearer " + str(access_token),
                "appkey": str(app_key),
                "appsecret": str(app_secret),
                "tr_id": KIS_INVESTOR_TR_ID,
                "custtype": "P",
                "Accept": "application/json",
            },
            params={
                "FID_COND_MRKT_DIV_CODE": "J",  # KRX only (not NXT/UN)
                "FID_INPUT_ISCD": str(ticker),
                "FID_INPUT_DATE_1": asof_string,
                "FID_ORG_ADJ_PRC": "",
                "FID_ETC_CLS_CODE": "",
            },
            timeout=(5, 12),
        )
        status = int(response.status_code)
        if status != 200:
            raise KisInvestorError(
                f"KIS 투자자별 수급 HTTP {status}. "
                "계정 API 권한·인증·요청 한도를 확인하세요."
            )
        try:
            payload = response.json()
        except ValueError:
            raise KisInvestorError(
                "KIS 투자자 수급 응답이 JSON 형식이 아닙니다."
            ) from None
    except KisInvestorError:
        raise
    except requests.exceptions.RequestException as exc:
        raise KisInvestorError(
            "KIS 수급 네트워크 요청 실패: " + type(exc).__name__
        ) from None
    return normalize_kis_investor_response(payload, str(ticker), asof)
