from __future__ import annotations

from contextvars import ContextVar, Token

from .contracts import InternalPrincipal

_request_principal: ContextVar[InternalPrincipal | None] = ContextVar(
    "internal_request_principal", default=None
)


def set_request_principal(
    principal: InternalPrincipal,
) -> Token[InternalPrincipal | None]:
    return _request_principal.set(principal)


def reset_request_principal(token: Token[InternalPrincipal | None]) -> None:
    _request_principal.reset(token)


def get_request_principal() -> InternalPrincipal | None:
    return _request_principal.get()
