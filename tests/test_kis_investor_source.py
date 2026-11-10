"""Offline contract tests for the KIS investor-flow read-only fallback."""
from __future__ import annotations

from datetime import date
from unittest.mock import Mock

import pytest

from kis_investor_source import (
    KisInvestorError, normalize_kis_investor_response,
    fetch_kis_investor_history, KIS_INVESTOR_TR_ID,
)


def sample():
    return {
        "rt_cd": "0",
        "output1": [{"irrelevant": "aggregate"}],
        "output2": [
            {"stck_bsop_date": "20261106", "prsn_ntby_qty": "150",
             "frgn_ntby_qty": "-200", "orgn_ntby_qty": "50"},
            {"stck_bsop_date": "20261109", "prsn_ntby_qty": "-800",
             "frgn_ntby_qty": "600", "orgn_ntby_qty": "150"},
            {"stck_bsop_date": "20261110", "prsn_ntby_qty": "0",
             "frgn_ntby_qty": "0", "orgn_ntby_qty": "0"},
        ]
    }


def test_date_and_quantity_fields_are_real_not_estimated():
    df = normalize_kis_investor_response(sample(), "005930", "2026-11-09")
    assert len(df) == 2
    assert df.iloc[-1]["개인 순매수(주)"] == -800
    assert df.iloc[-1]["외국인 순매수(주)"] == 600
    assert df.iloc[-1]["기관 순매수(주)"] == 150
    assert "개인 순매수(억원)" not in df


def test_missing_quantity_is_not_backfilled_with_zero():
    p = sample()
    p["output2"][1]["prsn_ntby_qty"] = ""
    df = normalize_kis_investor_response(p, "005930", "2026-11-09")
    assert len(df) == 1


def test_auth_denial_is_not_treated_as_empty_list():
    p = sample()
    p["rt_cd"] = "1"
    with pytest.raises(KisInvestorError, match="승인하지"):
        normalize_kis_investor_response(p, "005930", "2026-11-09")


def test_http_403_does_not_log_tokens_or_response_text():
    session = Mock()
    session.get.return_value = Mock(
        status_code=403, text="TOKEN_PRIVATE",
        json=lambda: {"error": "TOKEN_PRIVATE"},
    )
    with pytest.raises(KisInvestorError) as ctx:
        fetch_kis_investor_history(
            "005930", "2026-11-09", "key_private", "secret_private",
            "token_private", session=session)
    message = str(ctx.value)
    assert "HTTP 403" in message
    assert "PRIVATE" not in message
    assert session.get.call_args.kwargs["headers"]["tr_id"] == KIS_INVESTOR_TR_ID
    assert session.get.call_args.kwargs["params"]["FID_INPUT_ISCD"] == "005930"


def test_invalid_json_cannot_leak_response():
    session = Mock()
    session.get.return_value = Mock(status_code=200,
                                    json=Mock(side_effect=ValueError("secret response")))
    with pytest.raises(KisInvestorError, match="JSON 형식"):
        fetch_kis_investor_history(
            "005930", "2026-11-09", "key", "secret", "token", session=session)


def test_valid_broker_data_does_not_claim_marketwide_coverage():
    session = Mock()
    session.get.return_value = Mock(status_code=200, json=lambda: sample())
    df = fetch_kis_investor_history(
        "005930", "2026-11-09", "key", "secret", "token", session=session)
    assert len(df) == 2
    assert df.index.max().date().isoformat() == "2026-11-09"
    assert session.get.call_args.kwargs["params"]["FID_COND_MRKT_DIV_CODE"] == "J"
