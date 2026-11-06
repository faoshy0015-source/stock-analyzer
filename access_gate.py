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
    """Show a centered branded sign-in screen; stop before app data loads.

    Styling exists only on the unauthenticated page. Session authentication,
    Secrets-based comparison and fail-closed behavior are unchanged.
    """
    if st.session_state.get("_hanav_stock_authenticated") is True:
        return

    st.markdown(
        """
        <style>
        /* Isolated to login sessions: this CSS is not emitted after sign-in. */
        [data-testid="stSidebar"],
        [data-testid="stSidebarCollapsedControl"] { display: none !important; }
        [data-testid="stMain"] {
            background:
              radial-gradient(ellipse at 7% 3%, rgba(240,174,98,.13), transparent 38%),
              radial-gradient(ellipse at 93% 100%, rgba(63,193,152,.08), transparent 40%),
              #fffaf4;
        }
        .block-container {
            max-width: 1230px !important;
            padding-top: clamp(2.5rem, 9vh, 6rem) !important;
            padding-bottom: 3rem !important;
        }
        .hanav-auth-hero {
            position: relative;
            overflow: hidden;
            min-height: 218px;
            border-radius: 22px;
            padding: 27px 31px 30px;
            background: linear-gradient(122deg, #e8f6ed 0%, #fff4e1 57%, #ffe5c9 100%);
            border: 1px solid #eed8bb;
            border-left: 5px solid #e87d31;
            box-shadow: 0 15px 35px rgba(120, 87, 45, .10);
            color: #305949;
        }
        .hanav-auth-hero::before {
            content: "";
            position: absolute;
            width: 230px;
            height: 230px;
            right: -65px;
            top: -100px;
            border: 1px solid rgba(230,145,60,.25);
            border-radius: 50%;
            box-shadow: 0 0 0 42px rgba(229,158,79,.065),
                        0 0 0 86px rgba(26,146,120,.035);
            pointer-events: none;
        }
        .hanav-auth-eyebrow {
            position: relative;
            font-size: 10px;
            letter-spacing: 2.1px;
            font-weight: 750;
            color: #bd6b25;
            margin-bottom: 19px;
        }
        .hanav-auth-logo {
            position: relative;
            width: 43px;
            height: 43px;
            display: inline-flex;
            justify-content: center;
            align-items: center;
            border: 1px solid #edce9f;
            border-radius: 13px;
            background: #fff1dd;
            color: #a45d24;
            font-size: 20px;
            font-weight: 800;
            letter-spacing: -.8px;
            margin-bottom: 12px;
        }
        .hanav-auth-title {
            position: relative;
            font-size: clamp(1.7rem, 3vw, 2.15rem);
            font-weight: 800;
            letter-spacing: -.8px;
            line-height: 1.18;
            margin: 0 0 9px;
            color: #2d5a48;
        }
        .hanav-auth-subtitle {
            position: relative;
            font-size: .91rem;
            line-height: 1.65;
            margin: 0;
            color: #4c705e;
            opacity: .96;
        }
        .hanav-auth-panel-title {
            color: #164039;
            font-size: 1.05rem;
            font-weight: 760;
            letter-spacing: -.4px;
            margin: 24px 1px 4px;
        }
        .hanav-auth-panel-desc {
            color: #6a827b;
            font-size: .87rem;
            margin: 0 1px 14px;
            line-height: 1.6;
        }
        [data-testid="stForm"] {
            background: #fff !important;
            border: 1px solid #efe1cd !important;
            border-radius: 17px !important;
            padding: 21px 23px 23px !important;
            box-shadow: 0 10px 32px rgba(119,87,46,.065);
        }
        [data-testid="stForm"] [data-testid="stTextInput"] label {
            font-size: .85rem !important;
            font-weight: 650 !important;
            color: #315e53 !important;
        }
        [data-testid="stForm"] input[type="password"],
        [data-testid="stForm"] input[type="text"] {
            border-radius: 10px !important;
            border: 1px solid #e6d6bd !important;
            background: #fffefb !important;
            min-height: 45px !important;
        }
        [data-testid="stForm"] input:focus {
            border-color: #e8893d !important;
            box-shadow: 0 0 0 3px rgba(232,125,49,.14) !important;
        }
        [data-testid="stFormSubmitButton"] button {
            color: #ffffff !important;
            min-height: 46px !important;
            border-radius: 11px !important;
            background: linear-gradient(100deg, #d7752b, #ed9c4e) !important;
            border: 1px solid #d7752b !important;
            color: #fff !important;
            font-weight: 750 !important;
            box-shadow: 0 7px 17px rgba(212,114,42,.15);
        }
        [data-testid="stFormSubmitButton"] button:hover {
            background: linear-gradient(100deg, #c76a25, #df8737) !important;
            border-color: #bb6425 !important;
            color: #fff !important;
        }
        .hanav-auth-footer {
            text-align: center;
            margin-top: 22px;
            color: #98734f;
            font-size: 11px;
            letter-spacing: .45px;
        }
        @media (max-width: 780px) {
            .block-container { padding-top: 1.7rem !important; }
            .hanav-auth-hero { min-height: 200px; padding: 23px 22px 26px; }
            [data-testid="stForm"] { padding: 16px !important; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    _, center, _ = st.columns([0.7, 2, 0.7], gap="large")
    with center:
        st.markdown(
            """
            <section class="hanav-auth-hero" aria-label="Stock Analyzer login">
              <div class="hanav-auth-eyebrow">STOCK ANALYZER · SECURE ACCESS</div>
              <div class="hanav-auth-logo">SA</div>
              <h1 class="hanav-auth-title">Stock Analyzer</h1>
              <p class="hanav-auth-subtitle">
                기업의 가치를 더 입체적으로 읽다.<br>
                주가 · 재무 · 수급 · 리포트를 한곳에서 분석합니다.
              </p>
            </section>
            <div class="hanav-auth-panel-title">분석 워크스페이스 로그인</div>
            <p class="hanav-auth-panel-desc">
              등록된 앱 비밀번호를 입력하면 분석 화면이 열립니다.
            </p>
            """,
            unsafe_allow_html=True,
        )

        expected = configured_password(st.secrets)
        if not expected:
            st.error("앱 비밀번호 설정을 확인할 수 없습니다. "
                     "Streamlit Cloud → App settings → Secrets에 "
                     'APP_PASSWORD = "설정한 비밀번호" 형식으로 저장해 주세요.')
            st.stop()

        with st.form("stock_analyzer_sign_in", clear_on_submit=True):
            candidate = st.text_input(
                "앱 비밀번호",
                type="password",
                placeholder="비밀번호를 입력하세요",
                autocomplete="off",
            )
            submitted = st.form_submit_button("안전하게 로그인", use_container_width=True)

        st.markdown(
            '<div class="hanav-auth-footer">CREATED BY K.H.AHN</div>',
            unsafe_allow_html=True,
        )

        if submitted:
            if verify_password(candidate, expected):
                st.session_state["_hanav_stock_authenticated"] = True
                st.rerun()
            else:
                st.error("비밀번호가 일치하지 않습니다.")
    st.stop()
