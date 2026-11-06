"""Regression tests for early password gate and server-side Secrets only."""
from contextlib import nullcontext

import pytest

from access_gate import configured_password, verify_password, require_login


class Stopped(Exception):
    pass


class Reran(Exception):
    pass


class FakeStreamlit:
    def __init__(self, secrets=None, candidate="", submitted=False, authed=False):
        self.secrets=secrets if secrets is not None else {}
        self.session_state={"_hanav_stock_authenticated":True} if authed else {}
        self.candidate=candidate
        self.submitted=submitted
        self.errors=[]
        self.form_rendered=False
        self.stopped=False
        self.reran=False
        self.markup=[]

    def title(self,*args,**kwargs):pass
    def caption(self,*args,**kwargs):pass
    def markdown(self, content, **kwargs):
        self.markup.append(str(content))
    def columns(self, *args, **kwargs):
        return [nullcontext(), nullcontext(), nullcontext()]
    def error(self,message):self.errors.append(message)
    def form(self,*args,**kwargs):
        self.form_rendered=True
        return nullcontext()
    def text_input(self,*args,**kwargs):
        assert kwargs.get("type")=="password"
        return self.candidate
    def form_submit_button(self,*args,**kwargs):return self.submitted
    def stop(self):
        self.stopped=True
        raise Stopped()
    def rerun(self):
        self.reran=True
        raise Reran()


def test_default_secret_and_common_aliases():
    assert configured_password({"APP_PASSWORD":"  초록 비밀  "})=="초록 비밀"
    assert configured_password({"APP_PASSWORD":"primary","PASSWORD":"secondary"})=="primary"
    assert configured_password({"APP_PW":"fallback"})=="fallback"
    assert configured_password({"LOGIN_PASSWORD":"another"})=="another"


def test_missing_or_empty_password_denies_access():
    assert configured_password({}) is None
    assert configured_password({"APP_PASSWORD":"","PASSWORD":"   "}) is None
    st=FakeStreamlit()
    with pytest.raises(Stopped):require_login(st)
    assert st.stopped and not st.session_state.get("_hanav_stock_authenticated")
    assert any("APP_PASSWORD" in error for error in st.errors)


def test_correct_password_sets_session_and_reruns():
    st=FakeStreamlit({"APP_PASSWORD":"문자열특수!9"},
                     "문자열특수!9",submitted=True)
    with pytest.raises(Reran):require_login(st)
    assert st.session_state["_hanav_stock_authenticated"] is True
    assert st.reran
    assert not st.errors


def test_wrong_password_stays_locked():
    st=FakeStreamlit({"APP_PASSWORD":"secret"},
                     "incorrect",submitted=True)
    with pytest.raises(Stopped):require_login(st)
    assert st.form_rendered
    assert st.errors==["비밀번호가 일치하지 않습니다."]
    assert not st.session_state.get("_hanav_stock_authenticated")


def test_open_login_screen_waits_for_submit():
    st=FakeStreamlit({"APP_PASSWORD":"secret"})
    with pytest.raises(Stopped):require_login(st)
    assert st.form_rendered and not st.reran


def test_existing_session_bypasses_login_form_only():
    st=FakeStreamlit({},authed=True)
    require_login(st)
    assert not st.form_rendered and not st.errors


def test_credentials_are_not_trimmed_or_logged_on_verification():
    assert verify_password("abc","abc")
    assert verify_password("한글!","한글!")
    assert not verify_password(" abc","abc")
    assert not verify_password("abc ","abc")
    assert not verify_password("abc","")
    assert not verify_password(None,"abc")


def test_login_ui_is_centered_and_green_but_password_stays_server_side():
    st=FakeStreamlit({"APP_PASSWORD":"do-not-leak"})
    with pytest.raises(Stopped):
        require_login(st)
    page="\n".join(st.markup)
    assert "hanav-auth-hero" in page
    assert "linear-gradient(122deg, #07483f" in page
    assert 'data-testid="stForm"' in page
    assert "Stock Analyzer" in page
    assert "do-not-leak" not in page
    assert st.form_rendered


def test_signed_in_session_does_not_emit_login_only_css():
    st=FakeStreamlit({"APP_PASSWORD":"secret"},authed=True)
    require_login(st)
    assert st.markup==[]
