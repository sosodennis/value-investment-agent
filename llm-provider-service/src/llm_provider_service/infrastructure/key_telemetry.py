from __future__ import annotations

import logging
import os
from collections.abc import Collection
from datetime import UTC, datetime, timedelta
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError

from src.llm_provider_service.domain.provider_models import ProviderKeyHealth
from src.llm_provider_service.domain.reliability import UpstreamFailure

_logger = logging.getLogger(__name__)
_KEY_PREFIX = "via:llm-provider:key-health:"
_SAFE_STATUSES = frozenset(
    {"healthy", "available", "cooldown", "invalid_key", "unavailable"}
)
_SAFE_ERRORS = frozenset(
    {
        "invalid_key",
        "rate_limited",
        "global_rate_limited",
        "unavailable",
        "upstream_timeout",
        "credit_limit",
    }
)


def _cooldown_expired(value: str | None, now: datetime) -> bool:
    if not value:
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed <= now


def _redis_key(key_id: str) -> str | None:
    try:
        normalized = str(UUID(key_id))
    except (ValueError, AttributeError):
        return None
    return f"{_KEY_PREFIX}{normalized}"


class RedisProviderKeyTelemetry:
    def __init__(self) -> None:
        self._client = Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            password=os.getenv("REDIS_PASSWORD") or None,
            decode_responses=True,
            socket_connect_timeout=0.2,
            socket_timeout=0.2,
        )

    async def ping(self) -> bool:
        return bool(await self._client.ping())

    async def get_many(self, key_ids: Collection[str]) -> dict[str, ProviderKeyHealth]:
        keys = [(key_id, _redis_key(key_id)) for key_id in key_ids]
        valid = [(key_id, key) for key_id, key in keys if key is not None]
        if not valid:
            return {}
        pipeline = self._client.pipeline(transaction=False)
        for _, key in valid:
            pipeline.hgetall(key)
        try:
            rows = await pipeline.execute()
        except RedisError:
            _logger.warning("LLM key health could not be read from Redis")
            return {
                key_id: ProviderKeyHealth(
                    status="unavailable",
                    failure_count=0,
                    cooldown_until=None,
                    last_error="unavailable",
                    last_used_at=None,
                )
                for key_id, _ in valid
            }

        health: dict[str, ProviderKeyHealth] = {}
        now = datetime.now(UTC)
        for (key_id, _), row in zip(valid, rows, strict=True):
            if not isinstance(row, dict):
                continue
            status = row.get("status")
            if status not in _SAFE_STATUSES:
                continue
            cooldown_until = row.get("cooldown_until") or None
            if status == "cooldown" and _cooldown_expired(cooldown_until, now):
                status = "available"
                cooldown_until = None
            try:
                failure_count = max(0, int(row.get("failure_count", "0")))
            except (TypeError, ValueError):
                failure_count = 0
            last_error = row.get("last_error")
            health[key_id] = ProviderKeyHealth(
                status=status,
                failure_count=failure_count,
                cooldown_until=cooldown_until,
                last_error=last_error if last_error in _SAFE_ERRORS else None,
                last_used_at=row.get("last_used_at") or None,
            )
        return health

    async def get_many_strict(
        self, key_ids: Collection[str]
    ) -> dict[str, ProviderKeyHealth]:
        """Read runtime health and propagate Redis failures to data-plane callers."""
        keys = [(key_id, _redis_key(key_id)) for key_id in key_ids]
        valid = [(key_id, key) for key_id, key in keys if key is not None]
        if not valid:
            return {}
        pipeline = self._client.pipeline(transaction=False)
        for _, key in valid:
            pipeline.hgetall(key)
        rows = await pipeline.execute()
        health: dict[str, ProviderKeyHealth] = {}
        now = datetime.now(UTC)
        for (key_id, _), row in zip(valid, rows, strict=True):
            if not isinstance(row, dict) or row.get("status") not in _SAFE_STATUSES:
                continue
            cooldown_until = row.get("cooldown_until") or None
            status = row.get("status")
            if status == "cooldown" and _cooldown_expired(cooldown_until, now):
                status, cooldown_until = "available", None
            try:
                failures = max(0, int(row.get("failure_count", "0")))
            except (TypeError, ValueError):
                failures = 0
            health[key_id] = ProviderKeyHealth(
                status=status,
                failure_count=failures,
                cooldown_until=cooldown_until,
                last_error=row.get("last_error")
                if row.get("last_error") in _SAFE_ERRORS
                else None,
                last_used_at=row.get("last_used_at") or None,
            )
        return health

    async def record_use(self, key_id: str, *, at: datetime | None = None) -> int:
        key = _redis_key(key_id)
        if key is None:
            return 0
        timestamp = (at or datetime.now(UTC)).isoformat()
        script = """
        redis.call('HSETNX', KEYS[1], 'status', 'available')
        redis.call('HSET', KEYS[1], 'last_used_at', ARGV[1])
        redis.call('EXPIRE', KEYS[1], ARGV[2])
        return tonumber(redis.call('HGET', KEYS[1], 'event_version') or '0')
        """
        version = await self._client.eval(
            script, 1, key, timestamp, str(90 * 24 * 60 * 60)
        )
        return max(0, int(version))

    async def record_success(
        self,
        key_id: str,
        *,
        expected_version: int | None,
        at: datetime | None = None,
    ) -> bool:
        key = _redis_key(key_id)
        if key is None or expected_version is None:
            return False
        timestamp = (at or datetime.now(UTC)).isoformat()
        script = """
        local version = tonumber(redis.call('HGET', KEYS[1], 'event_version') or '0')
        if version ~= tonumber(ARGV[1]) then
          return 0
        end
        redis.call('HSET', KEYS[1], 'status', 'available', 'failure_count', '0',
          'cooldown_until', '', 'last_error', '', 'last_used_at', ARGV[2],
          'event_version', version + 1)
        redis.call('EXPIRE', KEYS[1], ARGV[3])
        return 1
        """
        updated = await self._client.eval(
            script,
            1,
            key,
            str(expected_version),
            timestamp,
            str(90 * 24 * 60 * 60),
        )
        return bool(updated)

    async def record_failure(
        self,
        key_id: str,
        failure: UpstreamFailure,
        *,
        cooldown_seconds: float,
        at: datetime | None = None,
    ) -> None:
        key = _redis_key(key_id)
        if key is None:
            return
        now = at or datetime.now(UTC)
        status = None
        if failure.category.value == "authentication" and failure.scope.value == "key":
            status = "invalid_key"
        elif failure.rotates_key:
            status = "cooldown"
        cooldown = (
            now + timedelta(seconds=max(0.0, cooldown_seconds))
            if status == "cooldown"
            else None
        )
        safe_error = (
            "invalid_key"
            if status == "invalid_key"
            else "upstream_timeout"
            if failure.category.value == "timeout"
            else "rate_limited"
            if failure.rotates_key
            else "credit_limit"
            if failure.category.value == "credit"
            else "global_rate_limited"
            if failure.category.value == "rate_limit"
            else "unavailable"
        )
        cooldown_value = cooldown.isoformat() if cooldown else ""
        script = """
        local count = tonumber(redis.call('HGET', KEYS[1], 'failure_count') or '0') + 1
        local version = tonumber(redis.call('HGET', KEYS[1], 'event_version') or '0') + 1
        redis.call('HSET', KEYS[1], 'failure_count', count, 'last_error', ARGV[3],
          'last_used_at', ARGV[4], 'event_version', version)
        if ARGV[1] ~= '' then
          redis.call('HSET', KEYS[1], 'status', ARGV[1], 'cooldown_until', ARGV[2])
        else
          redis.call('HSETNX', KEYS[1], 'status', 'available')
        end
        redis.call('EXPIRE', KEYS[1], ARGV[5])
        return count
        """
        await self._client.eval(
            script,
            1,
            key,
            status or "",
            cooldown_value,
            safe_error,
            now.isoformat(),
            str(90 * 24 * 60 * 60),
        )

    async def delete(self, key_id: str) -> None:
        key = _redis_key(key_id)
        if key is None:
            return
        try:
            await self._client.delete(key)
        except RedisError:
            _logger.warning("LLM key health could not be removed from Redis")

    async def close(self) -> None:
        await self._client.aclose()
