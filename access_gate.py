"""Session-based application password gate for HanaV Stock Analyzer.

This is an app-level shared-password barrier, not user identity management.
Credentials must be stored in Streamlit Secrets, never in GitHub.
"""
from __future__ import annotations

import hmac

PASSWORD_SECRET_NAMES = (
    "APP_PASSWORD",
    "APP_ACCESS_PASSWORD",
    "LOGIN_PASSWORD",
    "ACCESS_PASSWORD",
    "PASSWORD",
    "APP_PASS",
    "APP_PW",
    "STOCK_ANALYZER_PASSWORD",
    "ADMIN_PASSWORD",
    "app_password",
    "password",
)


def configured_password(secrets):
    """Find a non-empty application password from accepted secret names.

    Prefer APP_PASSWORD when present. A missing secret must *not* disable
    authentication or switch the app into a public/demo mode.
    """
    for name in PASSWORD_SECRET_NAMES:
        try:
            value = secrets.get(name)
        except Exception:  # absent/unconfigured Streamlit Secrets: fail closed
            continue
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def verify_password(candidate, configured):
    """Constant-time comparison; never expose or record either string."""
    return (isinstance(candidate, str) and isinstance(configured, str)
            and bool(configured)
            and hmac.compare_digest(candidate.encode("utf-8"),
                                    configured.encode("utf-8")))


def require_login(st):
    """Stop execution before any app content, external data, or cached reads."""
    if st.session_state.get("_hanav_stock_authenticated") is True:
        return

    st.title("🔒 HanaV Stock Analyzer")
    st.caption("이 앱은 비밀번호 인증 후 이용할 수 있습니다.")

    expected = configured_password(st.secrets)
    if not expected:
        st.error("앱 비밀번호 설정을 확인할 수 없습니다. "
                 "Streamlit Cloud → App settings → Secrets에 "
                 'APP_PASSWORD = "설정한 비밀번호" 형식으로 저장해 주세요.')
        st.stop()

    with st.form("stock_analyzer_sign_in", clear_on_submit=True):
        candidate = st.text_input("앱 비밀번호", type="password",
                                  placeholder="비밀번호 입력", autocomplete="off")
        submitted = st.form_submit_button("로그인", use_container_width=True)

    if submitted:
        if verify_password(candidate, expected):
            st.session_state["_hanav_stock_authenticated"] = True
            st.rerun()
        else:
            st.error("비밀번호가 일치하지 않습니다.")
    st.stop()
