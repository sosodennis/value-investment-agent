from __future__ import annotations

from hashlib import sha256
from uuid import uuid4

import pytest
from src.llm_provider_service.domain.provider_models import ProviderKeyHealth
from src.llm_provider_service.domain.reliability import (
    FailureCategory,
    FailureScope,
    UpstreamFailure,
)
from src.llm_provider_service.infrastructure import key_telemetry

ORG_HASH = sha256(b"org-a").hexdigest()[:32]


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

    async def ping(self) -> bool:
        return True

    async def eval(self, script: str, num_keys: int, key: str, *args: str) -> int:
        assert num_keys == 1
        row = self._rows.setdefault(key, {})
        if "version ~= tonumber(ARGV[1])" in script:
            expected_version = int(args[0])
            version = int(row.get("event_version", "0"))
            if version != expected_version:
                return 0
            row.update(
                status="available",
                failure_count="0",
                cooldown_until="",
                last_error="",
                last_used_at=args[1],
                event_version=str(version + 1),
            )
            return 1
        if "local count =" in script:
            status, cooldown, error, timestamp, _expiry = args
            version = int(row.get("event_version", "0")) + 1
            row.update(
                failure_count=str(int(row.get("failure_count", "0")) + 1),
                last_error=error,
                last_used_at=timestamp,
                event_version=str(version),
            )
            if status:
                row.update(status=status, cooldown_until=cooldown)
            else:
                row.setdefault("status", "available")
            return int(row["failure_count"])
        _timestamp, _expiry = args
        row.setdefault("status", "available")
        row["last_used_at"] = _timestamp
        return int(row.get("event_version", "0"))

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
        f"via:llm-provider:key-health:{ORG_HASH}:{expired_id}": {
            "status": "cooldown",
            "cooldown_until": "2000-01-01T00:00:00+00:00",
            "failure_count": "-4",
            "last_error": "sk-upstream-secret",
        },
        f"via:llm-provider:key-health:{ORG_HASH}:{active_id}": {
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
        health = await telemetry.get_many(
            [expired_id, active_id, "not-a-uuid"], organization_id="org-a"
        )
        await telemetry.delete(expired_id, organization_id="org-a")
        await telemetry.delete("not-a-uuid", organization_id="org-a")
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
        f"via:llm-provider:key-health:{ORG_HASH}:{expired_id}",
        f"via:llm-provider:key-health:{ORG_HASH}:{active_id}",
    ]
    assert redis.deleted == [f"via:llm-provider:key-health:{ORG_HASH}:{expired_id}"]


def _key_failure() -> UpstreamFailure:
    return UpstreamFailure(
        category=FailureCategory.RATE_LIMIT,
        scope=FailureScope.KEY,
        retryable=True,
        retry_after_seconds=0,
        deployment_id="deployment-a",
        http_status=429,
        reason="LLM provider request failed",
    )


@pytest.mark.asyncio
async def test_late_success_does_not_clear_a_newer_key_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key_id = str(uuid4())
    redis = _Redis({})
    monkeypatch.setattr(key_telemetry, "Redis", lambda **kwargs: redis)
    telemetry = key_telemetry.RedisProviderKeyTelemetry()
    try:
        request_version = await telemetry.record_use(key_id, organization_id="org-a")
        await telemetry.record_failure(
            key_id, _key_failure(), organization_id="org-a", cooldown_seconds=30
        )
        assert (
            await telemetry.record_success(
                key_id, organization_id="org-a", expected_version=request_version
            )
            is False
        )
        health = await telemetry.get_many_strict([key_id], organization_id="org-a")
    finally:
        await telemetry.close()

    assert health[key_id].status == "cooldown"
    assert health[key_id].failure_count == 1
    assert health[key_id].last_error == "rate_limited"
    assert health[key_id].cooldown_until is not None


@pytest.mark.asyncio
async def test_global_rate_limit_records_failure_without_disabling_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key_id = str(uuid4())
    redis = _Redis({})
    monkeypatch.setattr(key_telemetry, "Redis", lambda **kwargs: redis)
    telemetry = key_telemetry.RedisProviderKeyTelemetry()
    failure = UpstreamFailure(
        category=FailureCategory.RATE_LIMIT,
        scope=FailureScope.UNKNOWN,
        retryable=True,
        retry_after_seconds=5,
        deployment_id="deployment-a",
        http_status=429,
        reason="LLM provider request failed",
    )
    try:
        await telemetry.record_use(key_id, organization_id="org-a")
        await telemetry.record_failure(
            key_id, failure, organization_id="org-a", cooldown_seconds=30
        )
        health = await telemetry.get_many_strict([key_id], organization_id="org-a")
    finally:
        await telemetry.close()

    assert health[key_id].status == "available"
    assert health[key_id].failure_count == 1
    assert health[key_id].cooldown_until is None
    assert health[key_id].last_error == "global_rate_limited"


@pytest.mark.asyncio
async def test_manual_success_clears_an_invalid_key_health_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key_id = str(uuid4())
    redis = _Redis(
        {
            f"via:llm-provider:key-health:{ORG_HASH}:{key_id}": {
                "status": "invalid_key",
                "failure_count": "2",
                "last_error": "invalid_key",
                "event_version": "5",
            }
        }
    )
    monkeypatch.setattr(key_telemetry, "Redis", lambda **kwargs: redis)
    telemetry = key_telemetry.RedisProviderKeyTelemetry()
    try:
        request_version = await telemetry.record_use(key_id, organization_id="org-a")
        assert request_version == 5
        assert await telemetry.record_success(
            key_id, organization_id="org-a", expected_version=request_version
        )
        health = await telemetry.get_many_strict([key_id], organization_id="org-a")
    finally:
        await telemetry.close()

    assert health[key_id].status == "available"
    assert health[key_id].failure_count == 0
    assert health[key_id].last_error is None
