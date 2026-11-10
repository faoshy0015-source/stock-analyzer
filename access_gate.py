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
    """Green-first, ETF Finder-style centered login without changing authentication.

    The UI is emitted only for unauthenticated sessions. Secrets stay server
    side and a failed or unconfigured password always denies access.
    """
    if st.session_state.get("_hanav_stock_authenticated") is True:
        return

    st.markdown(
        """
        <style>
        :root {color-scheme:light;}
        [data-testid="stSidebar"],
        [data-testid="stSidebarCollapsedControl"] {display:none!important}
        [data-testid="stAppViewContainer"],
        [data-testid="stMain"] {
            background: linear-gradient(160deg,#f4f8f7 0%,#f8fcfa 68%,#f0f7f2 100%) !important;
            color:#203d35 !important;
        }
        header[data-testid="stHeader"] {background:#f4f8f7!important}
        .block-container {
            max-width:1080px!important;
            padding-top: clamp(2.8rem, 9vh, 6rem)!important;
            padding-bottom:3rem!important;
        }
        .hanav-login-brand {
            max-width:500px;
            margin:0 auto 22px;
            text-align:center;
        }
        .hanav-login-accent {
            width:52px;height:4px;border-radius:10px;
            margin:0 auto 20px;
            background:linear-gradient(90deg,#008878 0%,#008878 76%,#e87d31 76%,#e87d31 100%);
        }
        .hanav-login-title {
            color:#008878!important;
            font-size:clamp(29px,3.9vw,38px);
            font-weight:850;letter-spacing:-.045em;
            margin:0 0 8px;line-height:1.3;
        }
        .hanav-login-subtitle {
            color:#536f64;font-size:14px;font-weight:600;
            line-height:1.6;margin:0 0 5px;
        }
        .hanav-login-feature {
            color:#71877d;font-size:12px;
            line-height:1.65;margin:0;
        }
        .hanav-login-signature {
            margin-top:10px;font-size:11px;font-weight:650;
            letter-spacing:.04em;color:#bc7a3f;
        }
        [data-testid="stForm"] {
            background:#ffffff!important;
            border:1px solid #cbded5!important;
            border-radius:14px!important;
            padding:20px 22px 23px!important;
            box-shadow:0 8px 25px rgba(18,74,56,.065);
        }
        [data-testid="stForm"] [data-testid="stWidgetLabel"] p {
            color:#315e53!important;font-size:13px!important;font-weight:700!important;
        }
        [data-testid="stForm"] input[type="password"] {
            background:#fff!important;color:#203d35!important;
            border:1px solid #cbded5!important;
            border-radius:9px!important;min-height:44px!important;
        }
        [data-testid="stForm"] input:focus {
            border-color:#008878!important;
            box-shadow:0 0 0 3px rgba(0,136,120,.13)!important;
        }
        [data-testid="stFormSubmitButton"] button,
        [data-testid="stFormSubmitButton"] button[kind="primary"] {
            background:#008878!important;color:#ffffff!important;
            border:1px solid #008878!important;
            border-radius:9px!important;min-height:46px!important;
            font-weight:750!important;
            box-shadow:0 5px 14px rgba(0,108,93,.13)!important;
        }
        [data-testid="stFormSubmitButton"] button:hover {
            background:#006f62!important;
            border-color:#006f62!important;
        }
        [data-testid="stFormSubmitButton"] button p {color:#ffffff!important}
        .hanav-login-footer {
            max-width:440px;margin:19px auto 0;
            padding-top:11px;border-top:1px solid #d6e6dd;
            text-align:center;color:#83968d;font-size:11px;
        }
        @media(max-width:700px) {
            .block-container {padding-top:2.5rem!important}
            .hanav-login-brand {margin-bottom:16px}
            [data-testid="stForm"] {padding:16px!important}
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="hanav-login-brand" aria-label="Stock Analyzer login">
          <div class="hanav-login-accent"></div>
          <h1 class="hanav-login-title">Stock Analyzer</h1>
          <p class="hanav-login-subtitle">Private Investment Dashboard</p>
          <p class="hanav-login-feature">
            종목 분석 · 재무 · 수급 전환 · 리서치 리포트
          </p>
          <div class="hanav-login-signature">CREATED BY K.H.AHN</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    _, center, _ = st.columns([1, 1.15, 1])
    with center:
        expected = configured_password(st.secrets)
        if not expected:
            st.error("앱 비밀번호 설정을 확인할 수 없습니다. "
                     "Streamlit Cloud → App settings → Secrets에 "
                     'APP_PASSWORD = "설정한 비밀번호" 형식으로 저장해 주세요.')
            st.stop()

        with st.form("stock_analyzer_sign_in", clear_on_submit=True):
            candidate = st.text_input(
                "비밀번호", type="password",
                placeholder="비밀번호를 입력하세요", autocomplete="off",
            )
            submitted = st.form_submit_button(
                "🔐 로그인", type="primary", use_container_width=True,
            )
        st.markdown(
            '<div class="hanav-login-footer">PRIVATE RESEARCH · SECURE ACCESS</div>',
            unsafe_allow_html=True,
        )

        if submitted:
            if verify_password(candidate, expected):
                st.session_state["_hanav_stock_authenticated"] = True
                st.rerun()
            else:
                st.error("비밀번호가 일치하지 않습니다.")
    st.stop()
