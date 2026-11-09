"""Deterministic, offline checks for investor flow reversal."""
import pandas as pd

from flow_reversal import assess_reversal


def sample(n=11):
    idx = pd.bdate_range(end="2026-11-09", periods=n)
    personal = [1000] * (n - 1) + [-8000]
    foreign = [-700] * (n - 1) + [5000]
    institution = [-300] * (n - 1) + [3500]
    volumes = pd.DataFrame({
        "개인": personal, "외국인합계": foreign, "기관합계": institution,
    }, index=idx)
    values = volumes * 100000
    prices = pd.DataFrame({
        "거래량": [90000] * (n - 1) + [100000],
        "종가": [100000] * n,
    }, index=idx)
    return volumes, values, prices, idx[-1]


def test_detects_personal_buy_to_heavy_sell_and_institutional_buy():
    shares, amounts, prices, day = sample()
    found = assess_reversal(shares, amounts, prices, day)
    assert found is not None
    assert found["personal_buy_days"] == 10
    assert found["personal_net_qty"] == -8000
    assert found["foreign_net_qty"] == 5000
    assert found["institution_net_qty"] == 3500
    assert found["personal_sell_multiple"] == 8
    assert found["personal_sell_share_pct"] == 8
    assert 0 <= found["strength"] <= 100


def test_requires_same_date_for_price_quantity_and_value():
    shares, amounts, prices, day = sample()
    assert assess_reversal(shares, amounts.iloc[:-1], prices, day) is None
    assert assess_reversal(shares.iloc[:-1], amounts, prices, day) is None
    assert assess_reversal(shares, amounts, prices.iloc[:-1], day) is None


def test_rejects_previous_period_without_individual_buy_dominance():
    shares, amounts, prices, day = sample()
    shares.iloc[:6, shares.columns.get_loc("개인")] = -1000
    assert assess_reversal(shares, amounts, prices, day) is None


def test_rejects_without_large_personal_net_selling():
    shares, amounts, prices, day = sample()
    shares.loc[day, "개인"] = -1000  # 1% of today's total trading volume
    amounts.loc[day, "개인"] = -1000 * 100000
    assert assess_reversal(shares, amounts, prices, day) is None


def test_rejects_foreign_and_institution_sellers():
    shares, amounts, prices, day = sample()
    shares.loc[day, "외국인합계"] = -500
    shares.loc[day, "기관합계"] = -500
    assert assess_reversal(shares, amounts, prices, day) is None


def test_can_qualify_with_one_buyer_group_if_combined_net_positive():
    shares, amounts, prices, day = sample()
    shares.loc[day, "외국인합계"] = -200
    shares.loc[day, "기관합계"] = 9000
    amounts.loc[day, "외국인합계"] = -200 * 100000
    amounts.loc[day, "기관합계"] = 9000 * 100000
    assert assess_reversal(shares, amounts, prices, day) is not None


def test_rejects_low_liquidity_using_explicit_close_times_volume_proxy():
    shares, amounts, prices, day = sample()
    prices.loc[day, "종가"] = 10000
    assert assess_reversal(shares, amounts, prices, day) is None


def test_requires_exact_lookback_count():
    shares, amounts, prices, day = sample()
    assert assess_reversal(shares, amounts, prices, day, lookback=20) is None
    shares, amounts, prices, day = sample(21)
    found = assess_reversal(shares, amounts, prices, day, lookback=20)
    assert found is not None
    assert found["personal_buy_days"] == 20


def test_rejects_mixed_cash_share_direction():
    shares, amounts, prices, day = sample()
    amounts.loc[day, "개인"] = +500000
    assert assess_reversal(shares, amounts, prices, day) is None


def test_no_future_date_from_latest_data():
    shares, amounts, prices, day = sample()
    assert assess_reversal(shares, amounts, prices, day + pd.Timedelta(days=1)) is None


def test_incomplete_middle_session_not_replaced_with_older_session():
    shares, amounts, prices, day = sample(12)
    missing = prices.index[-3]
    amounts = amounts.drop(index=missing)
    # There are still ten old joined reports, but the actual preceding
    # ten trading sessions include the missing date.
    assert assess_reversal(shares, amounts, prices, day) is None
