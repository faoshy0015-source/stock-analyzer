"""Npay valuation extraction tests — never confuse annual EPS and BPS."""
from unittest.mock import Mock

from naver_valuation import (
    _checked_pairs,
    _number,
    fetch_naver_valuation,
    parse_naver_annual,
    parse_naver_integration,
)


def _forecast_payload():
    return {
        "financeInfo": {
            "trTitleList": [
                {"title": "2025.12.", "key": "202512", "isConsensus": "N"},
                {"title": "2026.12.", "key": "202612", "isConsensus": "Y"},
                {"title": "2027.12.", "key": "202712", "isConsensus": "Y"},
            ],
            "rowList": [
                {"title": "EPS(원)", "columns": {
                    "202512": {"value": "6,564"},
                    "202612": {"value": "45,655"},
                    "202712": {"value": "73,055"},
                }},
                {"title": "BPS(원)", "columns": {
                    "202512": {"value": "63,997"},
                    "202612": {"value": "108,381"},
                    "202712": {"value": "171,196"},
                }},
                {"title": "PER(배)", "columns": {
                    "202612": {"value": "4.51"},
                    "202712": {"value": "2.82"},
                }},
            ],
        }
    }


def test_year_labeled_eps_bps_are_distinct_and_consensus_only():
    rows = parse_naver_annual(_forecast_payload(), current_year=2026)
    assert sorted(rows) == [2026, 2027]
    assert rows[2026]["eps"] == 45655
    assert rows[2026]["bps"] == 108381
    assert rows[2027]["eps"] == 73055
    assert rows[2027]["bps"] == 171196
    assert rows[2026]["reported_per"] == 4.51
    assert 2025 not in rows


def test_only_explicit_consensus_years_appear():
    payload = _forecast_payload()
    payload["financeInfo"]["trTitleList"][1]["isConsensus"] = "N"
    rows = parse_naver_annual(payload, current_year=2026)
    assert list(rows) == [2027]


def test_no_forecast_when_columns_missing():
    payload = {"financeInfo": {"trTitleList": [
        {"key": "202612", "title": "2026.12.", "isConsensus": "Y"}],
        "rowList": [{"title": "EPS", "columns": {"202612": {"value": "--"}}}]}}
    assert parse_naver_annual(payload, current_year=2026) == {}


def test_integration_parses_only_supported_metric_codes():
    values = parse_naver_integration({
        "totalInfos": [
            {"code": "eps", "value": "22,292원"},
            {"code": "bps", "value": "86,052원"},
            {"code": "per", "value": "9.24배"},
            {"code": "pbr", "value": "2.39배"},
            {"code": "marketValue", "value": "1,000조"},
        ]
    })
    assert values == {"eps": 22292, "bps": 86052, "per": 9.24, "pbr": 2.39}
    assert _number("삼성전자") is None
    assert _number("nan") is None


def test_conflicting_current_eps_and_per_are_not_shown_together():
    values = {"per": 31.19, "eps": 6605, "pbr": 3.22, "bps": 63997}
    warnings = _checked_pairs(values, 206000)
    # A pair implying a price within 20% is arithmetically plausible even if
    # it represents an outdated accounting basis — flag sources separately.
    assert warnings == []
    assert values["eps"] == 6605


def test_forecast_per_uses_annual_eps_not_bps(monkeypatch):
    import naver_valuation as module

    def response(payload):
        obj = Mock()
        obj.raise_for_status.return_value = None
        obj.json.return_value = payload
        return obj

    def fake_get(url, **kwargs):
        if url.endswith("/integration"):
            return response({"totalInfos": [
                {"code": "per", "value": "9.24배"},
                {"code": "eps", "value": "22,292원"},
            ]})
        if url.endswith("/finance/annual"):
            return response(_forecast_payload())
        if url.endswith("/basic"):
            return response({"closePrice": "206,000",
                             "localTradedAt": "2026-11-12T10:30:00+09:00"})
        raise AssertionError(url)

    monkeypatch.setattr(module.requests, "get", fake_get)
    from datetime import datetime as RealDateTime
    class FixedDateTime:
        @staticmethod
        def now(tz=None):
            return RealDateTime(2026, 11, 12, 10, 30, tzinfo=tz)
    monkeypatch.setattr(module, "datetime", FixedDateTime)
    result = fetch_naver_valuation("005930")
    assert result["annual_forecasts"][2026]["eps"] == 45655
    assert result["annual_forecasts"][2026]["bps"] == 108381
    assert result["annual_forecasts"][2026]["current_price_per"] == 4.51
    assert result["annual_forecasts"][2027]["current_price_per"] == 2.82
    assert result["quote_time"].endswith("KST")
