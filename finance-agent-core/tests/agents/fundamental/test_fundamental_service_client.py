from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from src.agents.fundamental.application.fundamental_service_port import (
    FundamentalServiceFailure,
)
from src.agents.fundamental.infrastructure.fundamental_service_client import (
    FundamentalServiceClientSettings,
    HttpFundamentalServiceClient,
)
from src.shared.internal_services import InternalPrincipal


def _settings(*, max_attempts: int = 2) -> FundamentalServiceClientSettings:
    return FundamentalServiceClientSettings(
        base_url="https://fundamental.test",
        service_token="fundamental-token",
        timeout_seconds=1.0,
        max_attempts=max_attempts,
    )


def _principal() -> InternalPrincipal:
    return InternalPrincipal(
        subject_id="subject-1",
        organization_id="org-1",
        membership_id="membership-1",
    )


def _success(correlation_id: str) -> dict[str, object]:
    return {
        "contract_version": "internal.v1",
        "schema_version": "fundamental.v1",
        "correlation_id": correlation_id,
        "result": {"input_digest": "a" * 64, "quality_status": "verified"},
    }


@pytest.mark.asyncio
async def test_client_sends_signed_context_and_versioned_envelope() -> None:
    captured: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        body = json.loads(request.content)
        return httpx.Response(200, json=_success(body["context"]["correlation_id"]))

    client = HttpFundamentalServiceClient(
        _settings(), client=httpx.AsyncClient(transport=httpx.MockTransport(respond))
    )
    result = await client.execute(
        "validate",
        {
            "contract_version": "fundamental.v1",
            "assumptions": {"terminal_growth": "0.02"},
        },
        principal=_principal(),
        correlation_id="correlation-1",
        deadline_at=datetime.now(UTC) + timedelta(seconds=5),
    )

    assert result.correlation_id == "correlation-1"
    request = captured[0]
    assert request.url.path == "/v1/valuation/validate"
    assert request.headers["authorization"] == "Bearer fundamental-token"
    assert request.headers["x-request-id"] == "correlation-1"
    assert request.headers["x-organization-id"] == "org-1"
    body = json.loads(request.content)
    assert set(body) == {"context", "input"}
    assert body["context"]["contract_version"] == "internal.v1"
    assert body["context"]["audience"] == "fundamental-service"
    assert body["context"]["issuer"] == "finance-agent-core"
    assert body["context"]["signature"]
    assert body["input"]["assumptions"] == {"terminal_growth": "0.02"}
    await client.aclose()


@pytest.mark.asyncio
async def test_client_retries_retryable_service_error_before_deadline() -> None:
    attempts = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        body = json.loads(request.content)
        if attempts == 1:
            return httpx.Response(
                503,
                json={
                    "contract_version": "internal.v1",
                    "correlation_id": body["context"]["correlation_id"],
                    "error": {
                        "code": "source_unavailable",
                        "message": "retry",
                        "retryable": True,
                    },
                },
            )
        return httpx.Response(200, json=_success(body["context"]["correlation_id"]))

    client = HttpFundamentalServiceClient(
        _settings(), client=httpx.AsyncClient(transport=httpx.MockTransport(respond))
    )
    result = await client.execute(
        "calculate",
        {},
        principal=_principal(),
        correlation_id="correlation-2",
        deadline_at=datetime.now(UTC) + timedelta(seconds=5),
    )

    assert result.result["quality_status"] == "verified"
    assert attempts == 2
    await client.aclose()


@pytest.mark.asyncio
async def test_client_rejects_malformed_response_and_expired_deadline() -> None:
    malformed = HttpFundamentalServiceClient(
        FundamentalServiceClientSettings(
            base_url="https://fundamental.test",
            service_token="fundamental-token",
            max_attempts=1,
        ),
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(200, json={"result": {}})
            )
        ),
    )
    with pytest.raises(FundamentalServiceFailure) as malformed_error:
        await malformed.execute(
            "calculate",
            {},
            principal=_principal(),
            correlation_id="correlation-3",
            deadline_at=datetime.now(UTC) + timedelta(seconds=5),
        )
    assert malformed_error.value.code == "UPSTREAM_MALFORMED"
    await malformed.aclose()

    expired = HttpFundamentalServiceClient(_settings(max_attempts=1))
    with pytest.raises(FundamentalServiceFailure) as deadline_error:
        await expired.execute(
            "calculate",
            {},
            principal=_principal(),
            correlation_id="correlation-4",
            deadline_at=datetime.now(UTC) - timedelta(seconds=1),
        )
    assert deadline_error.value.code == "DEADLINE_EXCEEDED"
    await expired.aclose()
