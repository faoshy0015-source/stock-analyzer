"""Email-verified access gate for approved Stock Analyzer viewers only.

Authentication uses Supabase Auth OTP and an exact-email allowlist configured
in Streamlit Secrets. The historical APP_PASSWORD / session boolean cannot
grant access after this change.
"""
from __future__ import annotations

import time

from email_auth import (
    EmailAuthError, LAST_SENT_KEY, PENDING_KEY, SESSION_KEY, clear_auth_state,
    get_email_auth_config, is_approved, normal_email, otp_resend_permitted,
    request_email_code, validate_session, verify_email_code,
)


def require_login(st):
    """Deny access unless Supabase confirms an allowlisted email on this rerun."""
    try:
        config = get_email_auth_config(st.secrets)
    except EmailAuthError as exc:
        # Incomplete setup deliberately locks the whole application,
        # including viewers with an old shared-password session.
        st.error(str(exc))
        st.caption(
            "접근이 차단된 상태입니다. 앱 소유자가 승인 이메일과 "
            "Supabase 인증 설정을 완료해야 합니다."
        )
        st.stop()
        return

    # Explicitly disregard obsolete password-era authentication flags.
    st.session_state.pop("_hanav_stock_authenticated", None)
    saved = st.session_state.get(SESSION_KEY)
    if saved:
        try:
            verified = validate_session(config, saved)
        except EmailAuthError:
            st.error("이메일 인증 서버 확인에 실패했습니다. 재접속 후 다시 시도하세요.")
            st.stop()
            return
        if verified is not None and is_approved(verified["email"], config):
            st.session_state[SESSION_KEY] = verified
            with st.sidebar:
                st.caption("🔐 승인 계정: " + verified["email"])
                if st.button("🔒 로그아웃", key="stock_email_logout",
                             use_container_width=True):
                    clear_auth_state(st)
                    st.rerun()
            return
        clear_auth_state(st)

    st.markdown(
        """
        <style>
        :root {color-scheme:light;}
        [data-testid="stSidebar"],
        [data-testid="stSidebarCollapsedControl"] {display:none!important}
        [data-testid="stAppViewContainer"],
        [data-testid="stMain"] {
            background:linear-gradient(160deg,#f4f8f7 0%,#f8fcfa 68%,#f0f7f2 100%)!important;
            color:#203d35!important;
        }
        header[data-testid="stHeader"]{background:#f4f8f7!important}
        .block-container{
            max-width:1080px!important;
            padding-top:clamp(2.8rem,9vh,6rem)!important;
            padding-bottom:3rem!important;
        }
        .hanav-login-brand{
            max-width:500px;margin:0 auto 22px;text-align:center;
        }
        .hanav-login-accent{
            width:52px;height:4px;border-radius:10px;margin:0 auto 20px;
            background:linear-gradient(90deg,#008878 0%,#008878 76%,#e87d31 76%,#e87d31 100%);
        }
        .hanav-login-title{
            color:#008878!important;
            font-size:clamp(29px,3.9vw,38px);
            font-weight:850;letter-spacing:-.045em;
            margin:0 0 8px;line-height:1.3;
        }
        .hanav-login-subtitle{
            color:#536f64;font-size:14px;font-weight:600;
            line-height:1.6;margin:0 0 5px;
        }
        .hanav-login-feature{
            color:#71877d;font-size:12px;line-height:1.65;margin:0;
        }
        .hanav-login-signature{
            margin-top:10px;font-size:11px;font-weight:650;
            letter-spacing:.04em;color:#bc7a3f;
        }
        [data-testid="stForm"]{
            background:#ffffff!important;
            border:1px solid #cbded5!important;
            border-radius:14px!important;
            padding:20px 22px 23px!important;
            box-shadow:0 8px 25px rgba(18,74,56,.065);
        }
        [data-testid="stForm"] input{
            background:#fff!important;color:#203d35!important;
            border:1px solid #cbded5!important;
            border-radius:9px!important;min-height:44px!important;
        }
        [data-testid="stFormSubmitButton"] button{
            background:#008878!important;color:#ffffff!important;
            border:1px solid #008878!important;border-radius:9px!important;
            min-height:46px!important;font-weight:750!important;
        }
        [data-testid="stFormSubmitButton"] button:hover{
            background:#006f62!important;border-color:#006f62!important;
        }
        [data-testid="stFormSubmitButton"] button p{color:#ffffff!important}
        .hanav-login-footer{
            max-width:440px;margin:19px auto 0;
            padding-top:11px;border-top:1px solid #d6e6dd;
            text-align:center;color:#83968d;font-size:11px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <div class="hanav-login-brand" aria-label="Stock Analyzer email login">
          <div class="hanav-login-accent"></div>
          <h1 class="hanav-login-title">Stock Analyzer</h1>
          <p class="hanav-login-subtitle">Private Investment Dashboard</p>
          <p class="hanav-login-feature">
            승인 이메일 인증 · 종목 분석 · 수급 전환 · 리서치
          </p>
          <div class="hanav-login-signature">CREATED BY K.H.AHN</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    _, center, _ = st.columns([1, 1.15, 1])
    with center:
        pending = st.session_state.get(PENDING_KEY)
        if pending and not is_approved(pending, config):
            st.session_state.pop(PENDING_KEY, None)
            pending = None
        if not pending:
            with st.form("stock_email_otp_request", clear_on_submit=False):
                email = st.text_input(
                    "승인된 이메일 주소",
                    placeholder="이메일 주소를 입력하세요",
                    autocomplete="email",
                    max_chars=254,
                )
                requested = st.form_submit_button(
                    "✉️ 이메일 인증번호 받기",
                    type="primary", use_container_width=True,
                )
            if requested:
                requested_email = normal_email(email)
                if not is_approved(requested_email, config):
                    st.error("승인된 이메일 주소가 아닙니다. 관리자에게 문의하세요.")
                elif not otp_resend_permitted(st.session_state, requested_email):
                    st.warning("인증번호는 60초 간격으로 재발송할 수 있습니다.")
                else:
                    try:
                        request_email_code(config, requested_email)
                        st.session_state[PENDING_KEY] = requested_email
                        st.session_state[LAST_SENT_KEY] = {
                            "email": requested_email, "time": time.time()}
                        st.rerun()
                    except EmailAuthError as exc:
                        st.error(str(exc))
        else:
            st.caption("인증번호 발송 요청: " + pending)
            with st.form("stock_email_otp_verify", clear_on_submit=True):
                code = st.text_input(
                    "이메일 인증번호",
                    type="password",
                    placeholder="메일의 숫자 인증번호",
                    autocomplete="one-time-code",
                    max_chars=10,
                )
                submitted = st.form_submit_button(
                    "🔐 이메일 인증 후 로그인",
                    type="primary", use_container_width=True,
                )
            if submitted:
                try:
                    verified = verify_email_code(config, pending, code)
                    st.session_state[SESSION_KEY] = verified
                    st.session_state.pop(PENDING_KEY, None)
                    st.rerun()
                except EmailAuthError as exc:
                    st.error(str(exc))
            if st.button("다른 이메일 주소 사용", key="change_stock_login_email"):
                st.session_state.pop(PENDING_KEY, None)
                st.rerun()
            st.caption(
                "인증번호가 도착하지 않았다면 스팸함을 확인하세요. "
                "Supabase 기본 메일 제공자에는 발송 한도가 있습니다."
            )
        st.markdown(
            '<div class="hanav-login-footer">APPROVED EMAIL ACCESS · SECURE RESEARCH</div>',
            unsafe_allow_html=True,
        )
    st.stop()
