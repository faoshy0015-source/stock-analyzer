"""Fail-closed adapters for optional external market-data providers.

A single supplemental feed must never take down the whole analyst dashboard.
Failures remain visible as source-specific diagnostic types; no raw exception
messages, keys, tokens, URLs or response bodies enter the UI.
"""
from __future__ import annotations


def optional_fetch(source, operation, fallback_factory, issues, validator=None):
    """Return the provider value, or explicitly missing data plus a warning.

    This helper does not cache a failed result. Use around cached providers,
    not inside their cache decorators, to permit retries on the next rerun.
    """
    try:
        value = operation()
        if validator is not None and not validator(value):
            raise TypeError("Unexpected provider value structure")
        return value
    except Exception as exc:
        issues.append(f"{source}: {type(exc).__name__} · 응답 형식 또는 연결 상태 확인 필요")
        return fallback_factory()
