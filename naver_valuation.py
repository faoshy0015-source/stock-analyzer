"""Read-only Npay/Naver Finance valuation snapshot.

Important: the provider's PER/EPS and PBR/BPS may use a different reporting
period from KRX. Do not combine these figures with KRX or Yahoo ratios.
The mobile JSON endpoint is public but undocumented; failures leave values
missing rather than substituting a mismatched accounting basis.
"""
from __future__ import annotations

from datetime import datetime
from math import isfinite
import re
from zoneinfo import ZoneInfo

import requests

BASE = "https://m.stock.naver.com/api/stock"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://m.stock.naver.com/",
    "Accept": "application/json",
}
FIELDS = {
    "per": "per",
    "eps": "eps",
    "pbr": "pbr",
    "bps": "bps",
    "cnsper": "forward_per",
    "cnseps": "forward_eps",
    "dividendyieldratio": "dividend_yield",
    "dividend": "dps",
}


def _number(raw):
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, dict):
        return None
    value = str(raw).strip().replace(",", "")
    if not value or value in ("-", "—", "N/A", "null", "None"):
        return None
    match = re.fullmatch(r"\s*([+-]?\d+(?:\.\d+)?)\s*(?:배|원|%|％)?\s*", value)
    if not match:
        return None
    try:
        number = float(match.group(1))
    except ValueError:
        return None
    return number if isfinite(number) and abs(number) < 1e12 else None


def parse_naver_integration(payload):
    """Parse only recognized codes from the provider's totalInfos list."""
    if not isinstance(payload, dict):
        return {}
    entries = payload.get("totalInfos")
    if not isinstance(entries, list):
        return {}
    parsed = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("code") or "").strip().lower()
        field = FIELDS.get(key)
        if field is None:
            continue
        value = _number(entry.get("value"))
        if value is None:
            continue
        if field in ("per", "pbr", "bps", "forward_per") and value <= 0:
            continue
        if field in ("dividend_yield", "dps") and value < 0:
            continue
        parsed[field] = value
    return parsed



ANNUAL_FIELDS = {
    "EPS": "eps",
    "BPS": "bps",
    "PER": "reported_per",
    "PBR": "reported_pbr",
}


def parse_naver_annual(payload, current_year=None):
    """Read explicitly flagged forecast columns. No inferred consensus years."""
    if not isinstance(payload, dict):
        return {}
    info = payload.get("financeInfo")
    if not isinstance(info, dict):
        return {}
    headers = info.get("trTitleList")
    rows = info.get("rowList")
    if not isinstance(headers, list) or not isinstance(rows, list):
        return {}
    forecast_periods = {}
    for col in headers:
        if not isinstance(col, dict):
            continue
        if str(col.get("isConsensus") or "").strip().upper() != "Y":
            continue
        key = str(col.get("key") or "").strip()
        if not re.fullmatch(r"20\d{4}", key):
            continue
        year = int(key[:4])
        if current_year is not None and year not in (current_year, current_year + 1):
            continue
        # Use a fiscal year-ending December period for calendar-year comparison.
        if key[4:6] != "12":
            continue
        forecast_periods[key] = year
    if not forecast_periods:
        return {}
    result = {year: {"year": year, "estimated": True}
              for year in forecast_periods.values()}
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = re.sub(r"\s+", "", str(row.get("title") or "")).upper()
        match = re.match(r"^(EPS|BPS|PER|PBR)(?:\([^)]*\))?$", title)
        if not match:
            continue
        field = ANNUAL_FIELDS[match.group(1)]
        columns = row.get("columns")
        if not isinstance(columns, dict):
            continue
        for key, year in forecast_periods.items():
            raw = columns.get(key)
            if isinstance(raw, dict):
                raw = raw.get("value")
            value = _number(raw)
            if value is None or (field != "eps" and value <= 0):
                continue
            # EPS may be negative; do not turn an earnings loss into a PER.
            result[year][field] = value
    # Remove empty financial rows; estimates without EPS/BPS are not useful.
    return {year: row for year, row in result.items()
            if any(k in row for k in ("eps", "bps"))}


