from __future__ import annotations

import gzip
import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from api.server import app
from src.agents.fundamental.application.statement_reader import (
    FiscalArtifactCurrentReader,
)
from src.agents.fundamental.infrastructure.fundamental_service_client import (
    FundamentalServiceClientSettings,
    HttpFundamentalServiceClient,
)
from src.artifacts.application.wiring import build_default_artifact_service
from src.artifacts.public import build_artifact_envelope
from src.auth.entrypoint import Principal, require_current_user
from src.shared.artifacts.artifact_data_models import FinancialReportsArtifactData
from src.shared.artifacts.fiscal_statement_contracts import (
    FiscalReadRequestV2,
    FiscalReadResultV2,
)
from src.shared.artifacts.statement_read_artifact import (
    StatementEditionV2,
    StatementReadArtifactV3,
)


@pytest.fixture
def fiscal_api(monkeypatch):
    app.dependency_overrides[require_current_user] = lambda: Principal(
        user_id="test-user",
        subject="test-user",
        email="test@example.com",
        organization_id="organization-test",
        membership_id="membership-test",
    )
    service = AsyncMock()
    service.get_artifact_thread_id.return_value = "test-thread"
    service.get_run_thread_id.return_value = "test-thread"
    service.belongs_to_organization.return_value = True
    service.is_agent_output_reference.return_value = False
    service.is_referenced_artifact_reference.return_value = False
    ownership = AsyncMock()
    ownership.owns.return_value = True
    monkeypatch.setattr(
        "src.artifacts.interface.routes.get_ownership_service", lambda: ownership
    )
    app.dependency_overrides[build_default_artifact_service] = lambda: service
    authenticated_api = SimpleNamespace(service=service, ownership=ownership)
    value = FiscalReadResultV2.model_validate_json(
        gzip.decompress(
            (
                Path(__file__).resolve().parents[2]
                / "contracts/fixtures/fiscal-statements-quarter.v2.json.gz"
            ).read_bytes()
        )
    )
    request = FiscalReadRequestV2(
        manifest_digest=value.binding.manifest_digest,
        scope=value.binding.scope,
        cutoff_at=value.binding.cutoff_at,
        frequency="quarter",
    )
    edition = StatementEditionV2(
        edition_id="aapl-historical",
        label="Historical Apple",
        ticker="AAPL",
        company_name="Apple Inc.",
        scope=request.scope,
        cutoff_at=request.cutoff_at,
        annual_manifest_digest="a" * 64,
        fiscal_manifest_digest=request.manifest_digest,
    )
    artifact = StatementReadArtifactV3.from_fiscal(
        edition=edition,
        request=request,
        result=value,
    )
    data = FinancialReportsArtifactData(
        statement_read=artifact,
        model_type="statement_read",
        status="done",
    ).model_dump(mode="json")
    envelope = build_artifact_envelope(
        kind="financial_reports", produced_by="fundamental_analysis", data=data
    )
    authenticated_api.service.get_artifact_envelope.return_value = envelope
    calls = []
    state = {"revoked": False}

    async def respond(incoming):
        body = json.loads(incoming.content)
        calls.append(body)
        assert incoming.method == "GET"
        assert incoming.url.path == "/v1/data/fiscal-statements"
        assert body["input"] == request.model_dump(mode="json")
        assert body["context"]["principal"]["organization_id"] == "organization-test"
        assert body["context"]["signature"]
        base = {
            "contract_version": "internal.v1",
            "schema_version": "fundamental.v1",
            "correlation_id": body["context"]["correlation_id"],
        }
        if state["revoked"]:
            base.pop("schema_version")
            return httpx.Response(
                409,
                json={
                    **base,
                    "error": {
                        "code": "FISCAL_AUTHORITY_REVOKED",
                        "message": "revoked",
                        "retryable": False,
                    },
                },
            )
        return httpx.Response(
            200, json={**base, "result": value.model_dump(mode="json")}
        )

    @asynccontextmanager
    async def factory():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond)
        ) as transport:
            yield FiscalArtifactCurrentReader(
                HttpFundamentalServiceClient(
                    FundamentalServiceClientSettings(
                        base_url="https://fundamental.test",
                        service_token="test-key",
                        max_attempts=1,
                    ),
                    client=transport,
                )
            )

    monkeypatch.setattr(
        "src.artifacts.interface.routes.build_default_fiscal_artifact_current_reader",
        factory,
    )
    yield authenticated_api, envelope, calls, state
    app.dependency_overrides.clear()


async def get_saved(**changes):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as browser:
        return await browser.get("/api/v1/artifacts/saved-fiscal", **changes)


@pytest.mark.asyncio
async def test_saved_fiscal_exact_current_pass_and_conditional_revocation_cannot_return_old_value(
    fiscal_api,
):
    api, envelope, calls, state = fiscal_api
    first = await get_saved()
    assert first.status_code == 200
    assert first.json() == envelope.model_dump(mode="json")
    assert first.headers["cache-control"] == "private, no-store"
    assert "etag" not in first.headers
    conditional = await get_saved(
        headers={
            "If-None-Match": '"saved-fiscal"',
            "If-Modified-Since": "Thu, 01 Jan 2100 00:00:00 GMT",
        }
    )
    assert conditional.status_code == 200
    assert conditional.content == first.content
    assert len(calls) == 2
    state["revoked"] = True
    denied = await get_saved(headers={"If-None-Match": "*"})
    assert denied.status_code == 502
    assert denied.json()["detail"]["code"] == "FISCAL_AUTHORITY_REVOKED"
    assert denied.headers["cache-control"] == "private, no-store"
    assert "statement_read" not in denied.text
    assert "rows" not in denied.text
    assert len(calls) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["org", "owner", "thread", "workflow", "child"])
async def test_saved_fiscal_ownership_checks_precede_current_service_and_payload(
    fiscal_api, failure
):
    api, envelope, calls, state = fiscal_api
    kwargs = {}
    if failure == "org":
        api.service.belongs_to_organization.return_value = False
    if failure == "owner":
        api.ownership.owns.return_value = False
    if failure == "workflow":
        api.service.is_agent_output_reference.return_value = True
    if failure == "child":
        api.service.is_referenced_artifact_reference.return_value = True
    if failure == "thread":
        kwargs = {"params": {"thread_id": "other-thread"}}
    response = await get_saved(**kwargs)
    assert response.status_code == 404
    assert calls == []
    api.service.get_artifact_envelope.assert_not_awaited()
