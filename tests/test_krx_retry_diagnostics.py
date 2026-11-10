"""Offline fault-injection tests for KRX retry and source diagnostics."""
import pandas as pd
import pytest

from full_flow_scan import ScanDataError, _krx_retry_call, fetch_market_panels


def test_krx_retry_recovers_from_transient_empty_response():
    attempts = []
    waits = []

    def fetch():
        attempts.append(1)
        if len(attempts) == 1:
            return pd.DataFrame()
        return pd.DataFrame({"종가": [100]}, index=["005930"])

    got = _krx_retry_call(
        fetch, market="KOSPI", day="2026-11-09",
        dataset="개인 순매수 수량·대금", attempts=3,
        backoff_seconds=0.2, sleep=waits.append,
    )
    assert len(attempts) == 2
    assert waits == [0.2]
    assert not got.empty


def test_krx_retry_permanently_empty_reports_market_day_and_type():
    attempted = []
    with pytest.raises(ScanDataError) as ctx:
        _krx_retry_call(
            lambda: attempted.append(True) or pd.DataFrame(),
            market="KOSDAQ", day="2026-10-21",
            dataset="기관합계 순매수 수량·대금",
            attempts=3, backoff_seconds=0, sleep=lambda _: None,
        )
    msg = str(ctx.value)
    assert len(attempted) == 3
    assert "KOSDAQ" in msg
    assert "2026-10-21" in msg
    assert "기관합계" in msg
    assert "3회 시도" in msg
    assert "빈 응답" in msg


def test_krx_retry_recovers_after_exception_without_leaking_detail():
    attempts = []
    def fetch():
        attempts.append(1)
        if len(attempts) < 3:
            raise ConnectionError("token secret should not be logged")
        return pd.DataFrame({"값": [1]})
    got = _krx_retry_call(
        fetch, market="KOSPI", day="2026-11-09",
        dataset="거래일 지수 캘린더", attempts=3,
        backoff_seconds=0, sleep=lambda _: None,
    )
    assert not got.empty and len(attempts) == 3


class FlakyStock:
    def __init__(self, always_empty=False):
        self.sessions = pd.bdate_range(end="2026-11-09", periods=24)
        self.calls = []
        self.always_empty = always_empty
        self.target_day = self.sessions[-11].strftime("%Y%m%d")
        self.flaky_calls = 0

    def get_index_ohlcv_by_date(self, first, last, code):
        return pd.DataFrame({"종가": [1] * len(self.sessions)}, index=self.sessions)

    def get_market_ohlcv_by_ticker(self, stamp, market):
        index = pd.Index(["005930", "000660", "035420"], name="티커")
        return pd.DataFrame({
            "종가": [100000] * 3, "거래량": [100000] * 3,
            "거래대금": [10_000_000_000] * 3,
        }, index=index)

    def get_market_net_purchases_of_equities(self, first, last, market, investor):
        self.calls.append((first, market, investor))
        if first == self.target_day and investor == "외국인":
            self.flaky_calls += 1
            if self.always_empty or self.flaky_calls == 1:
                return pd.DataFrame()
        data = pd.DataFrame({
            "종목명": ["테스트"] * 3,
            "순매수거래량": [1000] * 3,
            "순매수거래대금": [100_000_000] * 3,
        }, index=pd.Index(["005930", "000660", "035420"], name="티커"))
        return data


def test_full_market_retries_one_empty_investor_feed_without_losing_day():
    stock = FlakyStock()
    panel, quality, dates = fetch_market_panels(
        "2026-11-09", markets=("KOSPI",), lookback=10,
        per_call_delay=0, retry_backoff_seconds=0,
        stock_module=stock)
    assert stock.flaky_calls == 2
    assert len(quality) == 11
    assert len(panel) == 33
    assert len(dates) == 11


def test_full_market_permanent_empty_reports_exact_failed_source():
    stock = FlakyStock(always_empty=True)
    with pytest.raises(ScanDataError) as ctx:
        fetch_market_panels(
            "2026-11-09", markets=("KOSPI",), lookback=10,
            per_call_delay=0, retry_backoff_seconds=0,
            stock_module=stock)
    assert stock.flaky_calls == 3
    msg = str(ctx.value)
    assert "KOSPI" in msg
    assert "외국인" in msg
    assert stock.sessions[-22].strftime("%Y-%m-%d") in msg
    assert "빈 응답" in msg
