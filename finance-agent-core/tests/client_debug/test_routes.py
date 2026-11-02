from __future__ import annotations

from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from src.auth.interface.contracts import Principal
from src.client_debug.application.service import ClientDebugService
from src.client_debug.application.wiring import get_client_debug_service
from src.client_debug.config import ClientDebugSettings
from src.client_debug.infrastructure.runtime_buffer import ClientDebugBuffer
from src.client_debug.interface.dependencies import (
    current_client_debug_mutation,
    current_client_debug_user,
)
from src.client_debug.interface.routes import router
from src.shared.kernel.correlation import reset_correlation_id, set_correlation_id


def _principal(user_id: str = "user-1", organization_id: str = "org-1") -> Principal:
    return Principal(
        user_id=user_id,
        subject=user_id,
        email=f"{user_id}@example.test",
        organization_id=organization_id,
        membership_id="membership-1",
    )


def _payload(capture_id: str) -> dict[str, object]:
    return {
        "schema_version": "client_debug.v1",
        "capture_id": capture_id,
        "events": [
            {
                "event_id": str(uuid4()),
                "sequence": 1,
                "occurred_at": "2026-11-02T00:00:00Z",
                "elapsed_ms": 12.5,
                "name": "ui.layout",
                "context": {
                    "route": "/workspace",
                    "viewport": {"width": 1200, "height": 800, "dpr": 2},
                },
                "details": {
                    "rect": {"width": 300, "height": 100},
                    "access_token": "never-store-this",
                },
            }
        ],
    }


@pytest.mark.asyncio
async def test_client_debug_routes_ingest_and_read_runtime_events() -> None:
    settings = ClientDebugSettings(enabled=True)
    service = ClientDebugService(
        buffer=ClientDebugBuffer(settings=settings),
        settings=settings,
    )
    principal = _principal()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_client_debug_service] = lambda: service
    app.dependency_overrides[current_client_debug_mutation] = lambda: principal
    app.dependency_overrides[current_client_debug_user] = lambda: principal

    capture_id = str(uuid4())
    token = set_correlation_id("server-request-1")
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            ingested = await client.post(
                "/api/v1/client-debug/events", json=_payload(capture_id)
            )
            listed = await client.get(f"/api/v1/client-debug/captures/{capture_id}")
    finally:
        reset_correlation_id(token)

    assert ingested.status_code == 202
    assert ingested.json()["accepted"] == 1
    assert ingested.json()["dropped_rate_limited"] == 0
    assert ingested.json()["dropped_capacity"] == 0
    assert ingested.json()["request_id"] == "server-request-1"
    assert listed.status_code == 200
    assert listed.json()["events"][0]["details"]["access_token"] == "[REDACTED]"


@pytest.mark.asyncio
async def test_client_debug_routes_hide_foreign_captures() -> None:
    settings = ClientDebugSettings(enabled=True)
    service = ClientDebugService(
        buffer=ClientDebugBuffer(settings=settings),
        settings=settings,
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_client_debug_service] = lambda: service
    owner = _principal()
    foreign = _principal(user_id="user-2")
    app.dependency_overrides[current_client_debug_mutation] = lambda: owner
    app.dependency_overrides[current_client_debug_user] = lambda: foreign
    capture_id = str(uuid4())

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/v1/client-debug/events", json=_payload(capture_id)
        )
        foreign_read = await client.get(f"/api/v1/client-debug/captures/{capture_id}")

    assert response.status_code == 202
    assert foreign_read.status_code == 404

    app.dependency_overrides[current_client_debug_mutation] = lambda: foreign
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        foreign_write = await client.post(
            "/api/v1/client-debug/events", json=_payload(capture_id)
        )

    assert foreign_write.status_code == 404
    assert foreign_write.json()["detail"] == "client_debug_capture_not_found"


@pytest.mark.asyncio
async def test_client_debug_rejects_unsafe_details() -> None:
    settings = ClientDebugSettings(enabled=True)
    service = ClientDebugService(
        buffer=ClientDebugBuffer(settings=settings),
        settings=settings,
    )
    principal = _principal()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_client_debug_service] = lambda: service
    app.dependency_overrides[current_client_debug_mutation] = lambda: principal
    app.dependency_overrides[current_client_debug_user] = lambda: principal
    payload = _payload(str(uuid4()))
    payload["events"][0]["details"] = {"outerHTML": "<div>secret</div>"}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post("/api/v1/client-debug/events", json=payload)

    assert response.status_code == 422

    payload = _payload(str(uuid4()))
    payload["events"][0]["context"]["traceparent"] = "invalid"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post("/api/v1/client-debug/events", json=payload)

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_client_debug_redacts_sensitive_values_under_generic_keys() -> None:
    settings = ClientDebugSettings(enabled=True)
    service = ClientDebugService(
        buffer=ClientDebugBuffer(settings=settings),
        settings=settings,
    )
    principal = _principal()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_client_debug_service] = lambda: service
    app.dependency_overrides[current_client_debug_mutation] = lambda: principal
    app.dependency_overrides[current_client_debug_user] = lambda: principal

    for unsafe_value in (
        "https://example.test/path?email=private@example.test",
        "?sessionId=private-session-123456",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.signaturevalue123",
    ):
        payload = _payload(str(uuid4()))
        payload["events"][0]["details"] = {"metadata": unsafe_value}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post("/api/v1/client-debug/events", json=payload)
            capture = await client.get(
                "/api/v1/client-debug/captures/" + payload["capture_id"]
            )

        assert response.status_code == 202
        assert capture.json()["events"][0]["details"]["metadata"] == "[REDACTED]"

    payload = _payload(str(uuid4()))
    payload["events"][0]["details"] = {"href": "https://example.test/?token=secret"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post("/api/v1/client-debug/events", json=payload)

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_client_debug_returns_429_when_capture_buffer_is_full() -> None:
    settings = ClientDebugSettings(enabled=True, max_captures=1)
    service = ClientDebugService(
        buffer=ClientDebugBuffer(settings=settings),
        settings=settings,
    )
    principal = _principal()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_client_debug_service] = lambda: service
    app.dependency_overrides[current_client_debug_mutation] = lambda: principal
    app.dependency_overrides[current_client_debug_user] = lambda: principal

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        first = await client.post(
            "/api/v1/client-debug/events", json=_payload(str(uuid4()))
        )
        second = await client.post(
            "/api/v1/client-debug/events", json=_payload(str(uuid4()))
        )

    assert first.status_code == 202
    assert second.status_code == 429
    assert second.json()["detail"] == "client_debug_buffer_full"
