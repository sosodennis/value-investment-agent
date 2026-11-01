from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from src.audit.application.recording import record_best_effort
from src.audit.domain.entities import AuditOutcome
from src.audit.interface.middleware import CorrelationIdMiddleware
from src.shared.kernel.correlation import normalize_correlation_id


class _AuditService:
    def __init__(self) -> None:
        self.events = []

    async def append(self, *, event):
        self.events.append(event)


def test_correlation_normalization_rejects_header_control_characters() -> None:
    normalized = normalize_correlation_id("trace-210\r\nX-Evil: value")

    assert normalized != "trace-210\r\nX-Evil: value"
    assert all(0x21 <= ord(character) <= 0x7E for character in normalized)


def _app(service: _AuditService) -> FastAPI:
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)

    @app.get("/audit")
    async def audit() -> dict[str, str]:
        await record_best_effort(
            organization_id="organization-1",
            actor_system="test",
            action="test.request.correlated",
            outcome=AuditOutcome.SUCCESS,
        )
        return {"status": "ok"}

    app.state.audit_service = service
    return app


@pytest.mark.asyncio
async def test_http_request_id_is_bound_to_audit_event_and_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _AuditService()
    monkeypatch.setattr(
        "src.audit.application.recording.get_audit_service", lambda: service
    )
    app = _app(service)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/audit", headers={"X-Request-ID": "trace-210"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "trace-210"
    assert service.events[-1].correlation_id == "trace-210"


@pytest.mark.asyncio
async def test_missing_or_oversized_request_id_gets_fresh_bounded_correlation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _AuditService()
    monkeypatch.setattr(
        "src.audit.application.recording.get_audit_service", lambda: service
    )
    app = _app(service)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        missing = await client.get("/audit")
        oversized = await client.get("/audit", headers={"X-Request-ID": "x" * 129})

    missing_id = missing.headers["X-Request-ID"]
    oversized_id = oversized.headers["X-Request-ID"]
    assert 1 <= len(missing_id) <= 128
    assert 1 <= len(oversized_id) <= 128
    assert missing_id != "x" * 129
    assert service.events[-2].correlation_id == missing_id
    assert service.events[-1].correlation_id == oversized_id
