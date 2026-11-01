"""Domain-neutral request and background-work correlation context."""

from __future__ import annotations

from contextvars import ContextVar, Token
from uuid import uuid4

MAX_CORRELATION_ID_LENGTH = 128

_correlation_id: ContextVar[str | None] = ContextVar(
    "request_correlation_id", default=None
)


def _is_safe(value: str) -> bool:
    return (
        bool(value)
        and len(value) <= MAX_CORRELATION_ID_LENGTH
        and all(0x21 <= ord(character) <= 0x7E for character in value)
    )


def normalize_correlation_id(value: str | None) -> str:
    """Bound an inbound identifier or generate one at the request boundary."""

    candidate = (value or "").strip()
    if _is_safe(candidate):
        return candidate
    return uuid4().hex


def set_correlation_id(value: str) -> Token[str | None]:
    return _correlation_id.set(value)


def reset_correlation_id(token: Token[str | None]) -> None:
    _correlation_id.reset(token)


def current_correlation_id() -> str | None:
    return _correlation_id.get()


def resolve_correlation_id(value: str | None = None) -> str:
    """Resolve explicit, request-local, or autonomous correlation metadata."""

    explicit = (value or "").strip()
    if _is_safe(explicit):
        return explicit
    inherited = current_correlation_id()
    return inherited or uuid4().hex
