from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import TypeAlias

from .errors import NotificationPayloadError

JsonValue: TypeAlias = (
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)


class NotificationType(str, Enum):
    ORGANIZATION_INVITATION = "organization.invitation"
    ORGANIZATION_MEMBERSHIP = "organization.membership"
    SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class NotificationAction:
    """Stable, opaque action metadata for a future invitation workflow."""

    action_type: str
    action_ref: str


@dataclass(frozen=True, slots=True)
class NotificationEvent:
    id: str
    event_key: str
    notification_type: NotificationType
    organization_id: str | None
    payload: dict[str, JsonValue]
    action: NotificationAction | None
    occurred_at: datetime
    expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class NotificationInboxItem:
    id: str
    event_id: str
    recipient_user_id: str
    notification_type: NotificationType
    organization_id: str | None
    payload: dict[str, JsonValue]
    action: NotificationAction | None
    read_at: datetime | None
    created_at: datetime
    expires_at: datetime | None


_FORBIDDEN_PAYLOAD_KEY_PARTS = frozenset(
    {
        "api_key",
        "authorization",
        "credential",
        "cookie",
        "password",
        "secret",
        "token",
    }
)
_MAX_PAYLOAD_BYTES = 16 * 1024
_MAX_PAYLOAD_DEPTH = 5
_SAFE_ACTION_TYPE_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
_SAFE_ACTION_REF_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$")
_SENSITIVE_VALUE_PATTERNS = (
    re.compile(
        r"(?i)\b(?:api[_-]?key|authorization|credential|password|secret|token)\b\s*[:=]\s*\S+"
    ),
    re.compile(
        r"(?i)\b(?:https?|wss?)://[^\s]*[?&](?:api[_-]?key|authorization|credential|password|secret|token)="
    ),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"\bsk-(?:or-v1-)?[A-Za-z0-9_-]{12,}\b"),
)


def require_utc(value: datetime, *, field_name: str) -> datetime:
    """Require an aware timestamp and normalize it to UTC."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")
    return value.astimezone(UTC)


def validate_notification_action(action: NotificationAction | None) -> None:
    """Keep action references opaque and free of URLs or credential material."""

    if action is None:
        return
    if not _SAFE_ACTION_TYPE_VALUE.fullmatch(action.action_type):
        raise ValueError("notification action type is invalid")
    if not _SAFE_ACTION_REF_VALUE.fullmatch(action.action_ref):
        raise ValueError("notification action reference is invalid")


def validate_notification_payload(payload: object) -> dict[str, JsonValue]:
    """Validate a small JSON payload and reject credential-like fields."""

    if not isinstance(payload, dict):
        raise NotificationPayloadError("notification payload must be an object")

    def validate_value(value: object, *, depth: int) -> JsonValue:
        if depth > _MAX_PAYLOAD_DEPTH:
            raise NotificationPayloadError("notification payload is too deeply nested")
        if value is None or isinstance(value, bool | int):
            return value
        if isinstance(value, float):
            if not math.isfinite(value):
                raise NotificationPayloadError(
                    "notification payload contains a non-finite number"
                )
            return value
        if isinstance(value, str):
            if any(pattern.search(value) for pattern in _SENSITIVE_VALUE_PATTERNS):
                raise NotificationPayloadError(
                    "notification payload contains credential-like material"
                )
            return value
        if isinstance(value, list):
            return [validate_value(item, depth=depth + 1) for item in value]
        if isinstance(value, dict):
            safe: dict[str, JsonValue] = {}
            for key, nested in value.items():
                if not isinstance(key, str) or not key:
                    raise NotificationPayloadError(
                        "notification payload keys must be strings"
                    )
                normalized_key = key.strip().lower().replace("-", "_")
                if any(part in normalized_key for part in _FORBIDDEN_PAYLOAD_KEY_PARTS):
                    raise NotificationPayloadError(
                        f"notification payload key '{key}' is not allowed"
                    )
                safe[key] = validate_value(nested, depth=depth + 1)
            return safe
        raise NotificationPayloadError(
            "notification payload contains an unsupported value"
        )

    validated = validate_value(payload, depth=0)
    if not isinstance(validated, dict):
        raise NotificationPayloadError("notification payload must be an object")
    encoded = json.dumps(validated, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > _MAX_PAYLOAD_BYTES:
        raise NotificationPayloadError("notification payload exceeds 16 KiB")
    return validated
