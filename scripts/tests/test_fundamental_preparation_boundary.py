"""Verify the caller/service wire boundary outside either isolated package."""

import asyncio
from datetime import UTC, datetime, timedelta
import json

import httpx
from pydantic import ValidationError
import pytest

from src.agents.fundamental.infrastructure.fundamental_service_client import (
    FundamentalServiceClientSettings,
    HttpFundamentalServiceClient,
)
from src.shared.artifacts.fundamental_contracts import (
    FundamentalValuationEvidenceReadResultV1,
    FundamentalValuationPreparationResultV1,
)
from src.shared.internal_services import InternalPrincipal

from fundamental_service.contracts import ValuationEvidenceReadResponseV1
from fundamental_service.testsupport import auth_headers, make_internal_envelope

from test_conditional_capital_composer import _prepared_case
from test_conditional_reinvestment_composer import _prepared
from test_valuation_release_inputs import _prepare


@pytest.mark.parametrize("joint_operating", (False, True))
def test_typed_caller_preserves_actual_conditional_service_response(
    tmp_path, joint_operating
):
    prepare = _prepared if joint_operating else _prepared_case
    fixture, service_client, candidate, prepared = prepare(tmp_path)
    response = _prepare(service_client, fixture, candidate)
    assert response.status_code == 200
    envelope = response.json()
    payload = envelope["result"]

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/valuation/prepare"
        context = json.loads(request.content)["context"]
        return httpx.Response(
            200, json={**envelope, "correlation_id": context["correlation_id"]}
        )

    async def read():
        client = HttpFundamentalServiceClient(
            settings=FundamentalServiceClientSettings(
                base_url="https://fundamental.test",
                service_token="synthetic-caller-token",
            ),
            client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
        )
        try:
            return await client.prepare_valuation(
                {
                    "contract_version": "fundamental.v1",
                    "snapshot_id": fixture.snapshot.snapshot_id,
                    "data_release_manifest_digest": candidate.manifest.manifest_digest,
                    "model_id": "fcff_dcf",
                },
                principal=InternalPrincipal(
                    subject_id="subject-test",
                    organization_id="org-test",
                    membership_id="membership-test",
                ),
                correlation_id="conditional-caller-boundary",
                deadline_at=datetime.now(UTC) + timedelta(seconds=30),
            )
        finally:
            await client.aclose()

    projected = asyncio.run(read())
    assert projected.input == payload["input"]
    assert projected.preparation_digest == prepared.preparation_digest
    assert projected.quality_status == "provisional"
    assert list(projected.missing_evidence or ()) == payload["missing_evidence"]
    assert projected.conditional_capital == payload["conditional_capital"]
    assert projected.conditional_quote == payload["conditional_quote"]
    assert projected.conditional_operating == payload.get("conditional_operating")
    assert projected.conditional_capital["policy"]["complete_award_inventory"] is False
    assert projected.conditional_capital["policy"]["complete_capital_claims"] is False
    assert projected.model_dump(mode="json") == payload
    with pytest.raises(ValidationError):
        FundamentalValuationPreparationResultV1.model_validate(
            {**payload, "unrecognized_caller_authorization": True}
        )


@pytest.mark.parametrize("joint_operating", (False, True))
def test_typed_caller_preserves_complete_service_valuation_evidence(
    tmp_path, joint_operating
):
    assert set(FundamentalValuationEvidenceReadResultV1.model_fields) == set(
        ValuationEvidenceReadResponseV1.model_fields
    )
    prepare = _prepared if joint_operating else _prepared_case
    fixture, service_client, candidate, prepared = prepare(tmp_path)
    request_payload = {
        "contract_version": "fundamental.v1",
        "snapshot_id": fixture.snapshot.snapshot_id,
        "data_release_manifest_digest": candidate.manifest.manifest_digest,
        "model_id": "fcff_dcf",
    }
    response = service_client.post(
        "/v1/valuation/evidence/facts",
        headers=auth_headers(),
        json=make_internal_envelope(request_payload),
    )
    assert response.status_code == 200, response.text
    envelope = response.json()

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/valuation/evidence/facts"
        context = json.loads(request.content)["context"]
        return httpx.Response(
            200, json={**envelope, "correlation_id": context["correlation_id"]}
        )

    async def read():
        client = HttpFundamentalServiceClient(
            settings=FundamentalServiceClientSettings(
                base_url="https://fundamental.test",
                service_token="synthetic-caller-token",
            ),
            client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
        )
        try:
            return await client.read_valuation_evidence(
                request_payload,
                principal=InternalPrincipal(
                    subject_id="subject-test",
                    organization_id="org-test",
                    membership_id="membership-test",
                ),
                correlation_id="evidence-caller-boundary",
                deadline_at=datetime.now(UTC) + timedelta(seconds=30),
            )
        finally:
            await client.aclose()

    projected = asyncio.run(read())
    assert projected.model_dump(mode="json") == envelope["result"]
    assert prepared.input is not None
    assert projected.mapping_version == prepared.input.provenance.mapping_version
    with pytest.raises(ValidationError):
        FundamentalValuationEvidenceReadResultV1.model_validate(
            {**envelope["result"], "unrecognized_caller_authorization": True}
        )
