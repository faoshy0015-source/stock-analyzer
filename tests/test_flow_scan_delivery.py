"""No-network tests for private results and Telegram alert formatting."""
from datetime import date
from unittest.mock import Mock

import pytest

import flow_scan_delivery as delivery


def example_report():
    return {
        "asof": "2026-11-09",
        "totals": {"scanned_tickers": 3000, "new_signals": 1,
                   "continuations": 1},
        "results": [
            {"first_day": True, "code": "005930", "name": "테스트",
             "market": "KOSPI", "personal_qty": -8000,
             "foreign_qty": 5000, "institution_qty": 3500,
             "sell_multiple": 8, "strength": 87},
            {"first_day": False, "code": "035420", "name": "다른테스트",
             "market": "KOSPI", "personal_qty": -5000,
             "foreign_qty": 4000, "institution_qty": 1200,
             "sell_multiple": 5, "strength": 80},
        ],
    }


def test_alert_only_lists_first_day_and_names_basis():
    message = delivery.alert_text(example_report())
    assert "2026-11-09" in message
    assert "005930" in message
    assert "035420" not in message
    assert "KRX" in message


def test_no_credentials_does_not_make_network_calls(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("No request expected")
    monkeypatch.setattr(delivery.requests, "post", fail)
    monkeypatch.setattr(delivery.requests, "get", fail)
    assert delivery.persist_scan(example_report(), env={}) is False
    assert delivery.read_latest_scan(env={}) is None
    assert delivery.already_notified("2026-11-09", env={}) is False
    assert delivery.send_telegram("hi", env={}) is False


def test_supabase_key_only_in_headers_not_querystring(monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return Mock(ok=True, status_code=201)

    monkeypatch.setattr(delivery.requests, "post", fake_post)
    assert delivery.persist_scan(
        example_report(), env={
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "private-token",
        })
    assert "private-token" not in calls[0][0]
    assert calls[0][1]["headers"]["apikey"] == "private-token"
    assert calls[0][1]["json"]["run_date"] == "2026-11-09"


def test_telegram_send_message_is_opt_in(monkeypatch):
    def fake_post(url, **kwargs):
        assert "token" in url
        assert kwargs["data"]["chat_id"] == "123"
        return Mock(ok=True, status_code=200,
                    json=lambda: {"ok": True})

    monkeypatch.setattr(delivery.requests, "post", fake_post)
    assert delivery.send_telegram(
        "hello", env={"TELEGRAM_BOT_TOKEN": "token",
                       "TELEGRAM_CHAT_ID": "123"}) is True


def test_telegram_failure_is_sanitized(monkeypatch):
    def fake_post(url, **kwargs):
        return Mock(ok=False, status_code=401)

    monkeypatch.setattr(delivery.requests, "post", fake_post)
    with pytest.raises(RuntimeError, match="전송 실패"):
        delivery.send_telegram(
            "hello", env={"TELEGRAM_BOT_TOKEN": "superprivate",
                           "TELEGRAM_CHAT_ID": "123"})
