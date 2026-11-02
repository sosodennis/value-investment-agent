from __future__ import annotations

import os
from dataclasses import dataclass

_DEFAULT_TTL_SECONDS = 24 * 60 * 60
_MAX_TTL_SECONDS = 7 * 24 * 60 * 60
MAX_CLIENT_DEBUG_REQUEST_BYTES = 256 * 1024


def _flag(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _bounded_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return min(max(value, minimum), maximum)


@dataclass(frozen=True, slots=True)
class ClientDebugSettings:
    enabled: bool
    max_events_per_request: int = 50
    max_events_per_capture: int = 10_000
    max_bytes_per_capture: int = 1 * 1024 * 1024
    max_total_bytes: int = 32 * 1024 * 1024
    max_captures: int = 128
    max_captures_per_owner: int = 8
    max_events_per_owner_per_minute: int = 30_000
    ttl_seconds: int = _DEFAULT_TTL_SECONDS

    @classmethod
    def from_environment(cls) -> ClientDebugSettings:
        return cls(
            enabled=_flag(os.getenv("CLIENT_DEBUG_CAPTURE_ENABLED")),
            max_events_per_request=_bounded_int(
                "CLIENT_DEBUG_MAX_EVENTS_PER_REQUEST",
                50,
                minimum=1,
                maximum=50,
            ),
            max_events_per_capture=_bounded_int(
                "CLIENT_DEBUG_MAX_EVENTS_PER_CAPTURE",
                10_000,
                minimum=1,
                maximum=100_000,
            ),
            max_bytes_per_capture=_bounded_int(
                "CLIENT_DEBUG_MAX_BYTES_PER_CAPTURE",
                1 * 1024 * 1024,
                minimum=64 * 1024,
                maximum=16 * 1024 * 1024,
            ),
            max_total_bytes=_bounded_int(
                "CLIENT_DEBUG_MAX_TOTAL_BYTES",
                32 * 1024 * 1024,
                minimum=1 * 1024 * 1024,
                maximum=256 * 1024 * 1024,
            ),
            max_captures=_bounded_int(
                "CLIENT_DEBUG_MAX_CAPTURES",
                128,
                minimum=1,
                maximum=1024,
            ),
            max_captures_per_owner=_bounded_int(
                "CLIENT_DEBUG_MAX_CAPTURES_PER_OWNER",
                8,
                minimum=1,
                maximum=128,
            ),
            max_events_per_owner_per_minute=_bounded_int(
                "CLIENT_DEBUG_MAX_EVENTS_PER_OWNER_PER_MINUTE",
                30_000,
                minimum=1_000,
                maximum=1_000_000,
            ),
            ttl_seconds=_bounded_int(
                "CLIENT_DEBUG_CAPTURE_TTL_SECONDS",
                _DEFAULT_TTL_SECONDS,
                minimum=60,
                maximum=_MAX_TTL_SECONDS,
            ),
        )
