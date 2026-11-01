"""Stable primitives for calls to independently deployed internal services."""

from .auth import (
    INTERNAL_CONTEXT_ISSUER,
    InternalAuthenticationError,
    InternalContextValidationError,
    authenticate_internal_request,
    build_internal_context,
    sign_internal_context,
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
    "INTERNAL_CONTEXT_ISSUER",
    "InternalAuthenticationError",
    "InternalContextValidationError",
    "InternalError",
    "InternalErrorResponse",
    "InternalPrincipal",
    "InternalReadiness",
    "InternalRequestContext",
    "ReadinessStatus",
    "authenticate_internal_request",
    "build_internal_context",
    "sign_internal_context",
    "get_request_principal",
    "reset_request_principal",
    "set_request_principal",
]
