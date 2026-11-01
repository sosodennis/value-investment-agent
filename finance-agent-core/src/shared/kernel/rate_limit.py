from __future__ import annotations

import asyncio
import os
import time
from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import Protocol


class RateLimitExceeded(RuntimeError):
    def __init__(self, message: str, *, retry_after_seconds: int = 1) -> None:
        self.retry_after_seconds = max(1, retry_after_seconds)
        super().__init__(message)


class RateLimiterUnavailable(RuntimeError):
    """The shared limiter could not make a safe decision."""


class _RedisClient(Protocol):
    async def eval(
        self, script: str, numkeys: int, *keys_and_args: object
    ) -> object: ...

    async def aclose(self) -> None: ...


class RateLimiter(Protocol):
    async def check(
        self, *, key: str, limit: int, window_seconds: int, cost: int = 1
    ) -> None: ...

    async def aclose(self) -> None: ...


@dataclass(frozen=True, slots=True)
class RateLimitSettings:
    directory_per_user_minute: int = 30
    invitations_per_actor_hour: int = 10
    invitations_per_organization_hour: int = 50
    invitations_per_recipient_hour: int = 10
    resend_per_invitation_hour: int = 3
    role_changes_per_actor_hour: int = 30
    role_changes_per_organization_hour: int = 100
    membership_changes_per_actor_hour: int = 30
    owner_transfers_per_actor_hour: int = 10
    invitation_responses_per_recipient_hour: int = 20
    notification_fanout_per_organization_minute: int = 100
    notification_fanout_system_minute: int = 1_000
    retention_days: int = 90
    expired_notification_retention_days: int = 30


def _positive_int(name: str, default: int, maximum: int) -> int:
    raw_value = os.getenv(name)
    try:
        value = default if raw_value is None else int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if not 1 <= value <= maximum:
        raise RuntimeError(f"{name} must be between 1 and {maximum}")
    return value


def _load_rate_limit_settings() -> RateLimitSettings:
    defaults = RateLimitSettings()
    bounds = {
        "directory_per_user_minute": (
            "ORG_DIRECTORY_SEARCH_PER_USER_PER_MINUTE",
            1_000,
        ),
        "invitations_per_actor_hour": ("ORG_INVITATIONS_PER_ACTOR_PER_HOUR", 1_000),
        "invitations_per_organization_hour": (
            "ORG_INVITATIONS_PER_ORGANIZATION_PER_HOUR",
            10_000,
        ),
        "invitations_per_recipient_hour": (
            "ORG_INVITATIONS_PER_RECIPIENT_PER_HOUR",
            100,
        ),
        "resend_per_invitation_hour": (
            "ORG_INVITATION_RESENDS_PER_INVITATION_PER_HOUR",
            100,
        ),
        "role_changes_per_actor_hour": ("ORG_ROLE_CHANGES_PER_ACTOR_PER_HOUR", 1_000),
        "role_changes_per_organization_hour": (
            "ORG_ROLE_CHANGES_PER_ORGANIZATION_PER_HOUR",
            10_000,
        ),
        "membership_changes_per_actor_hour": (
            "ORG_MEMBERSHIP_CHANGES_PER_ACTOR_PER_HOUR",
            1_000,
        ),
        "owner_transfers_per_actor_hour": (
            "ORG_OWNER_TRANSFERS_PER_ACTOR_PER_HOUR",
            100,
        ),
        "invitation_responses_per_recipient_hour": (
            "ORG_INVITATION_RESPONSES_PER_RECIPIENT_PER_HOUR",
            1_000,
        ),
        "notification_fanout_per_organization_minute": (
            "ORG_NOTIFICATION_FANOUT_PER_ORGANIZATION_PER_MINUTE",
            10_000,
        ),
        "notification_fanout_system_minute": (
            "ORG_NOTIFICATION_FANOUT_SYSTEM_PER_MINUTE",
            100_000,
        ),
        "retention_days": ("ORG_NOTIFICATION_RETENTION_DAYS", 3_650),
        "expired_notification_retention_days": (
            "ORG_EXPIRED_NOTIFICATION_RETENTION_DAYS",
            365,
        ),
    }
    return RateLimitSettings(
        **{
            field: _positive_int(name, getattr(defaults, field), maximum)
            for field, (name, maximum) in bounds.items()
        }
    )


rate_limit_settings = _load_rate_limit_settings()


