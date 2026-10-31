from __future__ import annotations

import email.utils
import time
from collections.abc import Mapping

from src.llm_provider_service.domain.reliability import (
    FailureCategory,
    FailureScope,
    UpstreamFailure,
)


def _token(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower().replace("-", "_")
    return normalized or None


def _value(value: object, name: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _metadata(exc: Exception, response: object) -> Mapping[str, object]:
    candidates = (
        _value(exc, "body"),
        _value(response, "body"),
        _value(response, "json"),
    )
    for candidate in candidates:
        if callable(candidate):
            try:
                candidate = candidate()
            except Exception:
                continue
        error = _value(candidate, "error")
        metadata = _value(error, "metadata")
        if isinstance(metadata, Mapping):
            return metadata
    return {}


def _error_type(exc: Exception, response: object) -> object:
    candidates = (_value(exc, "body"), _value(response, "body"))
    for candidate in candidates:
        error = _value(candidate, "error")
        value = _value(error, "error_type") or _value(error, "type")
        if value is not None:
            return value
    return _value(exc, "category")


def _retry_after(response: object) -> float | None:
    headers = _value(response, "headers", {})
    raw = _value(headers, "retry-after")
    if raw is None:
        raw = _value(headers, "Retry-After")
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        try:
            parsed = email.utils.parsedate_to_datetime(str(raw))
            return max(0.0, parsed.timestamp() - time.time())
        except (TypeError, ValueError, OverflowError):
            return None


def _is_timeout(exc: Exception) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    exception_name = type(exc).__name__.lower()
    if exception_name in {
        "timeout",
        "apitimeouterror",
        "readtimeout",
        "connecttimeout",
    }:
        return True
    return _token(_value(exc, "category")) in {"timeout", "timed_out"}


def classify_exception(
    exc: Exception, deployment_id: str | None = None
) -> UpstreamFailure:
    response = _value(exc, "response")
    status = _value(exc, "status_code") or _value(response, "status_code")
    status = status if isinstance(status, int) else None
    metadata = _metadata(exc, response)
    source = _token(metadata.get("limit_source"))
    error_type = _token(metadata.get("error_type") or _error_type(exc, response))
    rate_type = _token(_value(exc, "rate_limit_type"))
    provider_code = metadata.get("provider_code")
    provider_scoped = provider_code is not None or rate_type in {"provider", "upstream"}
    retry_after = _retry_after(response)
    if retry_after is None:
        retry_after = _retry_after(exc)

    if provider_scoped and source is not None:
        scope = FailureScope.UNKNOWN
        category = (
            FailureCategory.CREDIT if status == 402 else FailureCategory.RATE_LIMIT
        )
    elif source == "openrouter_key_limit":
        scope = FailureScope.KEY
        category = FailureCategory.CREDIT
    elif source in {
        "openrouter_credits",
        "openrouter_in_flight_budget",
        "openrouter_workspace_budget",
        "openrouter_guardrail_budget",
    }:
        scope = (
            FailureScope.ACCOUNT
            if source == "openrouter_credits"
            else FailureScope.WORKSPACE
        )
        category = FailureCategory.CREDIT
    elif provider_scoped:
        scope = FailureScope.UPSTREAM_PROVIDER
        category = FailureCategory.RATE_LIMIT
    elif status == 429:
        scope = FailureScope.UNKNOWN
        category = FailureCategory.RATE_LIMIT
    elif status == 402:
        scope = FailureScope.UNKNOWN
        category = FailureCategory.CREDIT
    elif status == 401:
        # A request sent with one managed credential cannot authenticate.  It
        # is safe to retire this key and try another key owned by the same user.
        scope = FailureScope.KEY
        category = FailureCategory.AUTHENTICATION
    elif status == 403 and error_type in {
        "authentication",
        "authentication_error",
    }:
        scope = FailureScope.KEY
        category = FailureCategory.AUTHENTICATION
    elif status in {401, 403}:
        scope = FailureScope.UNKNOWN
        category = FailureCategory.AUTHENTICATION
    elif status in {408, 504} or _is_timeout(exc):
        scope = FailureScope.UNKNOWN
        category = FailureCategory.TIMEOUT
    elif status == 400:
        scope = FailureScope.MODEL
        category = FailureCategory.BAD_REQUEST
    else:
        scope = FailureScope.UNKNOWN
        category = FailureCategory.UNAVAILABLE

    retryable = category in {
        FailureCategory.RATE_LIMIT,
        FailureCategory.TIMEOUT,
        FailureCategory.UNAVAILABLE,
    }
    if category is FailureCategory.CREDIT:
        retryable = source in {"openrouter_in_flight_budget", "openrouter_key_limit"}
    return UpstreamFailure(
        category=category,
        scope=scope,
        retryable=retryable,
        retry_after_seconds=retry_after,
        deployment_id=deployment_id or _value(exc, "failed_deployment_id"),
        http_status=status,
        reason="LLM provider request failed",
    )
