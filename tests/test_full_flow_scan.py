"""Offline tests for whole-market, exact-date KRX flow scanner."""
import pandas as pd
import pytest

from full_flow_scan import (
    ScanDataError, assemble_daily_snapshot, discover_sessions,
    evaluate_market_panel, evaluate_stock_rows, run_full_scan,
)


def rows_on_day(day, ticker="005930", market="KOSPI", personal=1000, foreign=-700,
                institution=-300, close=100000, volume=100000):
    return {
        "date": pd.Timestamp(day), "market": market,
        "code": ticker, "name": "테스트 종목", "close": close,
        "volume": volume, "turnover": close * volume,
        "turnover_source": "종가×거래량 근사",
        "price_change_pct": 0.5,
        "personal_qty": personal, "personal_krw": personal * close,
        "foreign_qty": foreign, "foreign_krw": foreign * close,
        "institution_qty": institution, "institution_krw": institution * close,
    }


def synthetic_panel(n=24, continuous=1):
    days = pd.bdate_range(end="2026-11-09", periods=n)
    all_rows = []
    for i, day in enumerate(days):
        streak_i = n - 1 - i
        is_turn = streak_i < continuous
        all_rows.append(rows_on_day(
            day,
            personal=-8000 if is_turn else 1000,
            foreign=5000 if is_turn else -700,
            institution=3500 if is_turn else -300,
        ))
    return pd.DataFrame(all_rows), days


def test_new_reversal_full_universe_individual_market():
    panel, days = synthetic_panel()
    signals, counts = evaluate_market_panel(panel, days, lookback=10)
    assert counts["scanned_tickers"] == 1
    assert counts["new_signals"] == 1
    assert counts["continuations"] == 0
    signal = signals[0]
    assert signal["transition"] == "신규 전환"
    assert signal["streak"] == 1
    assert signal["personal_buy_days"] == 10
    assert signal["ma20_gap_pct"] == 0
    assert signal["turnover_krw"] == 10_000_000_000


def test_second_day_new_flag_is_false():
    panel, dates = synthetic_panel(24, continuous=2)
    hits, stats = evaluate_market_panel(panel, dates, lookback=10)
    assert stats["new_signals"] == 0
    assert stats["continuations"] == 1
    assert hits[0]["streak"] == 2
    assert hits[0]["first_day"] is False


def test_gapped_history_not_shifted_backward():
    panel, dates = synthetic_panel()
    panel = panel[panel["date"] != dates[-4]].copy()
    assert evaluate_stock_rows(panel, dates, lookback=10) is None


def test_sale_without_value_confirmation_rejected():
    panel, dates = synthetic_panel()
    panel.loc[panel["date"] == dates[-1], "personal_krw"] = +5000
    assert evaluate_stock_rows(panel, dates, lookback=10) is None


def test_20_day_setting_requires_history():
    panel, dates = synthetic_panel()
    assert evaluate_stock_rows(panel, dates, lookback=20) is not None
    assert evaluate_stock_rows(panel.tail(15), dates, lookback=20) is None


def market_tables(tickers=("005930", "000660", "035420"), missing=()):
    index = pd.Index(list(tickers), name="티커")
    prices = pd.DataFrame({
        "종가": [100000] * len(index),
        "거래량": [100000] * len(index),
        "거래대금": [10_000_000_000] * len(index),
    }, index=index)
    flow = pd.DataFrame({
        "종목명": ["테스트"] * len(index),
        "순매수거래량": [1000] * len(index),
        "순매수거래대금": [100000000] * len(index),
    }, index=index)
    feeds = {key: flow.copy() for key in ("개인", "외국인", "기관합계")}
    for investor in missing:
        feeds[investor] = feeds[investor].iloc[:1]
    return prices, feeds


def test_all_ticker_coverage_marketwise():
    quotes, tables = market_tables()
    frame, quality = assemble_daily_snapshot(
        "2026-11-09", "KOSPI", quotes, tables)
    assert len(frame) == 3
    assert quality["price_universe"] == 3
    assert quality["aligned_tickers"] == 3
    assert quality["investor_coverage"]["개인"] == 1


def test_rejects_rank_only_response_instead_of_claiming_full_market():
    quotes, tables = market_tables(missing=("외국인",))
    with pytest.raises(ScanDataError, match="커버리지"):
        assemble_daily_snapshot("2026-11-09", "KOSPI", quotes, tables)


def test_rejects_empty_source_instead_of_false_zero_signals():
    quotes, tables = market_tables()
    tables["기관합계"] = pd.DataFrame()
    with pytest.raises(ScanDataError, match="빈 응답"):
        assemble_daily_snapshot("2026-11-09", "KOSPI", quotes, tables)


class FakeStock:
    def __init__(self):
        self.calls = []
        self.sessions = pd.bdate_range(end="2026-11-09", periods=24)

    def get_index_ohlcv_by_date(self, first, last, code):
        return pd.DataFrame({"종가": [1] * len(self.sessions)}, index=self.sessions)

    def get_market_ohlcv_by_ticker(self, date, market):
        self.calls.append(("prices", date, market))
        p, _ = market_tables()
        return p

    def get_market_net_purchases_of_equities(self, first, last, market, investor):
        self.calls.append((investor, first, market))
        _, f = market_tables()
        # Last session reverses; the synthetic feed is market wide.
        if first == "20261109":
            f["개인"]["순매수거래량"] = -8000
            f["개인"]["순매수거래대금"] = -800000000
            f["외국인"]["순매수거래량"] = 5000
            f["외국인"]["순매수거래대금"] = 500000000
            f["기관합계"]["순매수거래량"] = 3500
            f["기관합계"]["순매수거래대금"] = 350000000
        return f[investor]


def test_full_scan_uses_marketwide_batch_calls_and_returns_data():
    mock = FakeStock()
    result = run_full_scan("2026-11-09", markets=("KOSPI",),
                           stock_module=mock, lookback=10)
    assert result["status"] == "success"
    assert result["totals"]["scanned_tickers"] == 3
    assert result["totals"]["new_signals"] == 3
    assert result["coverage"]["min_investor_coverage"] == 1
    assert len(mock.calls) == 24 * 4


def test_no_holiday_fake_trading_date_passes():
    mock = FakeStock()
    with pytest.raises(ScanDataError, match="거래일"):
        discover_sessions(mock, "2026-11-08")