class InMemoryRateLimiter:
    """Bounded local limiter for development and tests without Redis."""

    def __init__(self, *, max_keys: int = 10_000) -> None:
        self._events: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = asyncio.Lock()
        self._max_keys = max_keys

    async def check(
        self, *, key: str, limit: int, window_seconds: int, cost: int = 1
    ) -> None:
        if limit < 1 or window_seconds < 1:
            raise ValueError("rate limiter bounds must be positive")
        if not 1 <= cost <= limit:
            raise RateLimitExceeded(
                "request exceeds the maximum rate limit cost",
                retry_after_seconds=window_seconds,
            )
        now = time.monotonic()
        cutoff = now - window_seconds
        async with self._lock:
            events = self._events.pop(key, deque())
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) + cost > limit:
                retry_after = max(1, int(events[0] - cutoff + 0.999))
                self._events[key] = events
                raise RateLimitExceeded(
                    "too many attempts; try again later",
                    retry_after_seconds=min(window_seconds, retry_after),
                )
            events.extend([now] * cost)
            self._events[key] = events
            while len(self._events) > self._max_keys:
                self._events.popitem(last=False)

    async def aclose(self) -> None:
        return None


@dataclass(frozen=True, slots=True)
class RedisRateLimiter:
    """Atomic fixed-window limiter shared by every API worker."""

    client: _RedisClient
    prefix: str = "value-investment-agent:rate-limit"

    async def check(
        self, *, key: str, limit: int, window_seconds: int, cost: int = 1
    ) -> None:
        if limit < 1 or window_seconds < 1:
            raise ValueError("rate limiter bounds must be positive")
        if not 1 <= cost <= limit:
            raise RateLimitExceeded(
                "request exceeds the maximum rate limit cost",
                retry_after_seconds=window_seconds,
            )
        script = (
            "local current = tonumber(redis.call('GET', KEYS[1]) or '0'); "
            "if current + tonumber(ARGV[2]) > tonumber(ARGV[3]) then "
            "return {0, redis.call('TTL', KEYS[1])}; end; "
            "current = redis.call('INCRBY', KEYS[1], ARGV[2]); "
            "if current == tonumber(ARGV[2]) then "
            "redis.call('EXPIRE', KEYS[1], ARGV[1]); end; "
            "return {1, redis.call('TTL', KEYS[1])}"
        )
        redis_key = f"{self.prefix}:{key}"
        try:
            result = await self.client.eval(
                script, 1, redis_key, window_seconds, cost, limit
            )
            if not isinstance(result, list) or len(result) != 2:
                raise ValueError("unexpected rate limiter response")
            allowed, ttl = int(result[0]), max(1, int(result[1]))
        except Exception as exc:
            raise RateLimiterUnavailable("shared rate limiter is unavailable") from exc
        if allowed != 1:
            raise RateLimitExceeded(
                "too many attempts; try again later",
                retry_after_seconds=min(window_seconds, ttl),
            )

    async def aclose(self) -> None:
        await self.client.aclose()


def _redis_url() -> str | None:
    configured = os.getenv("REDIS_URL", "").strip()
    if configured:
        return configured
    host = os.getenv("REDIS_HOST", "").strip()
    if not host:
        return None
    port = os.getenv("REDIS_PORT", "6379").strip()
    password = os.getenv("REDIS_PASSWORD", "").strip()
    auth = f":{password}@" if password else ""
    return f"redis://{auth}{host}:{port}/0"


def _build_rate_limiter() -> RateLimiter:
    url = _redis_url()
    if not url:
        environment = (
            os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "development"))
            .strip()
            .lower()
        )
        if environment in {"production", "prod", "staging"}:
            raise RuntimeError(
                "REDIS_URL or REDIS_HOST is required outside development and test"
            )
        return InMemoryRateLimiter()
    try:
        from redis.asyncio import Redis

        return RedisRateLimiter(Redis.from_url(url, decode_responses=False))
    except Exception as exc:
        raise RuntimeError("shared rate limiter configuration is invalid") from exc


rate_limiter = _build_rate_limiter()


async def close_rate_limiter() -> None:
    await rate_limiter.aclose()


__all__ = [
    "InMemoryRateLimiter",
    "RateLimitSettings",
    "RateLimiterUnavailable",
    "RateLimitExceeded",
    "RedisRateLimiter",
    "close_rate_limiter",
    "rate_limit_settings",
    "rate_limiter",
]
