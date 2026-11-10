"""Server-side email allowlist and Supabase Auth one-time-code verification.

No shared-password fallback. User-supplied emails and existing Streamlit
session flags are never treated as authentication. Every rerun validates the
Supabase-issued access token against the Auth server and rechecks the allowlist.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import time
from urllib.parse import urlparse

import requests

_EMAIL = re.compile(r"^[A-Za-z0-9.!#$%&'*+\-/=?^_`{|}~]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
_CODE = re.compile(r"^[0-9]{6,10}$")
SESSION_KEY = "_stock_verified_email_session"
PENDING_KEY = "_stock_pending_email"
LAST_SENT_KEY = "_stock_last_email_otp_sent"
# Supabase email rate limiting also applies. This reduces accidental repeated
# sends within a single browser session; it is NOT a substitute for server limits.
RESEND_WAIT_SECONDS = 60


class EmailAuthError(RuntimeError):
    """A user-displayable error that never includes tokens or response bodies."""


@dataclass(frozen=True)
class EmailAuthConfig:
    url: str
    anon_key: str
    allowlist: frozenset[str]


def normal_email(value):
    if not isinstance(value, str):
        return ""
    return value.strip().casefold()


def parse_approved_emails(value):
    """Only exact addresses are allowed; no domains, glob patterns or wildcards."""
    if isinstance(value, (list, tuple, set)):
        candidates = list(value)
    elif isinstance(value, str):
        candidates = re.split(r"[,;\n]", value)
    else:
        candidates = []
    result = set()
    for candidate in candidates:
        address = normal_email(candidate)
        if not address:
            continue
        if len(address) > 254 or not _EMAIL.fullmatch(address):
            raise EmailAuthError(
                "APP_ALLOWED_EMAILS에는 구체적인 이메일 주소만 등록하세요. "
                "와일드카드·도메인 전체 허용은 지원하지 않습니다."
            )
        result.add(address)
    return frozenset(result)


def _secret(secrets, key):
    try:
        value = secrets.get(key, "")
    except Exception:
        return ""
    return value


def get_email_auth_config(secrets):
    url = str(_secret(secrets, "SUPABASE_URL") or "").strip().rstrip("/")
    key = str(_secret(secrets, "SUPABASE_ANON_KEY") or "").strip()
    allowed = parse_approved_emails(_secret(secrets, "APP_ALLOWED_EMAILS"))
    if not allowed:
        raise EmailAuthError(
            "승인 이메일 목록 미설정: Streamlit Secrets의 APP_ALLOWED_EMAILS에 "
            "본인 이메일을 포함해 승인할 주소를 등록해야 합니다."
        )
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.path not in ("", "/"):
        raise EmailAuthError("SUPABASE_URL에는 https://...supabase.co 프로젝트 주소가 필요합니다.")
    if not key:
        raise EmailAuthError(
            "SUPABASE_ANON_KEY 미설정: Supabase 프로젝트의 공개용 anon 키를 "
            "Streamlit Secrets에 등록해야 합니다. service_role 키는 사용하지 않습니다."
        )
    return EmailAuthConfig(url, key, allowed)


def is_approved(email, config):
    return normal_email(email) in config.allowlist


def _headers(config, access_token=None):
    headers = {"apikey": config.anon_key, "Content-Type": "application/json"}
    if access_token:
        headers["Authorization"] = "Bearer " + access_token
    return headers


def _post_json(config, endpoint, data, *, session=None, timeout=12):
    post = session.post if session is not None else requests.post
    try:
        response = post(
            config.url + endpoint,
            json=data,
            headers=_headers(config),
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise EmailAuthError("인증 서버 접속 실패: " + type(exc).__name__) from None
    return response


def request_email_code(config, email, *, session=None):
    """Send OTP only to an exact admin-approved email; never create other users."""
    email = normal_email(email)
    if not is_approved(email, config) or not _EMAIL.fullmatch(email):
        # Avoid returning the email or disclosing account existence.
        raise EmailAuthError("승인되지 않은 이메일입니다. 관리자에게 접근 권한을 요청하세요.")
    response = _post_json(
        config, "/auth/v1/otp",
        {"email": email, "create_user": True},
        session=session,
    )
    if response.status_code == 429:
        raise EmailAuthError("인증 요청 횟수가 초과됐습니다. 잠시 후 다시 시도하세요.")
    if not response.ok:
        raise EmailAuthError(
            f"이메일 인증번호 발송 실패 (HTTP {response.status_code}). "
            "Supabase Auth 이메일 제공자·발송 제한·인증 설정을 확인하세요."
        )
    return True


def _json_response(response, stage):
    try:
        obj = response.json()
    except (ValueError, TypeError):
        raise EmailAuthError(f"{stage}: 인증 서버가 유효한 JSON을 반환하지 않았습니다.") from None
    if not isinstance(obj, dict):
        raise EmailAuthError(f"{stage}: 인증 서버 응답 형식이 올바르지 않습니다.")
    return obj


def verify_email_code(config, email, code, *, session=None):
    """Verify the email OTP, then obtain authoritative identity via /user."""
    email = normal_email(email)
    if not is_approved(email, config):
        raise EmailAuthError("승인 이메일 목록에 없는 계정입니다.")
    if not isinstance(code, str) or not _CODE.fullmatch(code.strip()):
        raise EmailAuthError("이메일에 전송된 숫자 인증번호를 입력하세요.")
    response = _post_json(
        config, "/auth/v1/verify",
        {"email": email, "token": code.strip(), "type": "email"},
        session=session,
    )
    if not response.ok:
        raise EmailAuthError(
            "인증번호가 유효하지 않거나 만료됐습니다. 메일의 인증번호를 다시 확인하세요."
        )
    payload = _json_response(response, "인증번호 검증")
    token = payload.get("access_token")
    refresh = payload.get("refresh_token")
    if not isinstance(token, str) or not token or not isinstance(refresh, str) or not refresh:
        raise EmailAuthError("인증 세션이 발급되지 않았습니다.")
    session_data = {"access_token": token, "refresh_token": refresh}
    verified = validate_session(config, session_data, session=session)
    if verified is None or verified["email"] != email:
        raise EmailAuthError("서버에서 확인한 이메일 주소가 요청한 계정과 다릅니다.")
    return verified


def get_auth_user(config, access_token, *, session=None):
    """Never trust a decoded JWT or client-provided email without server validation."""
    get = session.get if session is not None else requests.get
    try:
        response = get(
            config.url + "/auth/v1/user",
            headers=_headers(config, access_token),
            timeout=10,
        )
    except requests.RequestException as exc:
        raise EmailAuthError("사용자 인증 확인 실패: " + type(exc).__name__) from None
    if response.status_code in (401, 403):
        return None
    if not response.ok:
        raise EmailAuthError(f"사용자 인증 서버 오류 (HTTP {response.status_code})")
    user = _json_response(response, "사용자 확인")
    email = normal_email(user.get("email"))
    if not email or not isinstance(user.get("id"), str):
        raise EmailAuthError("인증 서버가 사용자 정보를 반환하지 않았습니다.")
    if not is_approved(email, config):
        return None
    return {"id": user["id"], "email": email}


def _refresh_session(config, refresh, *, session=None):
    response = _post_json(
        config, "/auth/v1/token?grant_type=refresh_token",
        {"refresh_token": refresh},
        session=session,
    )
    if not response.ok:
        return None
    payload = _json_response(response, "인증 세션 갱신")
    access = payload.get("access_token")
    new_refresh = payload.get("refresh_token")
    if not isinstance(access, str) or not access or not isinstance(new_refresh, str) or not new_refresh:
        return None
    return {"access_token": access, "refresh_token": new_refresh}


def validate_session(config, stored, *, session=None):
    """Call Supabase Auth on every view; refresh once if its token expired.

    A stale email in Streamlit session_state is never enough. If the owner
    revokes an address, the very next page rerun denies access immediately.
    """
    if not isinstance(stored, dict):
        return None
    access = stored.get("access_token")
    refresh = stored.get("refresh_token")
    if not isinstance(access, str) or not access:
        return None
    identity = get_auth_user(config, access, session=session)
    if identity is None and isinstance(refresh, str) and refresh:
        renewed = _refresh_session(config, refresh, session=session)
        if renewed:
            access = renewed["access_token"]
            refresh = renewed["refresh_token"]
            identity = get_auth_user(config, access, session=session)
    if identity is None:
        return None
    return {
        "access_token": access,
        "refresh_token": refresh,
        "email": identity["email"],
        "user_id": identity["id"],
    }


def clear_auth_state(st):
    """Clear *all* cached page session data before a new user can sign in."""
    st.session_state.clear()


def otp_resend_permitted(session_state, email, now=None):
    now = time.time() if now is None else now
    record = session_state.get(LAST_SENT_KEY, {})
    return not (
        isinstance(record, dict)
        and record.get("email") == normal_email(email)
        and now - float(record.get("time", 0)) < RESEND_WAIT_SECONDS
    )
