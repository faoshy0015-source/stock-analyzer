"""Separate administrator authorization for manual data and cache operations.

The normal APP_PASSWORD never unlocks administrator actions. ADMIN_PASSWORD
is read from Streamlit Secrets only. Unlock expires after 15 minutes or when
the configured administrator password changes.
"""
from __future__ import annotations

import hashlib
import hmac
import time

ADMIN_SESSION_KEY = "_stock_analyzer_admin_grant"
FAILED_ATTEMPTS_KEY = "_stock_analyzer_admin_failures"
MAX_ATTEMPTS = 5
LOCKOUT_SECONDS = 300
ADMIN_TTL_SECONDS = 900


def configured_admin_password(secrets):
    try:
        candidate = secrets.get("ADMIN_PASSWORD")
    except Exception:
        return None
    if isinstance(candidate, str) and candidate.strip():
        return candidate
    return None


def _fingerprint(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def is_admin_unlocked(state, secret, now=None):
    if not isinstance(secret, str) or not secret:
        return False
    current = time.time() if now is None else now
    grant = state.get(ADMIN_SESSION_KEY)
    return (
        isinstance(grant, dict)
        and grant.get("fingerprint") == _fingerprint(secret)
        and isinstance(grant.get("until"), (int, float))
        and current < grant["until"]
    )


def grant_admin(state, submitted, secret, now=None):
    """Return (success, reason), never persist the plain text password."""
    current = time.time() if now is None else now
    if not secret:
        return False, "관리자 비밀번호(ADMIN_PASSWORD)가 설정되지 않았습니다."
    block = state.get(FAILED_ATTEMPTS_KEY)
    if isinstance(block, dict) and block.get("until", 0) > current:
        return False, "관리자 인증 시도가 많아 잠시 잠겼습니다."
    if not isinstance(submitted, str) or not hmac.compare_digest(
        submitted.encode("utf-8"), secret.encode("utf-8")
    ):
        count = (block.get("count", 0) if isinstance(block, dict) else 0) + 1
        if count >= MAX_ATTEMPTS:
            state[FAILED_ATTEMPTS_KEY] = {
                "count": 0, "until": current + LOCKOUT_SECONDS
            }
            return False, "관리자 인증 시도가 많아 잠시 잠겼습니다."
        state[FAILED_ATTEMPTS_KEY] = {"count": count, "until": 0}
        return False, "관리자 비밀번호가 올바르지 않습니다."
    state.pop(FAILED_ATTEMPTS_KEY, None)
    state[ADMIN_SESSION_KEY] = {
        "fingerprint": _fingerprint(secret),
        "until": current + ADMIN_TTL_SECONDS,
    }
    return True, "관리자 기능이 15분간 열렸습니다."


def lock_admin(state):
    state.pop(ADMIN_SESSION_KEY, None)


def render_admin_controls(st, *, krx_loader, dart_loader=None):
    """All management buttons are constructed only after authorization.

    The loader functions are invoked on the server *inside* the access check.
    """
    with st.sidebar:
        with st.expander("🔐 관리자 도구", expanded=False):
            secret = configured_admin_password(st.secrets)
            if not secret:
                st.warning(
                    "관리자 기능이 잠겨 있습니다. Streamlit Cloud → "
                    "Settings → Secrets에 별도의 ADMIN_PASSWORD를 설정하세요."
                )
                return
            if not is_admin_unlocked(st.session_state, secret):
                with st.form("stock_analyzer_admin_login", clear_on_submit=True):
                    password = st.text_input(
                        "관리자 비밀번호", type="password",
                        placeholder="관리자 비밀번호를 입력하세요",
                        autocomplete="off",
                    )
                    submitted = st.form_submit_button(
                        "관리자 모드 열기", use_container_width=True
                    )
                if submitted:
                    success, message = grant_admin(
                        st.session_state, password, secret
                    )
                    if success:
                        st.rerun()
                    else:
                        st.error(message)
                return

            st.success("관리자 모드 활성화 · 15분 후 자동 잠금")
            st.caption("종목 목록 수동 갱신과 캐시 초기화는 관리자 전용입니다.")
            if st.button(
                "KRX 전체 종목 목록 불러오기",
                key="admin_krx_listing",
                use_container_width=True,
            ) and is_admin_unlocked(st.session_state, secret):
                krx_loader()
            if dart_loader is not None:
                if st.button(
                    "DART 상장사 목록 불러오기",
                    key="admin_dart_listing",
                    use_container_width=True,
                ) and is_admin_unlocked(st.session_state, secret):
                    dart_loader()
            if st.button(
                "새로고침 (캐시 초기화)",
                key="admin_clear_data_cache",
                use_container_width=True,
            ) and is_admin_unlocked(st.session_state, secret):
                st.cache_data.clear()
                st.rerun()
            if st.button(
                "🔒 관리자 모드 잠금",
                key="admin_lock_tools",
                use_container_width=True,
            ):
                lock_admin(st.session_state)
                st.rerun()
