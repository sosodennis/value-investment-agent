from __future__ import annotations

from contextvars import ContextVar, Token

from src.shared.internal_services import InternalPrincipal

_inference_principal: ContextVar[InternalPrincipal | None] = ContextVar(
    "model_inference_principal", default=None
)


def set_inference_principal(
    principal: InternalPrincipal | str,
    *,
    organization_id: str | None = None,
    membership_id: str | None = None,
) -> Token[InternalPrincipal | None]:
    if isinstance(principal, str):
        principal = InternalPrincipal(
            subject_id=principal,
            organization_id=organization_id,
            membership_id=membership_id,
        )
    return _inference_principal.set(principal)


def reset_inference_principal(token: Token[InternalPrincipal | None]) -> None:
    _inference_principal.reset(token)


def get_inference_principal() -> InternalPrincipal | None:
    return _inference_principal.get()
