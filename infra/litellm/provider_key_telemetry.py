"""Capture sanitized per-deployment outcomes from ordinary LiteLLM requests."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from uuid import UUID

from litellm.integrations.custom_logger import CustomLogger
from redis.asyncio import Redis

_logger = logging.getLogger(__name__)
_KEY_PREFIX = "via:llm-provider:key-health:"
_RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})
_HASH_TTL_SECONDS = 90 * 24 * 60 * 60
_RECORD_EVENT = """
if ARGV[1] == 'success' then
  redis.call('HSET', KEYS[1],
    'status', 'healthy',
    'failure_count', '0',
    'last_used_at', ARGV[2],
    'last_success_at', ARGV[2])
  redis.call('HDEL', KEYS[1], 'cooldown_until', 'last_error')
else
  local failure_count = redis.call('HINCRBY', KEYS[1], 'failure_count', 1)
  redis.call('HSET', KEYS[1],
    'status', ARGV[3],
    'failure_count', failure_count,
    'last_used_at', ARGV[2],
    'last_failure_at', ARGV[2],
    'last_error', ARGV[4])
  if ARGV[5] ~= '' then
    redis.call('HSET', KEYS[1], 'cooldown_until', ARGV[5])
  else
    redis.call('HDEL', KEYS[1], 'cooldown_until')
  end
end
redis.call('EXPIRE', KEYS[1], ARGV[6])
return 1
"""


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _deployment_id(kwargs: Mapping[str, object]) -> str | None:
    params = _mapping(kwargs.get("litellm_params"))
    metadata = _mapping(params.get("metadata"))
    for source in (params, metadata):
        model_info = _mapping(source.get("model_info"))
        model_id = model_info.get("id")
        if isinstance(model_id, str):
            try:
                return str(UUID(model_id))
            except ValueError:
                continue
    return None


def _cooldown_seconds() -> int:
    try:
        return min(
            3600, max(0, int(os.getenv("LLM_PROVIDER_KEY_COOLDOWN_SECONDS", "30")))
        )
    except ValueError:
        return 30


def _failure_state(kwargs: Mapping[str, object]) -> tuple[str, str, int]:
    exception = kwargs.get("exception")
    status_code = getattr(exception, "status_code", None)
    if status_code in {401, 403}:
        return "invalid_key", "invalid_key", 0
    if status_code == 429:
        return "cooldown", "rate_limited", _cooldown_seconds()
    if status_code in _RETRYABLE_STATUS_CODES:
        return "cooldown", "unavailable", _cooldown_seconds()
    if "timeout" in type(exception).__name__.lower():
        return "cooldown", "unavailable", _cooldown_seconds()
    return "unavailable", "unavailable", 0


class ProviderKeyTelemetryCallback(CustomLogger):
    def __init__(self) -> None:
        super().__init__(turn_off_message_logging=True)
        self._client = Redis(
            host=os.getenv("LITELLM_REDIS_HOST", "redis"),
            port=int(os.getenv("LITELLM_REDIS_PORT", "6379")),
            password=os.getenv("LITELLM_REDIS_PASSWORD") or None,
            decode_responses=True,
            socket_connect_timeout=0.2,
            socket_timeout=0.2,
        )

    async def async_log_success_event(
        self,
        kwargs: Mapping[str, object],
        response_obj: object,
        start_time: object,
        end_time: object,
    ) -> None:
        await self._record(kwargs, success=True)

    async def async_log_stream_event(
        self,
        kwargs: Mapping[str, object],
        response_obj: object,
        start_time: object,
        end_time: object,
    ) -> None:
        await self._record(kwargs, success=True)

    async def async_log_failure_event(
        self,
        kwargs: Mapping[str, object],
        response_obj: object,
        start_time: object,
        end_time: object,
    ) -> None:
        await self._record(kwargs, success=False)

    async def _record(self, kwargs: Mapping[str, object], *, success: bool) -> None:
        deployment_id = _deployment_id(kwargs)
        if deployment_id is None:
            return
        now = datetime.now(UTC)
        if success:
            args = (
                "success",
                now.isoformat(),
                "healthy",
                "",
                "",
                _HASH_TTL_SECONDS,
            )
        else:
            status, error, cooldown_seconds = _failure_state(kwargs)
            cooldown_until = (
                (now + timedelta(seconds=cooldown_seconds)).isoformat()
                if cooldown_seconds
                else ""
            )
            args = (
                "failure",
                now.isoformat(),
                status,
                error,
                cooldown_until,
                _HASH_TTL_SECONDS,
            )
        try:
            await asyncio.wait_for(
                self._client.eval(
                    _RECORD_EVENT,
                    1,
                    f"{_KEY_PREFIX}{deployment_id}",
                    *args,
                ),
                timeout=0.25,
            )
        except Exception:
            _logger.warning("LiteLLM key health event could not be recorded")

    async def aclose(self) -> None:
        await self._client.aclose()


provider_key_telemetry = ProviderKeyTelemetryCallback()
