"""Exchange-wide, exact-session investor-flow reversal screening.

KRX ranking tables are never assumed to be complete: we compare their ticker
coverage against that date's positive-volume KRX OHLCV universe. Missing
coverage causes an explicit failure instead of an apparently empty result.
This module does not transmit or persist market data.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from math import ceil, isfinite
from zoneinfo import ZoneInfo
import re
import time

import pandas as pd

MARKETS = ("KOSPI", "KOSDAQ")
INVESTORS = {"개인": "personal", "외국인": "foreign", "기관합계": "institution"}
REQUIRED_FLOW = ("순매수거래량", "순매수거래대금")
DEFAULT_COVERAGE = 0.90


class ScanDataError(RuntimeError):
    """A missing or incomplete KRX response must never mean 'no signals'."""


def _tidy_tickers(frame, columns):
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ScanDataError("KRX 빈 응답")
    if not set(columns).issubset(frame.columns):
        raise ScanDataError("KRX 필드 불일치: " + ", ".join(set(columns) - set(frame.columns)))
    data = frame.copy()
    data.index = data.index.astype(str).str.zfill(6)
    data = data[data.index.map(lambda x: bool(re.fullmatch(r"\d{6}", x)))]
    data = data[~data.index.duplicated(keep="first")]
    if data.empty:
        raise ScanDataError("KRX 종목코드가 없습니다")
    for c in columns:
        data[c] = pd.to_numeric(data[c], errors="coerce")
    return data


def assemble_daily_snapshot(day, market, prices, investor_tables, min_coverage=DEFAULT_COVERAGE):
    """Validate universe completeness before producing an aligned daily panel."""
    if market not in MARKETS:
        raise ValueError("unsupported market")
    quotes = _tidy_tickers(prices, ("종가", "거래량"))
    quotes = quotes[(quotes["종가"] > 0) & (quotes["거래량"] > 0)].copy()
    if quotes.empty:
        raise ScanDataError(f"{market} {day}: 거래된 종목 없음")
    universe = len(quotes)
    quotes = quotes.rename(columns={"종가": "close", "거래량": "volume"})
    if "거래대금" in quotes:
        quotes["turnover"] = pd.to_numeric(quotes["거래대금"], errors="coerce")
        quotes["turnover_source"] = "KRX 거래대금"
    else:
        quotes["turnover"] = quotes["close"] * quotes["volume"]
        quotes["turnover_source"] = "종가×거래량 근사"
    quotes["turnover"] = quotes["turnover"].where(
        quotes["turnover"] > 0, quotes["close"] * quotes["volume"])
    quotes["price_change_pct"] = pd.to_numeric(
        quotes["등락률"], errors="coerce") if "등락률" in quotes else float("nan")
    quotes = quotes[["close", "volume", "turnover", "turnover_source", "price_change_pct"]]
    names = None
    coverages = {}
    for investor, prefix in INVESTORS.items():
        if investor not in investor_tables:
            raise ScanDataError(f"{market} {day}: {investor} 자료 누락")
        raw = _tidy_tickers(investor_tables[investor], REQUIRED_FLOW)
        present = int(quotes.index.isin(raw.index).sum())
        ratio = present / universe
        coverages[investor] = round(ratio, 4)
        if ratio < min_coverage:
            raise ScanDataError(
                f"{market} {day}: {investor} 자료의 종목 커버리지 "
                f"{ratio:.1%} (필요 {min_coverage:.0%}, {present}/{universe}); "
                "상위 순위만 제공된 것으로 판단되어 전종목 검색 중단")
        raw = raw.rename(columns={
            "순매수거래량": prefix + "_qty",
            "순매수거래대금": prefix + "_krw",
        })
        quotes = quotes.join(raw[[prefix + "_qty", prefix + "_krw"]], how="left")
        if names is None and "종목명" in raw.columns:
            names = raw["종목명"].astype(str)
    if names is not None:
        quotes["name"] = names.reindex(quotes.index)
    else:
        quotes["name"] = quotes.index
    quotes["name"] = quotes["name"].fillna(pd.Series(quotes.index, index=quotes.index))
    quotes["date"] = pd.Timestamp(day).normalize()
    quotes["market"] = market
    quotes["code"] = quotes.index
    return quotes.reset_index(drop=True), {
        "date": str(pd.Timestamp(day).date()),
        "market": market, "price_universe": universe,
        "aligned_tickers": int(quotes[list(
            prefix + "_qty" for prefix in INVESTORS.values()
        )].notna().all(axis=1).sum()),
        "investor_coverage": coverages,
    }


def discover_sessions(stock, end_day, history_sessions=25):
    """Use actual KRX KOSPI index trading-session timestamps, not weekdays."""
    end = pd.Timestamp(end_day).normalize()
    start = end - pd.Timedelta(days=max(65, history_sessions * 2 + 15))
    try:
        index = stock.get_index_ohlcv_by_date(
            start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), "1001")
    except Exception as exc:
        raise ScanDataError(
            "KRX 거래일 조회 실패 (" + type(exc).__name__ + "): "
            "회원 로그인 상태 또는 데이터 제공처 연결을 확인하세요"
        ) from exc
    if index is None or index.empty:
        raise ScanDataError("KRX 코스피 지수 거래일 캘린더 조회 실패")
    sessions = pd.DatetimeIndex(pd.to_datetime(index.index, errors="coerce")).normalize()
    sessions = sessions[~sessions.isna()].unique().sort_values()
    if end not in sessions:
        raise ScanDataError(f"{end.date()}: KRX 거래일이 아니거나 종가지수 미확정")
    if len(sessions) < history_sessions:
        raise ScanDataError(f"최근 {history_sessions}거래일 캘린더 부족")
    return [pd.Timestamp(t).normalize() for t in sessions[-history_sessions:]]


def fetch_market_panels(
    day, markets=MARKETS, lookback=10, min_coverage=DEFAULT_COVERAGE,
    per_call_delay=0.05, progress=None, stock_module=None,
):
    """Batch *all* stock rows by session/market, with coverage enforcement.

    KRX's ranking endpoint may expose only a top subset in some versions.
    That is detected against the daily traded-ticker universe, not concealed.
    """
    if lookback not in (10, 20):
        raise ValueError("lookback must be 10 or 20")
    markets = tuple(markets)
    if not markets or any(m not in MARKETS for m in markets):
        raise ValueError("Select at least one supported market")
    if stock_module is None:
        from krx_auth import krx_login_configured
        if not krx_login_configured():
            raise ScanDataError(
                "KRX 회원 계정 인증 필요: Streamlit Secrets 또는 서버 환경변수에 "
                "KRX_ID, KRX_PW를 안전하게 등록하세요. "
                "KRX_OPEN_API_KEY와는 별개입니다."
            )
        from pykrx import stock as stock_module
    dates = discover_sessions(stock_module, day, history_sessions=max(22, lookback + 4))
    panels = []
    quality = []
    total = len(dates) * len(markets)
    completed = 0
    for market in markets:
        for trading_day in dates:
            stamp = trading_day.strftime("%Y%m%d")
            try:
                prices = stock_module.get_market_ohlcv_by_ticker(stamp, market=market)
                investor_tables = {}
                for investor in INVESTORS:
                    investor_tables[investor] = stock_module.get_market_net_purchases_of_equities(
                        stamp, stamp, market, investor)
                    if per_call_delay > 0:
                        time.sleep(per_call_delay)
                panel, summary = assemble_daily_snapshot(
                    trading_day, market, prices, investor_tables,
                    min_coverage=min_coverage)
            except ScanDataError:
                raise
            except Exception as exc:
                raise ScanDataError(
                    f"{market} {trading_day.date()} KRX 접속 실패: {type(exc).__name__}"
                ) from exc
            panels.append(panel)
            quality.append(summary)
            completed += 1
            if progress is not None:
                progress(completed, total, f"{market} {stamp}")
    return pd.concat(panels, ignore_index=True), quality, dates


def _positive_last(row):
    return (float(row["personal_qty"]) < 0
            and float(row["personal_krw"]) < 0
            and float(row["foreign_qty"] + row["institution_qty"]) > 0
            and float(row["foreign_krw"] + row["institution_krw"]) > 0)


def evaluate_stock_rows(
    stock_rows, sessions, lookback=10, min_personal_buy_ratio=0.6,
    min_sell_multiple=2.0, min_personal_share=0.05,
    min_turnover=5_000_000_000,
):
    """Evaluate one symbol on an exactly aligned KRX session calendar."""
    frame = stock_rows.sort_values("date").set_index("date")
    required = (
        "personal_qty", "personal_krw", "foreign_qty", "foreign_krw",
        "institution_qty", "institution_krw", "close", "volume", "turnover",
    )
    calendar = pd.DatetimeIndex(sessions)
    if not calendar.isin(frame.index).all():
        return None
    frame = frame.reindex(calendar)
    if frame[list(required)].isna().any().any():
        return None
    target = frame.iloc[-1]
    history = frame.iloc[-(lookback + 1):-1]
    if len(history) != lookback:
        return None
    buyer_days = int((history["personal_qty"] > 0).sum())
    if buyer_days < ceil(lookback * min_personal_buy_ratio) or history["personal_qty"].sum() <= 0:
        return None
    if not _positive_last(target) or target["volume"] <= 0 or target["turnover"] < min_turnover:
        return None
    previous_abs = float(history["personal_qty"].abs().median())
    previous_volume = float(history["volume"].median())
    if previous_volume <= 0:
        return None
    multiple = abs(float(target["personal_qty"])) / max(previous_abs, previous_volume * 0.001)
    sell_share = abs(float(target["personal_qty"])) / float(target["volume"])
    if multiple < min_sell_multiple or sell_share < min_personal_share:
        return None
    buyer_qty = float(target["foreign_qty"] + target["institution_qty"])
    absorption = buyer_qty / abs(float(target["personal_qty"]))
    volume_multiple = float(target["volume"]) / previous_volume
    streak = 0
    for _, row in frame.iloc[::-1].iterrows():
        if _positive_last(row):
            streak += 1
        else:
            break
    price_history = frame["close"].tail(20)
    ma20 = float(price_history.mean()) if len(price_history) == 20 else None
    price_pos = float((target["close"] / ma20 - 1) * 100) if ma20 and ma20 > 0 else None
    strength = round(min(100,
        30 * buyer_days / lookback
        + 25 * min(multiple / 3, 1)
        + 30 * min(sell_share / 0.15, 1)
        + 15 * min(absorption, 1)))
    return {
        "code": str(target["code"]), "name": str(target["name"]),
        "market": str(target["market"]),
        "date": str(calendar[-1].date()),
        "transition": "신규 전환" if streak == 1 else f"{streak}거래일 연속 순매수 대응",
        "first_day": bool(streak == 1),
        "streak": int(streak),
        "personal_buy_days": buyer_days,
        "prior_days": lookback,
        "personal_qty": int(target["personal_qty"]),
        "foreign_qty": int(target["foreign_qty"]),
        "institution_qty": int(target["institution_qty"]),
        "personal_krw": int(target["personal_krw"]),
        "foreign_krw": int(target["foreign_krw"]),
        "institution_krw": int(target["institution_krw"]),
        "sell_multiple": round(multiple, 2),
        "sell_share_pct": round(sell_share * 100, 2),
        "absorption_pct": round(absorption * 100, 2),
        "volume_multiple": round(volume_multiple, 2),
        "close": int(target["close"]),
        "price_change_pct": (
            round(float(target["price_change_pct"]), 2)
            if pd.notna(target.get("price_change_pct")) else None
        ),
        "ma20_gap_pct": round(price_pos, 2) if price_pos is not None else None,
        "turnover_krw": int(target["turnover"]),
        "turnover_source": str(target["turnover_source"]),
        "strength": strength,
    }


def evaluate_market_panel(panel, dates, lookback=10, **kwargs):
    """Screen all aligned ticker rows, never narrowing via a top-N candidate list."""
    dates = pd.DatetimeIndex(dates)
    if panel.empty or len(dates) < max(22, lookback + 4):
        raise ScanDataError("필수 수급·가격 데이터가 부족합니다")
    if "market" not in panel or "code" not in panel:
        raise ScanDataError("종목 데이터 스키마 오류")
    output = []
    incomplete = 0
    asof = dates[-1]
    for (market, ticker), symbol in panel.groupby(["market", "code"], sort=False):
        if pd.Timestamp(asof) not in pd.DatetimeIndex(symbol["date"]):
            incomplete += 1
            continue
        hit = evaluate_stock_rows(symbol, dates, lookback=lookback, **kwargs)
        if hit is not None:
            output.append(hit)
    output.sort(key=lambda d: (d["first_day"], d["strength"],
                               abs(d["personal_krw"])), reverse=True)
    return output, {
        "scanned_tickers": int(panel.loc[panel["date"] == asof, ["market", "code"]].drop_duplicates().shape[0]),
        "missing_asof": incomplete,
        "matched_signals": len(output),
        "new_signals": sum(1 for r in output if r["first_day"]),
        "continuations": sum(1 for r in output if not r["first_day"]),
    }


def run_full_scan(
    day, markets=MARKETS, lookback=10, min_coverage=DEFAULT_COVERAGE,
    progress=None, stock_module=None, **kwargs
):
    panel, quality, dates = fetch_market_panels(
        day, markets=markets, lookback=lookback, min_coverage=min_coverage,
        progress=progress, stock_module=stock_module)
    hits, counts = evaluate_market_panel(panel, dates, lookback=lookback, **kwargs)
    return {
        "status": "success",
        "asof": str(dates[-1].date()),
        "generated_kst": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds"),
        "method": "KRX market-wide daily ticker batch, completeness-gated",
        "settings": {"markets": list(markets), "lookback": lookback, **kwargs},
        "totals": counts,
        "coverage": {
            "per_day_market": quality,
            "min_investor_coverage": min(
                value for row in quality
                for value in row["investor_coverage"].values()),
        },
        "results": hits,
    }
