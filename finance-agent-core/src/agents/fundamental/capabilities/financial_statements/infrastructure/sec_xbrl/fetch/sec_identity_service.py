from __future__ import annotations

import os
from threading import Lock

from edgar import configure_http, set_identity

_SEC_IDENTITY = "ValueInvestmentAgent research@example.com"
_SEC_IDENTITY_CONFIGURED = False
_SEC_HTTP_CONFIGURED = False
_SEC_IDENTITY_LOCK = Lock()
_SEC_HTTP_TIMEOUT_SECONDS = 45.0


def _resolve_sec_http_timeout_seconds() -> float:
    raw = os.getenv("SEC_HTTP_TIMEOUT_SECONDS")
    if raw is None:
        return _SEC_HTTP_TIMEOUT_SECONDS
    try:
        timeout = float(raw)
    except ValueError:
        return _SEC_HTTP_TIMEOUT_SECONDS
    return max(5.0, timeout)


def ensure_sec_identity() -> None:
    global _SEC_HTTP_CONFIGURED
    global _SEC_IDENTITY_CONFIGURED

    if _SEC_IDENTITY_CONFIGURED:
        return

    with _SEC_IDENTITY_LOCK:
        if _SEC_IDENTITY_CONFIGURED:
            return
        if not _SEC_HTTP_CONFIGURED:
            configure_http(timeout=_resolve_sec_http_timeout_seconds())
            _SEC_HTTP_CONFIGURED = True
        set_identity(_SEC_IDENTITY)
        _SEC_IDENTITY_CONFIGURED = True
