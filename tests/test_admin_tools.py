"""Offline security tests for admin-only manual refresh and cache controls."""
from contextlib import nullcontext
from unittest.mock import Mock

import admin_tools as admin


class Rerun(Exception):
    pass


class FakeStreamlit:
    def __init__(self, *, secret=None, state=None, submit=False, candidate="",
                 clicked=None):
        self.secrets = {} if secret is None else secret
        self.session_state = {} if state is None else state
        self.submit = submit
        self.candidate = candidate
        self.clicked = set() if clicked is None else set(clicked)
        self.buttons_created = []
        self.error_messages = []
        self.warnings = []
        self.success_messages = []
        self.cache_data = Mock()
        self.cache_data.clear = Mock()

    def expander(self, *args, **kwargs):
        return nullcontext()

    def form(self, *args, **kwargs):
        return nullcontext()

    def text_input(self, *args, **kwargs):
        return self.candidate

    def form_submit_button(self, *args, **kwargs):
        return self.submit

    def button(self, label, key=None, **kwargs):
        self.buttons_created.append(key or label)
        return (key or label) in self.clicked

    def warning(self, text):
        self.warnings.append(text)

    def error(self, text):
        self.error_messages.append(text)

    def success(self, text):
        self.success_messages.append(text)

    def caption(self, text):
        pass

    def rerun(self):
        raise Rerun()


def test_admin_does_not_fall_back_to_app_password():
    assert admin.configured_admin_password({
        "APP_PASSWORD": "same-as-login",
    }) is None
    assert admin.configured_admin_password({
        "APP_PASSWORD": "member",
        "ADMIN_PASSWORD": "manager",
    }) == "manager"


def test_admin_secret_missing_never_calls_management_actions():
    st = FakeStreamlit(secret={"APP_PASSWORD": "member"},
                       clicked={"admin_krx_listing", "admin_clear_data_cache"})
    load = Mock()
    admin.render_admin_controls(st, krx_loader=load)
    assert load.call_count == 0
    st.cache_data.clear.assert_not_called()
    assert not st.buttons_created
    assert any("ADMIN_PASSWORD" in warning for warning in st.warnings)


def test_unapproved_does_not_even_render_admin_buttons():
    st = FakeStreamlit(secret={"ADMIN_PASSWORD": "manager"},
                       clicked={"admin_krx_listing", "admin_clear_data_cache"})
    krx, dart = Mock(), Mock()
    admin.render_admin_controls(st, krx_loader=krx, dart_loader=dart)
    krx.assert_not_called()
    dart.assert_not_called()
    st.cache_data.clear.assert_not_called()
    assert "admin_krx_listing" not in st.buttons_created
    assert "admin_clear_data_cache" not in st.buttons_created


def test_wrong_password_must_not_unlock():
    state = {}
    success, message = admin.grant_admin(state, "member", "manager", now=100)
    assert success is False
    assert "올바르지" in message
    assert not admin.is_admin_unlocked(state, "manager", now=101)


def test_admin_unlock_only_valid_fifteen_minutes_and_rotates():
    state = {}
    success, message = admin.grant_admin(state, "manager", "manager", now=100)
    assert success is True
    assert admin.is_admin_unlocked(state, "manager", now=999)
    assert not admin.is_admin_unlocked(state, "manager", now=1000)
    assert not admin.is_admin_unlocked(state, "new-manager", now=150)
    assert "manager" not in str(state)
    assert "15분" in message


def test_brute_force_is_temporarily_locked_out():
    state = {}
    for i in range(admin.MAX_ATTEMPTS):
        success, _ = admin.grant_admin(state, "wrong", "manager", now=100+i)
        assert not success
    success, _ = admin.grant_admin(state, "manager", "manager", now=120)
    assert success is False
    assert admin.is_admin_unlocked(state, "manager", now=120) is False
    success, _ = admin.grant_admin(state, "manager", "manager", now=500)
    assert success is True


def test_verified_admin_can_use_loader_but_normal_button_has_no_effect():
    state = {}
    admin.grant_admin(state, "manager", "manager", now=100)
    # Grant a fresh real-time token for UI, regardless of test wall clock.
    admin.grant_admin(state, "manager", "manager")
    st = FakeStreamlit(secret={"ADMIN_PASSWORD": "manager"}, state=state,
                       clicked={"admin_krx_listing"})
    krx, dart = Mock(), Mock()
    admin.render_admin_controls(st, krx_loader=krx, dart_loader=dart)
    krx.assert_called_once_with()
    dart.assert_not_called()


def test_cache_reset_only_when_admin_unlocked_and_clicked():
    state = {}
    admin.grant_admin(state, "manager", "manager")
    st = FakeStreamlit(secret={"ADMIN_PASSWORD": "manager"}, state=state,
                       clicked={"admin_clear_data_cache"})
    with __import__("pytest").raises(Rerun):
        admin.render_admin_controls(st, krx_loader=Mock())
    st.cache_data.clear.assert_called_once()


def test_lock_admin_revokes_action_grant():
    state = {}
    admin.grant_admin(state, "manager", "manager")
    assert admin.is_admin_unlocked(state, "manager")
    admin.lock_admin(state)
    assert not admin.is_admin_unlocked(state, "manager")


def test_navigation_labels_and_targets():
    from app_navigation import render_navigation

    class FakeNav:
        def __init__(self):
            self.sidebar = nullcontext()
            self.items = []
        def page_link(self, target, label, icon):
            self.items.append((target, label, icon))
        def divider(self):
            pass
    fake = FakeNav()
    render_navigation(fake)
    assert fake.items == [
        ("app.py", "Analyze", "🔎"),
        ("pages/0_전종목_수급_레이더.py", "전종목 수급 레이더", "📡"),
        ("pages/1_수급_전환_검색.py", "수급 전환 검색", "🔄"),
    ]
