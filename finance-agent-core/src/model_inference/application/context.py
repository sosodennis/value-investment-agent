from __future__ import annotations

from contextvars import ContextVar, Token

from src.shared.internal_services import InternalPrincipal

_inference_principal: ContextVar[InternalPrincipal | None] = ContextVar(
    "model_inference_principal", default=None
)


def set_inference_principal(subject_id: str) -> Token[InternalPrincipal | None]:
    return _inference_principal.set(InternalPrincipal(subject_id=subject_id))


def reset_inference_principal(token: Token[InternalPrincipal | None]) -> None:
    _inference_principal.reset(token)


def get_inference_principal() -> InternalPrincipal | None:
    return _inference_principal.get()
