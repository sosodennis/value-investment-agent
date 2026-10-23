from __future__ import annotations

from contextvars import ContextVar, Token

from ..domain.contracts import ProviderPrincipal

_provider_principal: ContextVar[ProviderPrincipal | None] = ContextVar(
    "provider_principal", default=None
)


def set_provider_principal(
    principal: ProviderPrincipal,
) -> Token[ProviderPrincipal | None]:
    return _provider_principal.set(principal)


def reset_provider_principal(token: Token[ProviderPrincipal | None]) -> None:
    _provider_principal.reset(token)


def get_provider_principal() -> ProviderPrincipal | None:
    return _provider_principal.get()
