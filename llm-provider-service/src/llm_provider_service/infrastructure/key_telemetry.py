"""Read per-key request health recorded by the LiteLLM callback."""

from __future__ import annotations

import logging
import os
from collections.abc import Collection
from datetime import UTC, datetime
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError

from src.llm_provider_service.domain.provider_models import ProviderKeyHealth

_logger = logging.getLogger(__name__)
_KEY_PREFIX = "via:llm-provider:key-health:"
_SAFE_STATUSES = frozenset(
    {"healthy", "available", "cooldown", "invalid_key", "unavailable"}
)
_SAFE_ERRORS = frozenset({"invalid_key", "rate_limited", "unavailable"})


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
            return {}

        health: dict[str, ProviderKeyHealth] = {}
        now = datetime.now(UTC)
        for (key_id, _), row in zip(valid, rows, strict=True):
            if not isinstance(row, dict):
                continue
            status = row.get("status")
            if status not in _SAFE_STATUSES:
                continue
            cooldown_until = row.get("cooldown_until") or None
            if status == "cooldown" and cooldown_until is not None:
                try:
                    expired = datetime.fromisoformat(cooldown_until) <= now
                except ValueError:
                    expired = True
                if expired:
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
