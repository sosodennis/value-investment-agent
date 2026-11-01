"""Authentication and parsing at the internal-service request boundary."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError

from .contracts import (
    INTERNAL_CONTRACT_VERSION,
    InternalPrincipal,
    InternalRequestContext,
)

INTERNAL_CONTEXT_ISSUER = "finance-agent-core"
_CLOCK_SKEW = timedelta(seconds=5)


class InternalAuthenticationError(ValueError):
    """Safe-to-log caller authentication failure."""

    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class InternalContextValidationError(ValueError):
    """Safe-to-log malformed request context failure."""

    def __init__(self) -> None:
        super().__init__("internal request context is invalid")


def _canonical_context(context: InternalRequestContext) -> bytes:
    return json.dumps(
        context.model_dump(mode="json", exclude={"signature"}),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sign_internal_context(context: InternalRequestContext, *, signing_key: str) -> str:
    if not signing_key:
        raise ValueError("internal context signing key is required")
    return hmac.new(
        signing_key.encode("utf-8"), _canonical_context(context), hashlib.sha256
    ).hexdigest()


def build_internal_context(
    *,
    principal: InternalPrincipal,
    correlation_id: str,
    deadline_at: datetime,
    audience: str,
    signing_key: str,
    issuer: str = INTERNAL_CONTEXT_ISSUER,
    issued_at: datetime | None = None,
) -> InternalRequestContext:
    issued = issued_at or datetime.now(UTC)
    context = InternalRequestContext(
        principal=principal,
        correlation_id=correlation_id,
        contract_version=INTERNAL_CONTRACT_VERSION,
        deadline_at=deadline_at,
        audience=audience,
        issuer=issuer,
        issued_at=issued,
    )
    return context.model_copy(
        update={"signature": sign_internal_context(context, signing_key=signing_key)}
    )


def authenticate_internal_request(
    authorization: str | None,
    *,
    expected_token: str | None,
    raw_context: Mapping[str, object],
    expected_audience: str | None = None,
    expected_issuer: str | None = None,
    signing_key: str | None = None,
    organization_header: str | None = None,
    now: datetime | None = None,
) -> InternalRequestContext:
    """Authenticate the backend caller before trusting the principal context.

    The shared secret identifies the trusted backend caller. The principal is
    accepted only after that check and is parsed into a typed model.
    Browser cookies, browser bearer credentials, and provider keys are not part
    of this function's input or output.
    """

    if not expected_token:
        raise InternalAuthenticationError(
            code="internal_auth_unconfigured",
            message="internal service authentication is not configured",
        )
    if authorization is None or not authorization.startswith("Bearer "):
        raise InternalAuthenticationError(
            code="internal_auth_missing",
            message="internal service authentication is required",
        )
    presented_token = authorization.removeprefix("Bearer ")
    if not presented_token or not hmac.compare_digest(presented_token, expected_token):
        raise InternalAuthenticationError(
            code="internal_auth_invalid",
            message="internal service authentication failed",
        )
    try:
        context = InternalRequestContext.model_validate(raw_context)
    except ValidationError as exc:
        raise InternalContextValidationError() from exc

    strict_context = any(
        value is not None for value in (expected_audience, expected_issuer, signing_key)
    )
    if strict_context:
        key = signing_key or expected_token
        if not key:
            raise InternalAuthenticationError(
                code="internal_context_unconfigured",
                message="internal context authentication is not configured",
            )
        if context.audience is not None and context.audience != expected_audience:
            raise InternalAuthenticationError(
                code="internal_context_claims_invalid",
                message="internal request context claims are invalid",
            )
        if context.issuer is not None and context.issuer != (
            expected_issuer or INTERNAL_CONTEXT_ISSUER
        ):
            raise InternalAuthenticationError(
                code="internal_context_claims_invalid",
                message="internal request context claims are invalid",
            )
        current = now or datetime.now(UTC)
        if (
            organization_header is not None
            and organization_header != context.principal.organization_id
        ):
            raise InternalAuthenticationError(
                code="internal_context_organization_mismatch",
                message="organization header does not match the request context",
            )
        if (
            context.audience != expected_audience
            or context.issuer != (expected_issuer or INTERNAL_CONTEXT_ISSUER)
            or context.issued_at is None
            or context.signature is None
            or context.principal.organization_id is None
            or context.principal.membership_id is None
        ):
            raise InternalAuthenticationError(
                code="internal_context_claims_invalid",
                message="internal request context claims are invalid",
            )
        if not hmac.compare_digest(
            context.signature, sign_internal_context(context, signing_key=key)
        ):
            raise InternalAuthenticationError(
                code="internal_context_signature_invalid",
                message="internal request context signature is invalid",
            )
        if context.issued_at > current + _CLOCK_SKEW:
            raise InternalAuthenticationError(
                code="internal_context_issued_at_invalid",
                message="internal request context issued time is invalid",
            )
        if context.deadline_at <= context.issued_at:
            raise InternalAuthenticationError(
                code="internal_context_deadline_invalid",
                message="internal request context deadline is invalid",
            )
    elif (
        organization_header is not None
        and organization_header != context.principal.organization_id
    ):
        raise InternalAuthenticationError(
            code="internal_context_organization_mismatch",
            message="organization header does not match the request context",
        )
    return context
