"""KRX credential binding does not log secrets or require them in tests."""
import os
from unittest.mock import Mock

from krx_auth import configure_streamlit_krx, krx_login_configured


def test_server_secrets_exposed_only_as_environment(monkeypatch):
    monkeypatch.delenv("KRX_ID", raising=False)
    monkeypatch.delenv("KRX_PW", raising=False)
    ui = Mock()
    ui.secrets = {"KRX_ID": "testid", "KRX_PW": "private"}
    assert configure_streamlit_krx(ui) is True
    assert os.environ["KRX_ID"] == "testid"
    assert os.environ["KRX_PW"] == "private"
    assert krx_login_configured() is True


def test_no_credentials_reuses_existing_environment(monkeypatch):
    monkeypatch.setenv("KRX_ID", "from_server")
    monkeypatch.setenv("KRX_PW", "from_server_pw")
    ui = Mock()
    ui.secrets = {}
    assert configure_streamlit_krx(ui) is True


def test_blank_server_does_not_enable_auth(monkeypatch):
    monkeypatch.delenv("KRX_ID", raising=False)
    monkeypatch.delenv("KRX_PW", raising=False)
    ui = Mock()
    ui.secrets = {}
    assert configure_streamlit_krx(ui) is False
