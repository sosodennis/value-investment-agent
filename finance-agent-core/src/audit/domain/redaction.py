from __future__ import annotations

from collections.abc import Mapping

from .entities import JsonValue

REDACTED = "[REDACTED]"
_SENSITIVE_KEY_PARTS = (
    "secret",
    "token",
    "password",
    "credential",
    "authorization",
    "api_key",
    "apikey",
    "private_key",
    "action_ref",
    "action_material",
    "invitation_code",
)


def redact_payload(value: Mapping[str, object]) -> dict[str, JsonValue]:
    """Return a JSON-safe payload with credential and action material removed."""

    return {str(key): _redact_value(str(key), item) for key, item in value.items()}


def _redact_value(key: str, value: object) -> JsonValue:
    normalized = key.casefold().replace("-", "_")
    if any(part in normalized for part in _SENSITIVE_KEY_PARTS):
        return REDACTED
    if isinstance(value, Mapping):
        return redact_payload(value)
    if isinstance(value, list | tuple):
        return [_redact_value(key, item) for item in value]
    if value is None or isinstance(value, bool | int | float | str):
        return value
    return str(value)