def _checked_pairs(values, reference_price):
    """Do not show conflicting PER/EPS or PBR/BPS as a coherent Npay pair."""
    warnings = []
    if reference_price is None or reference_price <= 0:
        return warnings
    for numerator, denominator in (("per", "eps"), ("pbr", "bps")):
        a, b = values.get(numerator), values.get(denominator)
        if a is None or b is None or b <= 0:
            continue
        computed_price = a * b
        if abs(computed_price - reference_price) / reference_price > 0.20:
            values.pop(numerator, None)
            values.pop(denominator, None)
            warnings.append(
                f"{numerator.upper()}/{denominator.upper()}와 제공 시세의 "
                "산술 일관성이 확인되지 않아 해당 두 값을 숨겼습니다."
            )
    return warnings


def fetch_naver_valuation(code):
    """Return source-separated valuation fields and a timestamp; never guess."""
    code = str(code).strip()
    result = {
        "source": "네이버 금융 Npay (모바일 공개 집계)",
        "requested_at": datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M KST"),
        "quote_time": "",
        "error": "",
        "warnings": [],
    }
    if not re.fullmatch(r"\d{6}", code):
        result["error"] = "종목코드 형식 오류"
        return result
    try:
        response = requests.get(
            f"{BASE}/{code}/integration", headers=HEADERS, timeout=(4, 9),
        )
        response.raise_for_status()
        values = parse_naver_integration(response.json())
        if not values:
            result["error"] = "Npay 투자지표 응답에 유효한 PER·EPS·PBR·BPS 정보가 없습니다."
            return result
        result.update(values)
    except (requests.exceptions.RequestException, ValueError, TypeError) as exc:
        result["error"] = "Npay 투자지표 연결 실패 (" + type(exc).__name__ + ")"
        return result

    # Annual consensus has a different basis from trailing EPS/BPS.
    # It is never substituted into the historical/current valuation fields.
    try:
        annual_response = requests.get(
            f"{BASE}/{code}/finance/annual", headers=HEADERS, timeout=(4, 10),
        )
        annual_response.raise_for_status()
        forecast = parse_naver_annual(
            annual_response.json(),
            current_year=datetime.now(ZoneInfo("Asia/Seoul")).year,
        )
        result["annual_forecasts"] = forecast
        if not forecast:
            result["warnings"].append(
                "Npay 연간 재무 응답에서 올해·내년 예상 EPS/BPS 열을 확인하지 못했습니다."
            )
    except (requests.exceptions.RequestException, ValueError, TypeError) as exc:
        result["annual_forecasts"] = {}
        result["warnings"].append(
            "연도별 컨센서스 조회 실패 (" + type(exc).__name__ + ")"
        )

    # Basic quote is used only to cross-check accounting pairs and to show
    # the quote's timestamp; it must not be described as the metric period.
    try:
        response = requests.get(
            f"{BASE}/{code}/basic", headers=HEADERS, timeout=(4, 7),
        )
        response.raise_for_status()
        basic = response.json()
        if isinstance(basic, dict):
            stamp = str(basic.get("localTradedAt") or "")
            if stamp:
                try:
                    time = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                    if time.tzinfo is None:
                        time = time.replace(tzinfo=ZoneInfo("Asia/Seoul"))
                    result["quote_time"] = time.astimezone(
                        ZoneInfo("Asia/Seoul")
                    ).strftime("%Y-%m-%d %H:%M KST")
                except ValueError:
                    pass
            quote_price = _number(basic.get("closePrice"))
            result["warnings"].extend(_checked_pairs(result, quote_price))
            result["quote_price"] = quote_price if quote_price and quote_price > 0 else None
            for year, row in result.get("annual_forecasts", {}).items():
                eps = row.get("eps")
                if result["quote_price"] and eps is not None and eps > 0:
                    row["current_price_per"] = round(result["quote_price"] / eps, 2)
    except (requests.exceptions.RequestException, ValueError, TypeError):
        result["warnings"].append(
            "시세 기준일·PER/EPS의 산술 일관성은 별도로 확인하지 못했습니다."
        )
    return result
