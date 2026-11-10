"""Offline security contract tests for approved-email Supabase Auth."""
from unittest.mock import Mock

import pytest

import email_auth as auth


SECRETS = {
    "SUPABASE_URL": "https://example.supabase.co",
    "SUPABASE_ANON_KEY": "public-anon-key",
    "APP_ALLOWED_EMAILS": ["owner@example.com", "viewer@naver.com"],
}


def config():
    return auth.get_email_auth_config(SECRETS)


def test_allowlist_accepts_exact_email_addresses_case_insensitive():
    cfg = config()
    assert auth.is_approved(" OWNER@EXAMPLE.COM ", cfg)
    assert auth.is_approved("viewer@naver.com", cfg)
    assert not auth.is_approved("not-owner@example.com", cfg)
    assert not auth.is_approved("owner@example.com.attacker.net", cfg)
    assert not auth.is_approved("employee@other.com", cfg)


def test_missing_approval_list_fails_closed_even_with_legacy_password():
    with pytest.raises(auth.EmailAuthError, match="승인 이메일 목록"):
        auth.get_email_auth_config({
            "APP_PASSWORD": "known-old-password",
            "SUPABASE_URL": SECRETS["SUPABASE_URL"],
            "SUPABASE_ANON_KEY": "anon",
        })


@pytest.mark.parametrize("candidate", ["*@example.com", "@example.com", "example.com", "owner@", "*.com"])
def test_domains_and_wildcards_are_forbidden(candidate):
    with pytest.raises(auth.EmailAuthError):
        auth.parse_approved_emails(candidate)


def test_anon_key_is_mandatory_and_service_role_cannot_replace_it():
    with pytest.raises(auth.EmailAuthError, match="SUPABASE_ANON_KEY"):
        auth.get_email_auth_config({
            "SUPABASE_URL": SECRETS["SUPABASE_URL"],
            "SUPABASE_SERVICE_ROLE_KEY": "server-secret",
            "APP_ALLOWED_EMAILS": ["owner@example.com"],
        })


def test_unapproved_address_does_not_send_any_email():
    session = Mock()
    with pytest.raises(auth.EmailAuthError, match="승인되지"):
        auth.request_email_code(config(), "attacker@example.com", session=session)
    session.post.assert_not_called()


def test_email_code_sent_to_approved_address_no_password_or_service_role():
    session = Mock()
    session.post.return_value = Mock(ok=True, status_code=200)
    assert auth.request_email_code(config(), "OWNER@EXAMPLE.COM", session=session)
    kwargs = session.post.call_args.kwargs
    assert kwargs["json"] == {"email": "owner@example.com", "create_user": True}
    assert kwargs["headers"]["apikey"] == SECRETS["SUPABASE_ANON_KEY"]
    assert "Authorization" not in kwargs["headers"]
    assert "owner@example.com" not in session.post.call_args.args[0]
    assert "service_role" not in str(session.post.call_args)


def test_verify_code_requires_authoritative_supabase_get_user():
    session = Mock()
    session.post.return_value = Mock(
        ok=True, status_code=200, json=lambda: {
            "access_token": "ACCESS", "refresh_token": "REFRESH",
            "user": {"email": "attacker@example.com"},  # untrusted
        })
    session.get.return_value = Mock(
        ok=True, status_code=200, json=lambda: {
            "id": "uuid-from-auth-server", "email": "owner@example.com",
        })
    verified = auth.verify_email_code(
        config(), "owner@example.com", "123456", session=session)
    assert verified["email"] == "owner@example.com"
    assert verified["user_id"] == "uuid-from-auth-server"
    assert session.get.call_args.kwargs["headers"]["Authorization"] == "Bearer ACCESS"


def test_forged_response_email_mismatch_is_blocked():
    session = Mock()
    session.post.return_value = Mock(
        ok=True, status_code=200, json=lambda: {
            "access_token": "ACCESS", "refresh_token": "REFRESH"})
    session.get.return_value = Mock(
        ok=True, status_code=200, json=lambda: {
            "id": "uuid", "email": "viewer@naver.com"})
    with pytest.raises(auth.EmailAuthError, match="다릅니다"):
        auth.verify_email_code(
            config(), "owner@example.com", "123456", session=session)


def test_session_revocation_is_effective_on_next_validation():
    session = Mock()
    session.get.return_value = Mock(
        ok=True, status_code=200,
        json=lambda: {"id": "uuid", "email": "owner@example.com"})
    old = {"access_token": "ACCESS", "refresh_token": "REFRESH"}
    assert auth.validate_session(config(), old, session=session)
    removed = auth.get_email_auth_config({
        **SECRETS, "APP_ALLOWED_EMAILS": ["viewer@naver.com"]})
    assert auth.validate_session(removed, old, session=session) is None


def test_client_session_email_or_old_flag_cannot_bypass_supabase():
    session = Mock()
    session.get.return_value = Mock(ok=False, status_code=401)
    session.post.return_value = Mock(ok=False, status_code=401)
    stored = {"email": "owner@example.com", "access_token": "FORGED",
              "refresh_token": "FORGED"}
    assert auth.validate_session(config(), stored, session=session) is None
    assert auth.validate_session(config(), {"email": "owner@example.com"},
                                 session=session) is None


def test_expired_jwt_refreshes_and_rechecks_identity():
    session = Mock()
    session.get.side_effect = [
        Mock(ok=False, status_code=401),
        Mock(ok=True, status_code=200,
             json=lambda: {"id": "uuid", "email": "owner@example.com"}),
    ]
    session.post.return_value = Mock(
        ok=True, status_code=200,
        json=lambda: {"access_token": "NEW", "refresh_token": "ROTATED"})
    verified = auth.validate_session(
        config(), {"access_token": "EXPIRED", "refresh_token": "OLD"},
        session=session)
    assert verified["access_token"] == "NEW"
    assert verified["refresh_token"] == "ROTATED"
    assert session.post.call_args.args[0].endswith(
        "/auth/v1/token?grant_type=refresh_token")


def test_no_response_bodies_or_keys_in_otp_errors():
    session = Mock()
    session.post.return_value = Mock(
        ok=False, status_code=403, text="service-secret",
        json=lambda: {"error": "service-secret"})
    with pytest.raises(auth.EmailAuthError) as error:
        auth.request_email_code(config(), "owner@example.com", session=session)
    assert "service-secret" not in str(error.value)


def test_resend_throttle_for_same_email_only():
    now = 700.0
    state = {auth.LAST_SENT_KEY: {"email": "owner@example.com", "time": now}}
    assert not auth.otp_resend_permitted(state, "OWNER@example.com", now=now+12)
    assert auth.otp_resend_permitted(state, "owner@example.com", now=now+65)
