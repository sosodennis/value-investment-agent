"""Authentication and parsing at the internal-service request boundary."""

from __future__ import annotations

import hmac
from collections.abc import Mapping

from pydantic import ValidationError

from .contracts import InternalRequestContext


class InternalAuthenticationError(ValueError):
    """Safe-to-log caller authentication failure."""

    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class InternalContextValidationError(ValueError):
    """Safe-to-log malformed request context failure."""

    def __init__(self) -> None:
        super().__init__("internal request context is invalid")


def authenticate_internal_request(
    authorization: str | None,
    *,
    expected_token: str | None,
    raw_context: Mapping[str, object],
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
        return InternalRequestContext.model_validate(raw_context)
    except ValidationError as exc:
        raise InternalContextValidationError() from exc
