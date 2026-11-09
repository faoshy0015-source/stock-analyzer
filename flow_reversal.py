"""Investor-flow reversal screener for Korean equities.

All signals are end-of-day and use date-aligned KRX net *share counts*.
The first-stage candidate pool comes from foreign/institution net-buy rankings,
so it is not an exhaustive scan of every listed security.
"""
from __future__ import annotations

from datetime import date, timedelta
from math import isfinite
import re

import pandas as pd

PARTICIPANTS = ("개인", "외국인합계", "기관합계")
REQUIRED_PRICE_COLUMNS = ("거래량", "종가")


def _normalized(frame, columns):
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return pd.DataFrame(columns=list(columns))
    if any(column not in frame.columns for column in columns):
        return pd.DataFrame(columns=list(columns))
    data = frame.loc[:, list(columns)].copy()
    data.index = pd.to_datetime(data.index, errors="coerce")
    data = data.loc[data.index.notna()]
    if getattr(data.index, "tz", None) is not None:
        data.index = data.index.tz_localize(None)
    data.index = data.index.normalize()
    data = data.loc[~data.index.duplicated(keep="last")].sort_index()
    for column in columns:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    return data.dropna(subset=list(columns))


def assess_reversal(
    volumes,
    values,
    prices,
    asof,
    lookback=10,
    min_buy_days_ratio=0.6,
    min_sell_multiple=2.0,
    min_sell_share=0.05,
    min_turnover=5_000_000_000,
):
    """Return a matched signal or None, never fabricate missing/stale sessions.

    A signal requires: personal net buying on >=60% of prior sessions AND net
    buying overall, exceptional personal net selling today, institutional or
    foreign positive net buying as a group, and meaningful liquidity.
    """
    if lookback not in (10, 20):
        raise ValueError("lookback must be 10 or 20")
    target = pd.Timestamp(asof).normalize()
    qty = _normalized(volumes, PARTICIPANTS)
    money = _normalized(values, PARTICIPANTS)
    px = _normalized(prices, REQUIRED_PRICE_COLUMNS)
    if target not in qty.index or target not in money.index or target not in px.index:
        return None

    # The official price series determines the actual last N market sessions.
    # If any investor report is missing in that exact window, reject it rather
    # than silently substituting an older session.
    recent_sessions = px.loc[px.index <= target].tail(lookback + 1)
    if len(recent_sessions) != lookback + 1 or recent_sessions.index[-1] != target:
        return None
    joined = qty.rename(columns={c: c + "_qty" for c in PARTICIPANTS})
    joined = joined.join(money.rename(columns={c: c + "_krw" for c in PARTICIPANTS}),
                         how="inner").join(px, how="inner")
    if not recent_sessions.index.isin(joined.index).all():
        return None
    history = joined.loc[recent_sessions.index[:-1]]
    today = joined.loc[target]
    if isinstance(today, pd.DataFrame):
        return None

    person_prev = history["개인_qty"]
    days_bought = int((person_prev > 0).sum())
    if days_bought < int(lookback * min_buy_days_ratio + 0.999999):
        return None
    if float(person_prev.sum()) <= 0:
        return None

    individual = float(today["개인_qty"])
    foreign = float(today["외국인합계_qty"])
    institution = float(today["기관합계_qty"])
    buyers = foreign + institution
    daily_volume = float(today["거래량"])
    close = float(today["종가"])
    if not all(isfinite(x) for x in (individual, foreign, institution, daily_volume, close)):
        return None
    if individual >= 0 or buyers <= 0 or daily_volume <= 0 or close <= 0:
        return None

    # Median personal daily net activity (not trade volume) is the reference.
    # A small floor relative to historic total volume prevents exploding
    # multiples when prior net activity is near zero.
    baseline_volume = float(history["거래량"].median())
    if baseline_volume <= 0:
        return None
    baseline_net = float(person_prev.abs().median())
    denominator = max(baseline_net, baseline_volume * 0.001)
    multiple = abs(individual) / denominator
    selling_share = abs(individual) / daily_volume
    approximate_turnover = close * daily_volume  # explicitly NOT official turnover
    if (multiple < min_sell_multiple or selling_share < min_sell_share
            or approximate_turnover < min_turnover):
        return None

    net_foreign_krw = float(today["외국인합계_krw"])
    net_institution_krw = float(today["기관합계_krw"])
    net_person_krw = float(today["개인_krw"])
    if net_person_krw >= 0 or net_foreign_krw + net_institution_krw <= 0:
        return None
    # Positive group net value/qty needed; one buyer can offset the other.
    absorption = buyers / abs(individual)
    volume_ratio = daily_volume / baseline_volume
    # Ranking aid only, not a projected return or entry recommendation.
    strength = round(min(100,
        30 * days_bought / lookback
        + 25 * min(multiple / 3, 1)
        + 30 * min(selling_share / 0.15, 1)
        + 15 * min(absorption, 1)))
    return {
        "date": target.strftime("%Y-%m-%d"),
        "personal_buy_days": days_bought,
        "prior_days": lookback,
        "prior_personal_net_qty": int(person_prev.sum()),
        "personal_net_qty": int(individual),
        "foreign_net_qty": int(foreign),
        "institution_net_qty": int(institution),
        "buyer_net_qty": int(buyers),
        "personal_net_krw": int(net_person_krw),
        "foreign_net_krw": int(net_foreign_krw),
        "institution_net_krw": int(net_institution_krw),
        "personal_sell_multiple": round(multiple, 2),
        "personal_sell_share_pct": round(selling_share * 100, 2),
        "buyer_absorption_pct": round(absorption * 100, 2),
        "volume_ratio": round(volume_ratio, 2),
        "price": int(close),
        "approx_turnover_krw": int(approximate_turnover),
        "strength": strength,
        "strength_label": "강한 전환" if (multiple >= 3 and selling_share >= 0.1 and
                                           days_bought >= 0.7 * lookback) else "전환 관찰",
    }


