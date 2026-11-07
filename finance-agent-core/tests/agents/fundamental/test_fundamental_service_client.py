from __future__ import annotations

import hashlib
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
from src.agents.fundamental.interface.fundamental_service_contracts import (
    FundamentalIdentityResolutionRequestV1,
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


def _facts_success(correlation_id: str) -> dict[str, object]:
    return {
        "contract_version": "internal.v1",
        "schema_version": "fundamental.v1",
        "correlation_id": correlation_id,
        "result": {
            "contract_version": "fundamental.v1",
            "snapshot_id": "snapshot-aapl-2025",
            "snapshot_manifest_digest": "a" * 64,
            "identity": {
                "issuer_id": "320193",
                "issuer_name": "Apple Inc.",
                "domicile": "US",
                "reporting_basis": "us-gaap",
                "security_id": "US0378331005",
                "share_class": "common",
                "currency": "USD",
            },
            "valuation_timestamp": "2026-01-15T00:00:00Z",
            "quality_status": "verified",
            "facts": [
                {
                    "contract_version": "fundamental.v1",
                    "fact_id": "fact-revenue-2025",
                    "issuer_id": "320193",
                    "concept": "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
                    "normalized_field": "total_revenue",
                    "value": 100,
                    "unit": "USD",
                    "scale": 0,
                    "currency": "USD",
                    "period_start": "2024-10-01",
                    "period_end": "2025-09-27",
                    "context": {
                        "concept_qname": "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
                        "period_type": "duration",
                        "start_date": "2024-10-01",
                        "end_date": "2025-09-27",
                        "unit_qname": "iso4217:USD",
                        "measure": "iso4217:USD",
                        "entity_scope": "320193",
                        "consolidation_scope": "consolidated",
                        "context_id": "D2025",
                    },
                    "as_of": "2025-09-27T00:00:00Z",
                    "available_at": "2025-11-01T00:00:00Z",
                    "captured_at": "2025-11-02T00:00:00Z",
                    "accession_number": "0000320193-25-000073",
                    "taxonomy_version": "us-gaap-2025",
                    "source": {
                        "source_url": "https://www.sec.gov/Archives/filing.xml",
                        "content_hash": "b" * 64,
                        "source_role": "filing",
                        "captured_at": "2025-11-02T00:00:00Z",
                        "available_at": "2025-11-01T00:00:00Z",
                        "filed_at": "2025-11-01T00:00:00Z",
                        "accession_number": "0000320193-25-000073",
                        "parser_version": "2.47.4",
                        "taxonomy_version": "us-gaap-2025",
                    },
                    "quality": "verified",
                    "mapping_decision_id": "mapping-revenue-v1",
                    "mapping_confidence": "high",
                    "rejected_candidate_reasons": [
                        {"candidate_id": "segment", "reason": "not consolidated"}
                    ],
                    "point_in_time_policy": "sec-pit-v1",
                }
            ],
        },
    }


def _identity_result() -> dict[str, object]:
    payload: dict[str, object] = {
        "ticker": "AAPL",
        "identity": {
            "issuer_id": "0000320193",
            "issuer_name": "Apple Inc.",
            "domicile": "US",
            "reporting_basis": "us-gaap",
            "security_id": "AAPL",
            "share_class": "AAPL",
            "currency": "USD",
        },
        "mapping_version": "sec-issuer-identity-v1",
        "source_evidence": [
            {
                "source_id": source_id,
                "source_uri": source_uri,
                "content_hash": "a" * 64,
                "captured_at": "2026-11-07T00:00:00Z",
                "available_at": "2026-11-07T00:00:00Z",
                "media_type": "application/json",
                "byte_count": 1,
            }
            for source_id, source_uri in (
                (
                    "sec-company-tickers",
                    "https://www.sec.gov/files/company_tickers.json",
                ),
                (
                    "sec-submissions",
                    "https://data.sec.gov/submissions/CIK0000320193.json",
                ),
                (
                    "sec-companyfacts",
                    "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
                ),
            )
        ],
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return {**payload, "resolution_digest": hashlib.sha256(canonical).hexdigest()}


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
async def test_client_calls_sec_ingestion_with_its_bounded_service_timeout() -> None:
    captured: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        body = json.loads(request.content)
        return httpx.Response(200, json=_success(body["context"]["correlation_id"]))

    client = HttpFundamentalServiceClient(
        _settings(), client=httpx.AsyncClient(transport=httpx.MockTransport(respond))
    )
    result = await client.execute(
        "ingest_sec_data",
        {"contract_version": "fundamental.v1", "ticker": "MSFT"},
        principal=_principal(),
        correlation_id="correlation-ingestion",
        deadline_at=datetime.now(UTC) + timedelta(seconds=180),
    )

    assert result.correlation_id == "correlation-ingestion"
    assert captured[0].url.path == "/v1/data/ingestions"
    assert captured[0].extensions["timeout"]["read"] == 120.0
    assert json.loads(captured[0].content)["input"]["ticker"] == "MSFT"
    await client.aclose()


@pytest.mark.asyncio
async def test_client_reads_typed_facts_from_the_immutable_snapshot_endpoint() -> None:
    captured: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        body = json.loads(request.content)
        return httpx.Response(
            200, json=_facts_success(body["context"]["correlation_id"])
        )

    client = HttpFundamentalServiceClient(
        _settings(), client=httpx.AsyncClient(transport=httpx.MockTransport(respond))
    )
    result = await client.read_facts(
        {
            "contract_version": "fundamental.v1",
            "snapshot_id": "snapshot-aapl-2025",
            "required_fields": ["total_revenue"],
        },
        principal=_principal(),
        correlation_id="correlation-facts",
        deadline_at=datetime.now(UTC) + timedelta(seconds=5),
    )

    assert captured[0].url.path == "/v1/data/facts"
    assert captured[0].method == "GET"
    assert result.snapshot_id == "snapshot-aapl-2025"
    assert result.snapshot_manifest_digest == "a" * 64
    assert result.identity.issuer_id == "320193"
    assert result.facts[0].fact_id == "fact-revenue-2025"
    assert result.facts[0].source.content_hash == "b" * 64
    await client.aclose()


@pytest.mark.asyncio
async def test_client_resolves_identity_with_typed_digest_bound_response() -> None:
    captured: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                **_success(body["context"]["correlation_id"]),
                "result": _identity_result(),
            },
        )

    client = HttpFundamentalServiceClient(
        _settings(), client=httpx.AsyncClient(transport=httpx.MockTransport(respond))
    )
    result = await client.resolve_identity(
        FundamentalIdentityResolutionRequestV1(ticker=" aapl "),
        principal=_principal(),
        correlation_id="correlation-identity",
        deadline_at=datetime.now(UTC) + timedelta(seconds=180),
    )

    assert result.ticker == "AAPL"
    assert result.identity.issuer_id == "0000320193"
    assert result.resolution_digest
    assert captured[0].url.path == "/v1/identity/resolve"
    assert captured[0].extensions["timeout"]["read"] == 120.0
    assert json.loads(captured[0].content)["input"] == {"ticker": "AAPL"}
    await client.aclose()


@pytest.mark.asyncio
async def test_client_rejects_identity_response_with_changed_source_hash() -> None:
    invalid_result = _identity_result()
    invalid_result["source_evidence"][0]["content_hash"] = "b" * 64

    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                **_success(body["context"]["correlation_id"]),
                "result": invalid_result,
            },
        )

    client = HttpFundamentalServiceClient(
        _settings(max_attempts=1),
        client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )

    with pytest.raises(FundamentalServiceFailure) as error:
        await client.resolve_identity(
            FundamentalIdentityResolutionRequestV1(ticker="AAPL"),
            principal=_principal(),
            correlation_id="correlation-identity-invalid",
            deadline_at=datetime.now(UTC) + timedelta(seconds=5),
        )

    assert error.value.code == "UPSTREAM_MALFORMED"
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
