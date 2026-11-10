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


def test_rank_only_response_retained_as_partial_with_explicit_missing_rows():
    quotes, tables = market_tables(missing=("외국인",))
    frame, quality = assemble_daily_snapshot("2026-11-09", "KOSPI", quotes, tables)
    assert quality["investor_coverage"]["외국인"] == round(1/3, 4)
    assert quality["aligned_tickers"] == 1
    assert frame["foreign_qty"].isna().sum() == 2


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
    assert len(mock.calls) == 11 * 4  # requested 10 previous + asof, not 22 extraneous dates


def test_no_holiday_fake_trading_date_passes():
    mock = FakeStock()
    with pytest.raises(ScanDataError, match="거래일"):
        discover_sessions(mock, "2026-11-08")


def test_market_coverage_95_percent_can_be_screened_without_filling_missing_rows():
    # A real screenshot showed 852/891=95.6% but an arbitrary 98% gate
    # aborted before any symbol could be checked.
    universe = tuple(f"{n:06d}" for n in range(100))
    quotes, feeds = market_tables(tickers=universe)
    feeds["기관합계"] = feeds["기관합계"].iloc[:95]
    panel, quality = assemble_daily_snapshot(
        "2026-11-09", "KOSPI", quotes, feeds, min_coverage=0.90)
    assert quality["investor_coverage"]["기관합계"] == 0.95
    assert quality["aligned_tickers"] == 95
    assert panel["institution_qty"].isna().sum() == 5


def test_low_ranked_response_still_fails_under_ninety_percent():
    universe = tuple(f"{n:06d}" for n in range(100))
    quotes, feeds = market_tables(tickers=universe)
    feeds["기관합계"] = feeds["기관합계"].iloc[:85]
    with pytest.raises(ScanDataError, match="커버리지"):
        assemble_daily_snapshot(
            "2026-11-09", "KOSPI", quotes, feeds, min_coverage=0.90)


def test_eligible_count_excludes_any_stock_with_missing_required_session():
    complete, dates = synthetic_panel()
    partial = complete.copy()
    partial["code"] = "000001"
    partial["name"] = "불완비 종목"
    partial.loc[partial["date"] == dates[-4], "personal_qty"] = float("nan")
    together = pd.concat([complete, partial], ignore_index=True)
    matches, counts = evaluate_market_panel(together, dates, lookback=10)
    assert counts["scanned_tickers"] == 2
    assert counts["eligible_tickers"] == 1
    assert counts["excluded_incomplete_tickers"] == 1
    assert counts["eligible_ratio"] == 0.5
    assert len(matches) == 1
    assert matches[0]["code"] == "005930"


def test_missing_old_session_not_in_10_day_window_does_not_block_signal():
    panel, dates = synthetic_panel()
    # More remote missing data should not disqualify the exact last 10 days.
    old_date = dates[-19]
    panel = panel.loc[panel["date"] != old_date]
    signal = evaluate_stock_rows(panel, dates, lookback=10)
    assert signal is not None
    assert signal["first_day"] is True


def test_streak_breaks_on_missing_older_calendar_session():
    panel, dates = synthetic_panel(24, continuous=3)
    # Today's reversal and previous day are present; 2 days ago is missing.
    panel = panel[panel["date"] != dates[-3]]
    # 10-day signal must fail because date itself is required, never fabricate.
    assert evaluate_stock_rows(panel, dates, lookback=10) is None


def test_oct21_partial_krx_day_at_889pct_does_not_abort_price_universe():
    # Screenshot: KOSDAQ 2026-10-21 price universe 1,674,
    # institution ranking response for 1,488 (88.9%).
    universe = tuple(f"{n:06d}" for n in range(1674))
    quotes, feeds = market_tables(tickers=universe)
    feeds["기관합계"] = feeds["기관합계"].iloc[:1488]
    daily, quality = assemble_daily_snapshot(
        "2026-10-21", "KOSDAQ", quotes, feeds)
    assert len(daily) == 1674
    assert quality["aligned_tickers"] == 1488
    assert quality["investor_coverage"]["기관합계"] == 0.8889
    assert daily["institution_qty"].isna().sum() == 186
    # Ranking omissions are not the same as zero institutional net buying.
    assert daily["institution_qty"].isna().sum() != 0


def test_date_aligned_market_scan_is_partial_not_failed_when_rankings_incomplete():
    class PartiallyCoveredStock(FakeStock):
        def get_market_net_purchases_of_equities(self, first, last, market, investor):
            base = super().get_market_net_purchases_of_equities(first, last, market, investor)
            if investor == "기관합계":
                return base.iloc[:2]
            return base
    broker = PartiallyCoveredStock()
    report = run_full_scan(
        "2026-11-09", markets=("KOSPI",), lookback=10, stock_module=broker)
    assert report["status"] == "partial"
    assert report["totals"]["scanned_tickers"] == 3
    assert report["totals"]["eligible_tickers"] == 2
    assert report["totals"]["excluded_incomplete_tickers"] == 1
    assert report["coverage"]["min_investor_coverage"] < 1.0
    assert len(broker.calls) == 11 * 4


def test_only_requested_sessions_are_required_for_20_day_scan():
    broker = FakeStock()
    report = run_full_scan(
        "2026-11-09", markets=("KOSPI",), lookback=20, stock_module=broker)
    assert report["status"] == "success"
    assert len(broker.calls) == 21 * 4


def test_date_outside_10_day_window_not_fetched_or_causes_abort():
    class OldDayIncomplete(FakeStock):
        def get_market_net_purchases_of_equities(self, first, last, market, investor):
            assert first != self.sessions[-16].strftime("%Y%m%d")
            return super().get_market_net_purchases_of_equities(
                first, last, market, investor)
    broker = OldDayIncomplete()
    result = run_full_scan(
        "2026-11-09", markets=("KOSPI",), lookback=10, stock_module=broker)
    assert result["status"] == "success"
