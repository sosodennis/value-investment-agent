from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime

import pytest

from src.agents.fundamental.application.fundamental_service_port import (
    FundamentalServiceFailure,
)
from src.agents.fundamental.application.workflow_orchestrator.services.service_request_producer import (
    prepare_service_valuation_request,
)
from src.agents.fundamental.interface.fundamental_service_contracts import (
    FundamentalIdentityResolutionV1,
    FundamentalServiceResponseV1,
)
from src.shared.cross_agent.domain.market_identity import CompanyProfile
from src.shared.internal_services import InternalPrincipal


class _Client:
    def __init__(self, *, ingestion: Mapping[str, object]) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.ingestion = dict(ingestion)

    async def resolve_identity(self, request, **_kwargs):
        self.calls.append(("resolve_identity", request.model_dump(mode="json")))
        identity = {
            "issuer_id": "0000320193",
            "issuer_name": "Apple Inc.",
            "domicile": "US",
            "reporting_basis": "us-gaap",
            "security_id": "AAPL",
            "share_class": "AAPL",
            "currency": "USD",
        }
        payload = {
            "ticker": "AAPL",
            "identity": identity,
            "mapping_version": "sec-issuer-identity-v1",
            "source_evidence": tuple(
                {
                    "source_id": source_id,
                    "source_uri": f"https://sec.test/{source_id}",
                    "content_hash": "a" * 64,
                    "captured_at": "2026-11-07T00:00:00Z",
                    "available_at": "2026-11-07T00:00:00Z",
                    "media_type": "application/json",
                    "byte_count": 1,
                }
                for source_id in (
                    "sec-company-tickers",
                    "sec-submissions",
                    "sec-companyfacts",
                )
            ),
        }
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return FundamentalIdentityResolutionV1.model_validate_json(
            json.dumps(
                {**payload, "resolution_digest": hashlib.sha256(canonical).hexdigest()},
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )

    async def execute(self, operation, input_payload, **_kwargs):
        self.calls.append((operation, dict(input_payload)))
        result = {
            **self.ingestion,
            "valuation_timestamp": input_payload["valuation_timestamp"],
        }
        return FundamentalServiceResponseV1(
            contract_version="internal.v1",
            schema_version="fundamental.v1",
            correlation_id="correlation-1",
            result=result,
        )


def _principal() -> InternalPrincipal:
    return InternalPrincipal(
        subject_id="subject-1", organization_id="org-1", membership_id="member-1"
    )


def _ingestion(*, status: str = "created") -> dict[str, object]:
    return {
        "contract_version": "fundamental.v1",
        "status": status,
        "identity": {
            "issuer_id": "0000320193",
            "issuer_name": "Apple Inc.",
            "domicile": "US",
            "reporting_basis": "us-gaap",
            "security_id": "AAPL",
            "share_class": "AAPL",
            "currency": "USD",
        },
        "valuation_timestamp": "2026-11-07T00:00:00Z",
        "snapshot_id": "snapshot-aapl-1",
        "manifest_digest": "b" * 64,
        "canonical_fact_ids": ["fact-revenue", "fact-operating-income"],
        "quality_status": "verified",
        "parser_version": "2.47.4",
        "validation_profile_id": "sec-efm-us-dqc-v31.0.3",
        "validation_profile_digest": "c" * 64,
        "taxonomy_manifest_id": "sec-us-gaap-2023-2024-public-bundle",
        "taxonomy_version": "us-gaap-2023-2024",
        "reused": status == "reused",
        "coalesced": False,
        "correlation_id": "correlation-1",
    }


def _state(*, request: Mapping[str, object] | None = None) -> dict[str, object]:
    fundamental: dict[str, object] = {"model_type": "dcf_standard"}
    if request is not None:
        fundamental["valuation_request"] = dict(request)
    return {
        "company_profile": CompanyProfile(ticker="AAPL", name="Apple Inc."),
        "fundamental_analysis": fundamental,
    }


def _request() -> dict[str, object]:
    return {
        "contract_version": "fundamental.v1",
        "valuation_context": {
            "valuation_timestamp": "2026-11-07T00:00:00Z",
            "source_selection_policy": "pit-v1",
            "coverage_profile": "us-gaap-public-v1",
        },
        "assumptions": {"trace": {"description": "caller-owned"}},
        "uncertainty": {"mode": "none"},
        "quality": {"status": "verified"},
        "provenance": {
            "snapshot_id": "pending",
            "fact_ids": [],
            "mapping_version": "sec-us-gaap-v1",
            "parser_version": "2.47.4",
            "taxonomy_version": "us-gaap-2023-2024",
            "policy_version": "sec-public-pit-v1",
        },
        "model_id": "fcff_dcf",
        "model_version": "fcff_dcf-v1",
        "policy_id": "fcff_dcf-us-gaap-public-v1",
    }


@pytest.mark.asyncio
async def test_producer_resolves_identity_then_ingests_and_pins_request() -> None:
    client = _Client(ingestion=_ingestion())

    prepared = await prepare_service_valuation_request(
        _state(request=_request()),
        client=client,
        principal=_principal(),
        correlation_id="correlation-1",
        deadline_at=datetime(2026, 11, 7, tzinfo=UTC),
    )

    assert [operation for operation, _ in client.calls] == [
        "resolve_identity",
        "ingest_sec_data",
    ]
    ingestion_payload = client.calls[1][1]
    assert ingestion_payload["cik"] == "0000320193"
    assert ingestion_payload["ticker"] == "AAPL"
    assert ingestion_payload["required_fields"] == [
        "revenue",
        "operating_income",
        "cash",
        "debt",
        "diluted_shares",
    ]
    assert prepared.snapshot_selector["identity"] == prepared.identity
    assert prepared.snapshot_selector["valuation_timestamp"] == "2026-11-07T00:00:00Z"
    assert prepared.valuation_request is not None
    assert prepared.valuation_request["historical_facts"] == [
        "fact-revenue",
        "fact-operating-income",
    ]
    assert prepared.valuation_request["identity"] == prepared.identity


@pytest.mark.asyncio
async def test_producer_returns_explicit_missing_assumptions_reason() -> None:
    client = _Client(ingestion=_ingestion())

    prepared = await prepare_service_valuation_request(
        _state(),
        client=client,
        principal=_principal(),
        correlation_id="correlation-1",
        deadline_at=datetime(2026, 11, 7, tzinfo=UTC),
    )

    assert prepared.valuation_request is None
    assert prepared.reason == "caller valuation assumptions are required"
    assert prepared.ingestion["snapshot_id"] == "snapshot-aapl-1"


@pytest.mark.asyncio
async def test_producer_rejects_identity_mismatch_before_ingestion() -> None:
    client = _Client(ingestion=_ingestion())
    request = _request()
    request["identity"] = {"issuer_id": "0000000001"}

    with pytest.raises(FundamentalServiceFailure, match="identity") as error:
        await prepare_service_valuation_request(
            _state(request=request),
            client=client,
            principal=_principal(),
            correlation_id="correlation-1",
            deadline_at=datetime(2026, 11, 7, tzinfo=UTC),
        )

    assert error.value.code == "IDENTITY_MISMATCH"
    assert [operation for operation, _ in client.calls] == ["resolve_identity"]


@pytest.mark.asyncio
async def test_producer_rejects_degraded_ingestion_without_snapshot() -> None:
    client = _Client(ingestion=_ingestion(status="degraded"))

    with pytest.raises(FundamentalServiceFailure) as error:
        await prepare_service_valuation_request(
            _state(request=_request()),
            client=client,
            principal=_principal(),
            correlation_id="correlation-1",
            deadline_at=datetime(2026, 11, 7, tzinfo=UTC),
        )

    assert error.value.code == "SEC_INGESTION_DEGRADED"


@pytest.mark.asyncio
async def test_producer_rejects_missing_ticker_without_service_calls() -> None:
    client = _Client(ingestion=_ingestion())

    with pytest.raises(FundamentalServiceFailure) as error:
        await prepare_service_valuation_request(
            {"company_profile": None, "fundamental_analysis": {}},
            client=client,
            principal=_principal(),
            correlation_id="correlation-1",
            deadline_at=datetime(2026, 11, 7, tzinfo=UTC),
        )

    assert error.value.code == "FUNDAMENTAL_TICKER_MISSING"
    assert client.calls == []
