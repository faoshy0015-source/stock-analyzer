"""Server-only KRX login environment binding for authenticated pykrx.

KRX_ID / KRX_PW are KRX Data Marketplace account credentials (not the
KRX OpenAPI auth key). Never display, log, save or embed these values in HTML.
"""
from __future__ import annotations

import os


def configure_streamlit_krx(st):
    """Expose Streamlit server secrets to pykrx in this server process only."""
    try:
        krx_id = str(st.secrets.get("KRX_ID", "") or "").strip()
        krx_pw = str(st.secrets.get("KRX_PW", "") or "").strip()
    except Exception:
        return krx_login_configured()
    if not (krx_id and krx_pw):
        return krx_login_configured()
    os.environ["KRX_ID"] = krx_id
    os.environ["KRX_PW"] = krx_pw
    return True


def krx_login_configured():
    return bool(os.environ.get("KRX_ID") and os.environ.get("KRX_PW"))