def load_candidates(day, markets=("KOSPI", "KOSDAQ"), each_investor=20):
    """Build an explicitly non-exhaustive candidate pool via KRX net buyers.

    One API ranking may include only a subset of the market. Do not describe
    the result as an all-listed-stock screening or a guaranteed complete list.
    """
    from pykrx import stock

    stamp = pd.Timestamp(day).strftime("%Y%m%d")
    items = {}
    notices = []
    successful_calls = 0
    for market in markets:
        for investor in ("외국인", "기관합계"):
            try:
                data = stock.get_market_net_purchases_of_equities(
                    stamp, stamp, market, investor)
                if data is None or data.empty:
                    notices.append(f"{market} {investor}: 수급 순위 응답 없음")
                    continue
                if not {"순매수거래량", "순매수거래대금"}.issubset(data.columns):
                    notices.append(f"{market} {investor}: 수급 열 구조 불일치")
                    continue
                successful_calls += 1
                ranked = data.copy()
                ranked["순매수거래량"] = pd.to_numeric(
                    ranked["순매수거래량"], errors="coerce")
                ranked["순매수거래대금"] = pd.to_numeric(
                    ranked["순매수거래대금"], errors="coerce")
                ranked = ranked[(ranked["순매수거래량"] > 0)
                                & (ranked["순매수거래대금"] > 0)]
                # Diversify volume and value rankings, since prices differ.
                half = max(1, each_investor // 2)
                chosen = pd.concat([
                    ranked.nlargest(half, "순매수거래량"),
                    ranked.nlargest(each_investor - half, "순매수거래대금"),
                ]).loc[lambda df: ~df.index.duplicated(keep="first")]
                for ticker, row in chosen.iterrows():
                    code = str(ticker).zfill(6)
                    if not re.fullmatch(r"\d{6}", code):
                        continue
                    if code not in items:
                        items[code] = {
                            "code": code,
                            "name": str(row.get("종목명") or code),
                            "market": market,
                            "candidate_net_krw": 0,
                        }
                    items[code]["candidate_net_krw"] += max(
                        0, int(row["순매수거래대금"]))
            except Exception as exc:
                notices.append(f"{market} {investor}: {type(exc).__name__} 조회 오류")
    candidates = sorted(
        items.values(), key=lambda x: x["candidate_net_krw"], reverse=True)
    return candidates, notices, successful_calls


def load_stock_history(code, end_day, calendar_days=65):
    """Fetch exact-date net investor flow and KRX daily OHLCV for one ticker."""
    from pykrx import stock

    end = pd.Timestamp(end_day).date()
    start = end - timedelta(days=calendar_days)
    first, last = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
    shares = stock.get_market_trading_volume_by_date(first, last, code)
    values = stock.get_market_trading_value_by_date(first, last, code)
    prices = stock.get_market_ohlcv_by_date(first, last, code)
    return shares, values, prices
