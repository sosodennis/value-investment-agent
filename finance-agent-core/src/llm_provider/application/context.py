"""Request-local provider identity propagation.

The graph is compiled once and reused across requests, so user identity cannot
be stored on singleton agent wiring. A context variable keeps the verified
principal request-local while preserving the existing agent-facing contract.
"""

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
