"""Regression checks for the approved-email-only Streamlit access gate."""
from contextlib import nullcontext
from unittest.mock import Mock

import pytest

import access_gate
from access_gate import require_login
from email_auth import PENDING_KEY, SESSION_KEY


SECRETS = {
    "SUPABASE_URL": "https://example.supabase.co",
    "SUPABASE_ANON_KEY": "anon",
    "APP_ALLOWED_EMAILS": ["owner@example.com"],
    "APP_PASSWORD": "legacy_password_must_not_unlock",
}


class Stopped(Exception):
    pass


class Reran(Exception):
    pass


class FakeStreamlit:
    def __init__(self, secrets=None, *, state=None,
                 input_text="", submit=False, logout=False):
        self.secrets = {} if secrets is None else secrets
        self.session_state = {} if state is None else state
        self.input_text = input_text
        self.submit = submit
        self.logout = logout
        self.sidebar = nullcontext()
        self.errors = []
        self.warnings = []
        self.messages = []
        self.markup = []
        self.form_count = 0

    def markdown(self, content, **kwargs):
        self.markup.append(str(content))

    def columns(self, *args, **kwargs):
        return [nullcontext(), nullcontext(), nullcontext()]

    def error(self, message):
        self.errors.append(message)

    def warning(self, message):
        self.warnings.append(message)

    def caption(self, message):
        self.messages.append(message)

    def form(self, *args, **kwargs):
        self.form_count += 1
        return nullcontext()

    def text_input(self, *args, **kwargs):
        return self.input_text

    def form_submit_button(self, *args, **kwargs):
        return self.submit

    def button(self, *args, **kwargs):
        if kwargs.get("key") == "stock_email_logout":
            return self.logout
        return False

    def stop(self):
        raise Stopped()

    def rerun(self):
        raise Reran()


def test_missing_allowlist_denies_password_only_sessions():
    st = FakeStreamlit(
        {"APP_PASSWORD": "legacy", "SUPABASE_URL": SECRETS["SUPABASE_URL"]},
        state={"_hanav_stock_authenticated": True})
    with pytest.raises(Stopped):
        require_login(st)
    assert st.errors and "승인 이메일" in st.errors[0]


def test_old_password_flag_cannot_grant_access():
    st = FakeStreamlit(
        SECRETS, state={"_hanav_stock_authenticated": True})
    with pytest.raises(Stopped):
        require_login(st)
    assert "_hanav_stock_authenticated" not in st.session_state
    assert st.form_count == 1


def test_unauthorized_email_never_requests_otp(monkeypatch):
    send = Mock()
    monkeypatch.setattr(access_gate, "request_email_code", send)
    st = FakeStreamlit(SECRETS, input_text="intruder@other.com", submit=True)
    with pytest.raises(Stopped):
        require_login(st)
    send.assert_not_called()
    assert "승인된 이메일 주소" in st.errors[0]


def test_approved_email_receives_code_and_is_not_yet_authenticated(monkeypatch):
    send = Mock(return_value=True)
    monkeypatch.setattr(access_gate, "request_email_code", send)
    st = FakeStreamlit(SECRETS, input_text="owner@example.com", submit=True)
    with pytest.raises(Reran):
        require_login(st)
    send.assert_called_once()
    assert st.session_state[PENDING_KEY] == "owner@example.com"
    assert SESSION_KEY not in st.session_state


def test_correct_otp_needs_external_verification_before_rerun(monkeypatch):
    verified = {
        "access_token": "token", "refresh_token": "refresh",
        "email": "owner@example.com", "user_id": "uuid"
    }
    check = Mock(return_value=verified)
    monkeypatch.setattr(access_gate, "verify_email_code", check)
    st = FakeStreamlit(SECRETS, state={PENDING_KEY: "owner@example.com"},
                       input_text="123456", submit=True)
    with pytest.raises(Reran):
        require_login(st)
    assert st.session_state[SESSION_KEY] == verified
    check.assert_called_once()


def test_approved_saved_session_requires_online_validation_each_rerun(monkeypatch):
    session = {"email": "owner@example.com",
               "access_token": "token", "refresh_token": "refresh"}
    check = Mock(return_value={
        **session, "user_id": "uuid"
    })
    monkeypatch.setattr(access_gate, "validate_session", check)
    st = FakeStreamlit(SECRETS, state={SESSION_KEY: session})
    require_login(st)
    require_login(st)
    assert check.call_count == 2
    assert st.form_count == 0
    assert any("owner@example.com" in x for x in st.messages)


def test_revoked_or_invalid_session_clears_previous_page_state(monkeypatch):
    monkeypatch.setattr(access_gate, "validate_session", lambda *a: None)
    st = FakeStreamlit(SECRETS, state={
        SESSION_KEY: {"access_token": "revoked"},
        "cached_stock_results": {"private": "data"},
    })
    with pytest.raises(Stopped):
        require_login(st)
    assert "cached_stock_results" not in st.session_state
    assert st.form_count == 1


def test_logout_clears_all_session_state(monkeypatch):
    session = {"email": "owner@example.com",
               "access_token": "token", "refresh_token": "refresh"}
    monkeypatch.setattr(access_gate, "validate_session", lambda *args: {
        **session, "user_id": "uuid"})
    st = FakeStreamlit(SECRETS, state={
        SESSION_KEY: session, "old_stock_rows": [1, 2, 3]},
        logout=True)
    with pytest.raises(Reran):
        require_login(st)
    assert not st.session_state


def test_etf_finder_green_theme_preserved_for_email_login():
    st = FakeStreamlit(SECRETS)
    with pytest.raises(Stopped):
        require_login(st)
    text = "\n".join(st.markup)
    assert "Stock Analyzer" in text
    assert "Private Investment Dashboard" in text
    assert "CREATED BY K.H.AHN" in text
    assert "background:#008878" in text
    assert "#e87d31" in text
    assert "APP_PASSWORD" not in text
