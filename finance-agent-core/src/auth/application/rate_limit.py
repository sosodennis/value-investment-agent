from __future__ import annotations

from fastapi import HTTPException, Request

from src.audit.application.recording import record_best_effort
from src.audit.domain.entities import AuditOutcome
from src.auth.application.errors import RateLimitExceeded
from src.shared.kernel.rate_limit import (
    RateLimiterUnavailable,
    RateLimitSettings,
    rate_limit_settings,
    rate_limiter,
)


async def enforce_rate_limit(
    *,
    request: Request,
    organization_id: str,
    actor_user_id: str,
    operation: str,
    key_parts: tuple[str, ...],
    limit: int,
    window_seconds: int,
    cost: int = 1,
) -> None:
    """Apply a fail-closed limit and record the security decision."""

    key = ":".join((operation, *key_parts))
    try:
        check_kwargs = {"key": key, "limit": limit, "window_seconds": window_seconds}
        if cost != 1:
            check_kwargs["cost"] = cost
        await rate_limiter.check(**check_kwargs)
    except RateLimitExceeded as error:
        await record_best_effort(
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            action="abuse.rate_limited",
            outcome=AuditOutcome.DENIED,
            target_type="rate_limit",
            target_id=operation,
            correlation_id=request.headers.get("X-Request-ID"),
            payload={
                "operation": operation,
                "retry_after_seconds": error.retry_after_seconds,
            },
        )
        raise HTTPException(
            status_code=429,
            detail={
                "code": "rate_limited",
                "message": str(error),
                "retry_after_seconds": error.retry_after_seconds,
            },
            headers={"Retry-After": str(error.retry_after_seconds)},
        ) from error
    except RateLimiterUnavailable as error:
        await record_best_effort(
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            action="abuse.rate_limiter_unavailable",
            outcome=AuditOutcome.FAILURE,
            target_type="rate_limit",
            target_id=operation,
            correlation_id=request.headers.get("X-Request-ID"),
            payload={"operation": operation},
        )
        raise HTTPException(
            status_code=503,
            detail={"code": "rate_limiter_unavailable"},
            headers={"Retry-After": "5"},
        ) from error


__all__ = [
    "RateLimitSettings",
    "enforce_rate_limit",
    "rate_limit_settings",
    "rate_limiter",
]
