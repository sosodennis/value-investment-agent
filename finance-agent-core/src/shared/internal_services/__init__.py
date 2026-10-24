"""Stable primitives for calls to independently deployed internal services."""

from .auth import (
    InternalAuthenticationError,
    InternalContextValidationError,
    authenticate_internal_request,
)
from .contracts import (
    INTERNAL_CONTRACT_VERSION,
    InternalError,
    InternalErrorResponse,
    InternalPrincipal,
    InternalReadiness,
    InternalRequestContext,
    ReadinessStatus,
)
from .principal_context import (
    get_request_principal,
    reset_request_principal,
    set_request_principal,
)

__all__ = [
    "INTERNAL_CONTRACT_VERSION",
    "InternalAuthenticationError",
    "InternalContextValidationError",
    "InternalError",
    "InternalErrorResponse",
    "InternalPrincipal",
    "InternalReadiness",
    "InternalRequestContext",
    "ReadinessStatus",
    "authenticate_internal_request",
    "get_request_principal",
    "reset_request_principal",
    "set_request_principal",
]
