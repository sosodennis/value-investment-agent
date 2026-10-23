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
]
