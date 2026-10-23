from __future__ import annotations

from uuid import uuid4

import pytest
from src.llm_provider_service.domain.provider_models import ProviderKeyHealth
from src.llm_provider_service.infrastructure import key_telemetry


class _Pipeline:
    def __init__(self, rows: dict[str, dict[str, str]]) -> None:
        self._rows = rows
        self.keys: list[str] = []

    def hgetall(self, key: str) -> _Pipeline:
        self.keys.append(key)
        return self

    async def execute(self) -> list[dict[str, str]]:
        return [self._rows.get(key, {}) for key in self.keys]


class _Redis:
    def __init__(self, rows: dict[str, dict[str, str]]) -> None:
        self._rows = rows
        self._pipeline: _Pipeline | None = None
        self.deleted: list[str] = []

    def pipeline(self, *, transaction: bool) -> _Pipeline:
        assert transaction is False
        self._pipeline = _Pipeline(self._rows)
        return self._pipeline

    async def delete(self, key: str) -> None:
        self.deleted.append(key)

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_key_health_cooldown_expiry_and_error_values_are_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expired_id = str(uuid4())
    active_id = str(uuid4())
    rows = {
        f"via:llm-provider:key-health:{expired_id}": {
            "status": "cooldown",
            "cooldown_until": "2000-01-01T00:00:00+00:00",
            "failure_count": "-4",
            "last_error": "sk-upstream-secret",
        },
        f"via:llm-provider:key-health:{active_id}": {
            "status": "cooldown",
            "cooldown_until": "2999-01-01T00:00:00+00:00",
            "failure_count": "3",
            "last_error": "rate_limited",
            "last_used_at": "2026-10-22T12:00:00+00:00",
        },
    }
    redis = _Redis(rows)
    monkeypatch.setattr(key_telemetry, "Redis", lambda **kwargs: redis)
    telemetry = key_telemetry.RedisProviderKeyTelemetry()

    try:
        health = await telemetry.get_many([expired_id, active_id, "not-a-uuid"])
        await telemetry.delete(expired_id)
        await telemetry.delete("not-a-uuid")
    finally:
        await telemetry.close()

    assert health == {
        expired_id: ProviderKeyHealth(
            status="available",
            failure_count=0,
            cooldown_until=None,
            last_error=None,
            last_used_at=None,
        ),
        active_id: ProviderKeyHealth(
            status="cooldown",
            failure_count=3,
            cooldown_until="2999-01-01T00:00:00+00:00",
            last_error="rate_limited",
            last_used_at="2026-10-22T12:00:00+00:00",
        ),
    }
    assert redis._pipeline is not None
    assert redis._pipeline.keys == [
        f"via:llm-provider:key-health:{expired_id}",
        f"via:llm-provider:key-health:{active_id}",
    ]
    assert redis.deleted == [f"via:llm-provider:key-health:{expired_id}"]
