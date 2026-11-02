from __future__ import annotations

import json
import math
import re

from src.shared.kernel.types import JSONObject, JSONValue

REDACTED = "[REDACTED]"
_MAX_DETAIL_DEPTH = 6
_MAX_STRING_LENGTH = 4096
_MAX_ARRAY_ITEMS = 100
_MAX_OBJECT_KEYS = 100
_MAX_DETAILS_BYTES = 32 * 1024

_SENSITIVE_KEY_PARTS = (
    "authorization",
    "cookie",
    "password",
    "secret",
    "token",
    "credential",
    "api_key",
    "apikey",
    "private_key",
)
_FORBIDDEN_KEY_PARTS = (
    "outerhtml",
    "innerhtml",
    "serialized_dom",
    "dom_tree",
    "input_value",
    "request_url",
    "response_url",
    "url",
    "href",
    "query",
    "fragment",
    "request_body",
    "response_body",
    "body",
)
_SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}\b"),
    re.compile(r"\bsk-(?:or-v1-)?[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b"),
    re.compile(r"(?i)(?:https?://|www\.)[^\s\"'<>]+"),
    re.compile(r"(?:^|[?&#])[A-Za-z0-9_.~-]{1,64}=[^\s&#]*"),
    re.compile(
        r"(?i)\b(?:session|csrf|auth|access|refresh)[_-]?(?:token)?\s*[:=]\s*[^\s,;]+"
    ),
)


class ClientDebugPayloadError(ValueError):
    pass


def _normalized_key(key: str) -> str:
    return key.strip().lower().replace("-", "_").replace(" ", "_")


def _is_sensitive_key(key: str) -> bool:
    normalized = _normalized_key(key)
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _is_forbidden_key(key: str) -> bool:
    normalized = _normalized_key(key)
    return any(part in normalized for part in _FORBIDDEN_KEY_PARTS)


def _sanitize(value: object, *, key: str | None, depth: int) -> JSONValue:
    if depth > _MAX_DETAIL_DEPTH:
        raise ClientDebugPayloadError("client debug details are too deeply nested")
    if key is not None and _is_forbidden_key(key):
        raise ClientDebugPayloadError(
            "client debug details contain a forbidden DOM or input field"
        )
    if key is not None and _is_sensitive_key(key):
        return REDACTED
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ClientDebugPayloadError(
                "client debug details contain a non-finite number"
            )
        return value
    if isinstance(value, str):
        if len(value) > _MAX_STRING_LENGTH:
            raise ClientDebugPayloadError(
                "client debug details contain an oversized string"
            )
        if any(pattern.search(value) for pattern in _SENSITIVE_VALUE_PATTERNS):
            return REDACTED
        return value
    if isinstance(value, list | tuple):
        if len(value) > _MAX_ARRAY_ITEMS:
            raise ClientDebugPayloadError(
                "client debug details contain too many array items"
            )
        return [_sanitize(item, key=None, depth=depth + 1) for item in value]
    if isinstance(value, dict):
        if len(value) > _MAX_OBJECT_KEYS:
            raise ClientDebugPayloadError(
                "client debug details contain too many object keys"
            )
        safe: dict[str, JSONValue] = {}
        for raw_key, nested in value.items():
            if not isinstance(raw_key, str) or not raw_key.strip():
                raise ClientDebugPayloadError(
                    "client debug detail keys must be non-empty strings"
                )
            safe[raw_key] = _sanitize(
                nested,
                key=raw_key,
                depth=depth + 1,
            )
        return safe
    raise ClientDebugPayloadError("client debug details contain an unsupported value")


def sanitize_details(value: JSONObject) -> JSONObject:
    sanitized = _sanitize(value, key=None, depth=0)
    if not isinstance(sanitized, dict):
        raise ClientDebugPayloadError("client debug details must be an object")
    encoded = json.dumps(sanitized, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > _MAX_DETAILS_BYTES:
        raise ClientDebugPayloadError("client debug details exceed the 32 KiB limit")
    return sanitized


def require_safe_route(route: str) -> str:
    if not route.startswith("/") or "?" in route or "#" in route:
        raise ValueError("client debug route must be a pathname without query or hash")
    return route
