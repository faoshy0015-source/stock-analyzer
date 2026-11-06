"""Read-only KRX valuation comparison data. All failures are missing, not zero.

Requires public pykrx endpoints. The underlying provider can reject or change
requests. No invented peers, valuation histories or analyst forecasts.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd


def _num(value):
    try:
        result = float(str(value).replace(",", ""))
        if pd.notna(result) and 0 < result < 1e7:
            return result
    except (ValueError, TypeError, OverflowError):
        pass
    return None


def _per_and_pbr(frame, code):
    if frame is None or frame.empty:
        return None, None
    key = str(code)
    if key not in frame.index.astype(str):
        return None, None
    row = frame.loc[key]
    if isinstance(row, pd.DataFrame):
        row = row.iloc[0]
    return _num(row.get("PER")), _num(row.get("PBR"))


def _sector_peers(fundamentals, sectors, code, min_peers=5):
    """Use KRX's own broad sector classification, not guessed competitors."""
    if fundamentals is None or fundamentals.empty or sectors is None or sectors.empty:
        return {}
    sector_codes = sectors.index.astype(str)
    code = str(code)
    if code not in sector_codes or "업종명" not in sectors.columns:
        return {}
    industry = str(sectors.loc[code, "업종명"]).strip()
    if not industry:
        return {}
    group = sectors.loc[sectors["업종명"].astype(str).eq(industry)]
    peer_codes = [t for t in group.index.astype(str) if t != code]
    peers = fundamentals.loc[fundamentals.index.astype(str).isin(peer_codes)].copy()
    if peers.empty:
        return {"sector_name": industry, "peer_count": 0}
    # Exclude invalid, zero and non-finite multiples without excluding profitable
    # businesses solely because their valuation is high.
    per = pd.to_numeric(peers.get("PER"), errors="coerce") if "PER" in peers else pd.Series(dtype=float)
    pbr = pd.to_numeric(peers.get("PBR"), errors="coerce") if "PBR" in peers else pd.Series(dtype=float)
    per = per[(per > 0) & (per < 400)].dropna()
    pbr = pbr[(pbr > 0) & (pbr < 100)].dropna()
    result = {"sector_name": industry, "peer_count": int(len(peers)),
              "peer_per_count": int(len(per)), "peer_pbr_count": int(len(pbr))}
    if len(per) >= min_peers:
        result["peer_median_per"] = float(per.median())
    if len(pbr) >= min_peers:
        result["peer_median_pbr"] = float(pbr.median())
    # KRX EPS/BPS is a same-definition peer profitability proxy; not full
    # DART weighted-average-equity ROE. Never label this as official ROE.
    if {"EPS", "BPS", "PBR"} <= set(peers.columns):
        eps = pd.to_numeric(peers["EPS"], errors="coerce")
        bps = pd.to_numeric(peers["BPS"], errors="coerce")
        peer_roe = eps / bps.replace(0, float("nan"))
        valid = peers.loc[(peer_roe > 0.01) & (peer_roe < 0.7) &
                          (pd.to_numeric(peers["PBR"],errors="coerce") > 0)].copy()
        if len(valid) >= min_peers:
            roe_vals = (pd.to_numeric(valid["EPS"], errors="coerce") /
                        pd.to_numeric(valid["BPS"],errors="coerce"))
            # Sector PBR / ROE as an industry-relative measure. The PER
            # relationship implies overlapping information, disclosed in UI.
            ratios = pd.to_numeric(valid["PBR"], errors="coerce") / roe_vals
            ratios = ratios[(ratios > 0) & (ratios < 1e4)].dropna()
            if len(ratios) >= min_peers:
                result["peer_median_pbr_roe"] = float(ratios.median())
                result["peer_pbr_roe_count"] = int(len(ratios))
    return result


def _history_monthly(frame):
    result = {"historical_per": [], "historical_pbr": [],
              "history_months_per": 0, "history_months_pbr": 0,
              "history_span_years": 0}
    if frame is None or frame.empty:
        return result
    frame = frame.copy().sort_index()
    # Convert daily to month-end observations to avoid overweighting months
    # with more trading sessions. Caller may already deliver monthly rows.
    if isinstance(frame.index, pd.DatetimeIndex):
        frame.index = frame.index.tz_localize(None) if frame.index.tz is not None else frame.index
        frame = frame.resample("ME").last()
        if len(frame) > 1:
            result["history_span_years"] = round(
                (frame.index.max() - frame.index.min()).days / 365.25, 2)
    for metric, field in [("PER", "historical_per"), ("PBR", "historical_pbr")]:
        if metric not in frame:
            continue
        values = pd.to_numeric(frame[metric], errors="coerce")
        values = values[(values > 0) & (values < (400 if metric == "PER" else 100))]
        result[field] = [round(float(x), 4) for x in values.dropna().tolist()][-64:]
        result["history_months_" + metric.lower()] = len(result[field])
    return result


def fetch_valuation_context(code, market, history_years=5):
    """Fetch latest KRX sector comparables and 5y monthly fundamentals.

    Returns a plain dict for Streamlit cache; the 'errors' field contains no
    credential values. Historic values use KRX's date-specific EPS/BPS basis.
    """
    result = {"source": "pykrx/한국거래소", "errors": []}
    market = "KOSDAQ" if "KOSDAQ" in str(market).upper() else "KOSPI"
    code = str(code)
    if not (code.isascii() and code.isdigit() and len(code) == 6):
        result["errors"].append("종목코드가 6자리 숫자가 아닙니다.")
        return result
    try:
        from pykrx import stock
    except ImportError:
        result["errors"].append("pykrx 라이브러리 사용 불가")
        return result

    refdate = datetime.now(ZoneInfo("Asia/Seoul")).date()
    # Do not assume today's EOD fundamentals are available.
    for days_back in (1, 2, 3, 4, 5, 6, 7):
        day = refdate - timedelta(days=days_back)
        if day.weekday() >= 5:
            continue
        stamp = day.strftime("%Y%m%d")
        try:
            fundamentals = stock.get_market_fundamental_by_ticker(stamp, market=market)
            if fundamentals is None or fundamentals.empty:
                continue
            current_per, current_pbr = _per_and_pbr(fundamentals, code)
            if current_per is None and current_pbr is None:
                continue
            result.update({"date": day.isoformat(), "krx_per":current_per,
                           "krx_pbr":current_pbr})
            row = fundamentals.loc[code] if code in fundamentals.index.astype(str) else None
            if row is not None:
                eps = _num(row.get("EPS"))
                bps = _num(row.get("BPS"))
                if eps and bps:
                    result["krx_roe_proxy"] = eps / bps
            try:
                sector = stock.get_market_sector_classifications(stamp, market)
                result.update(_sector_peers(fundamentals, sector, code))
            except Exception as exc:
                result["errors"].append("업종별 비교 조회 실패: " + type(exc).__name__)
            break
        except Exception as exc:
            result["errors"].append("KRX 현재 PER/PBR 조회 실패: " + type(exc).__name__)
            break

    try:
        start=(refdate - timedelta(days=365 * int(history_years)+10)).strftime("%Y%m%d")
        end=(refdate - timedelta(days=1)).strftime("%Y%m%d")
        historical=stock.get_market_fundamental_by_date(start,end,code,freq="m")
        result.update(_history_monthly(historical))
    except Exception as exc:
        result["errors"].append("과거 5년 PER/PBR 조회 실패: " + type(exc).__name__)
    return result
