from __future__ import annotations

import asyncio
import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import TypeAdapter, ValidationError

from src.agents.fundamental.application.annual_statement_reader import (
    AnnualStatementReaderService,
)
from src.agents.fundamental.application.annual_statement_reader_contracts import (
    AnnualStatementReaderBinding,
    AnnualStatementReadIntent,
)
from src.agents.fundamental.application.fundamental_service_port import (
    FundamentalServiceFailure,
)
from src.agents.fundamental.infrastructure.fundamental_service_client import (
    FundamentalServiceClientSettings,
    HttpFundamentalServiceClient,
)
from src.agents.fundamental.interface.fundamental_service_contracts import (
    FundamentalActiveReleaseV1,
)
from src.artifacts.application.service import ArtifactService
from src.shared.artifacts.annual_statement_contracts import (
    AnnualStatementsReadRequestV1,
    AnnualStatementsReadResponseV1,
)
from src.shared.internal_services import InternalPrincipal

FIXTURE = (
    Path(__file__).resolve().parents[4] / "contracts/fixtures/annual-statements.v1.json"
)


def read_intent(**values):
    if values.get("thread_id") is not None:
        payload = {"kind": "existing_thread", **values}
    else:
        payload = {
            "kind": "new_thread",
            "creation_id": "56f29c65-fef4-4ccd-a6aa-cae123e9e71d",
            **values,
        }
    return TypeAdapter(AnnualStatementReadIntent).validate_python(payload)


def wire():
    return json.loads(FIXTURE.read_text())


def binding():
    return AnnualStatementReaderBinding(
        issuer_id="0000000001",
        ticker="TEST",
        company_name="Example Issuer",
        profile_id="annual-statements:explicit-scope",
        cutoff_at=datetime(2024, 12, 1, tzinfo=UTC),
    )


def principal():
    return InternalPrincipal(
        subject_id="reader", organization_id="org-1", membership_id="member-1"
    )


class Repository:
    def __init__(self):
        self.records = {}

    async def save(self, record):
        for existing in self.records.values():
            if existing.dedupe_key == record.dedupe_key:
                return existing.artifact_id
        self.records[record.artifact_id] = record
        return record.artifact_id


def service(*, allowed=True, result=None):
    payload = wire()
    release = FundamentalActiveReleaseV1.model_validate(
        {
            "active": {
                "profile_id": binding().profile_id,
                "manifest_digest": payload["data_release_manifest_digest"],
                "revision": 1,
                "activated_at": "2024-12-01T00:00:00Z",
            },
            "manifest": {
                "profile_id": binding().profile_id,
                "manifest_digest": payload["data_release_manifest_digest"],
                "required_fields": ["revenue"],
            },
        }
    )
    client = SimpleNamespace(
        read_active_release=AsyncMock(return_value=release),
        read_annual_statements=AsyncMock(
            return_value=result
            or AnnualStatementsReadResponseV1.model_validate(payload)
        ),
    )
    repo = Repository()
    owns = AsyncMock(return_value=allowed)
    claim = AsyncMock(return_value=allowed)
    reader = AnnualStatementReaderService(
        client=client,
        artifacts=ArtifactService(repo),
        bindings=(binding(),),
        owns_thread=owns,
        claim_thread=claim,
    )
    return reader, client, repo, owns, claim


@pytest.mark.asyncio
async def test_new_thread_preserves_exact_statement_without_valuation_and_retries_deduplicate():
    reader, client, repo, owns, claim = service()
    first = await reader.read(
        read_intent(issuer_id="0000000001"),
        principal=principal(),
        correlation_id="read-1",
        deadline_at=datetime.now(UTC) + timedelta(seconds=30),
    )
    second = await reader.read(
        read_intent(thread_id=first.thread_id, issuer_id="0000000001"),
        principal=principal(),
        correlation_id="read-2",
        deadline_at=datetime.now(UTC) + timedelta(seconds=30),
    )
    assert first.reference == second.reference
    assert len(repo.records) == 1
    assert "run_id" not in first.reference.download_url
    assert claim.await_args.args == ("reader", first.thread_id, "org-1")
    assert owns.await_args.args == ("reader", first.thread_id, "org-1")
    payload = next(iter(repo.records.values())).envelope.data
    assert payload["fundamental_service"] is None
    assert (
        payload["annual_statements"]["statements"]["tables"][0]["rows"][0]["cells"][0][
            "fact"
        ]["value"]
        == "9007199254740993.125"
    )
    assert (
        payload["annual_statements"]["statements"]["valuation_eligibility"]
        == "not_evaluated"
    )
    assert (
        client.read_annual_statements.await_args.args[0].cutoff_at
        == binding().cutoff_at
    )


@pytest.mark.asyncio
async def test_owner_and_org_denial_happens_before_service_or_storage():
    reader, client, repo, owns, claim = service(allowed=False)
    with pytest.raises(FundamentalServiceFailure) as error:
        await reader.read(
            read_intent(thread_id="other-thread", issuer_id="0000000001"),
            principal=principal(),
            correlation_id="denied",
            deadline_at=datetime.now(UTC) + timedelta(seconds=30),
        )
    assert error.value.code == "THREAD_NOT_FOUND"
    client.read_active_release.assert_not_awaited()
    claim.assert_not_awaited()
    assert repo.records == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("issuer_id", "0000000002"),
        ("security_id", "another-security"),
        ("security_scope", "another-share-class"),
    ],
)
async def test_service_scope_cannot_be_mislabeled_as_catalog_company(field, value):
    response = AnnualStatementsReadResponseV1.model_validate(wire())
    changed_scope = response.statements.scope.model_copy(update={field: value})
    changed = response.model_copy(
        update={
            "statements": response.statements.model_copy(
                update={"scope": changed_scope}
            )
        }
    )
    reader, client, repo, *_ = service(result=changed)
    with pytest.raises(FundamentalServiceFailure) as error:
        await reader.read(
            read_intent(thread_id="thread", issuer_id="0000000001"),
            principal=principal(),
            correlation_id="scope",
            deadline_at=datetime.now(UTC) + timedelta(seconds=30),
        )
    assert error.value.code == "STATEMENT_READ_BINDING_MISMATCH"
    assert repo.records == {}


@pytest.mark.parametrize(
    "change", ["number", "period", "issuer", "lookahead", "evidence"]
)
def test_statement_contract_rejects_corrupt_cell_bindings(change):
    payload = wire()
    cell = payload["statements"]["tables"][0]["rows"][0]["cells"][0]
    if change == "number":
        cell["fact"]["value"] = 42
    elif change == "period":
        cell["period_id"] = "a" * 64
    elif change == "issuer":
        cell["fact"]["issuer_id"] = "0000000002"
    elif change == "lookahead":
        cell["fact"]["available_at"] = "2025-01-01T00:00:00Z"
    else:
        payload["statements"]["candidate_evidence"] = []
    with pytest.raises(ValidationError):
        AnnualStatementsReadResponseV1.model_validate(payload)


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", [None, "cutoff", "manifest", "malformed"])
async def test_signed_typed_client_uses_statement_route_and_rejects_response_mismatch(
    mismatch,
):
    payload = copy.deepcopy(wire())
    if mismatch == "cutoff":
        payload["statements"]["cutoff_at"] = "2024-12-02T00:00:00Z"
    if mismatch == "manifest":
        payload["data_release_manifest_digest"] = "b" * 64
    if mismatch == "malformed":
        payload["statements"]["tables"][0]["rows"][0]["cells"][0]["fact"]["value"] = (
            "NaN"
        )

    async def respond(request):
        assert request.url.path == "/v1/data/annual-statements"
        body = json.loads(request.content)
        assert body["input"]["contract_version"] == "fundamental.annual-statements.v1"
        assert body["context"]["principal"]["organization_id"] == "org-1"
        assert body["context"]["signature"]
        return httpx.Response(
            200,
            json={
                "contract_version": "internal.v1",
                "schema_version": "fundamental.v1",
                "correlation_id": "typed",
                "result": payload,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as transport:
        client = HttpFundamentalServiceClient(
            FundamentalServiceClientSettings(
                base_url="https://fundamental.test", service_token="test-key"
            ),
            client=transport,
        )
        request = AnnualStatementsReadRequestV1(
            data_release_manifest_digest=wire()["data_release_manifest_digest"],
            cutoff_at=binding().cutoff_at,
        )
        if mismatch:
            with pytest.raises(FundamentalServiceFailure):
                await client.read_annual_statements(
                    request,
                    principal=principal(),
                    correlation_id="typed",
                    deadline_at=datetime.now(UTC) + timedelta(seconds=30),
                )
        else:
            result = await client.read_annual_statements(
                request,
                principal=principal(),
                correlation_id="typed",
                deadline_at=datetime.now(UTC) + timedelta(seconds=30),
            )
            assert (
                result.statements.tables[0].rows[0].cells[0].fact.value
                == "9007199254740993.125"
            )


@pytest.mark.asyncio
async def test_new_read_intent_retries_and_concurrent_reads_keep_one_thread_and_artifact():
    reader, client, repo, owns, claim = service()
    first_failure = FundamentalServiceFailure(
        "UPSTREAM_UNAVAILABLE", "Unavailable", retryable=True
    )
    client.read_annual_statements.side_effect = [
        first_failure,
        AnnualStatementsReadResponseV1.model_validate(wire()),
        AnnualStatementsReadResponseV1.model_validate(wire()),
    ]
    intent = read_intent(issuer_id="0000000001")
    kwargs = {
        "principal": principal(),
        "correlation_id": "stable-retry",
        "deadline_at": datetime.now(UTC) + timedelta(seconds=30),
    }
    with pytest.raises(FundamentalServiceFailure):
        await reader.read(intent, **kwargs)
    results = await asyncio.gather(
        reader.read(intent, **kwargs), reader.read(intent, **kwargs)
    )
    assert results[0] == results[1]
    assert len(repo.records) == 1
    assert len({call.args[1] for call in claim.await_args_list}) == 1
    owns.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_catalog_issuer_does_not_claim_a_thread():
    reader, client, repo, owns, claim = service()
    with pytest.raises(FundamentalServiceFailure) as error:
        await reader.read(
            read_intent(issuer_id="0000000002"),
            principal=principal(),
            correlation_id="unknown",
            deadline_at=datetime.now(UTC) + timedelta(seconds=30),
        )
    assert error.value.code == "STATEMENT_READER_UNAVAILABLE"
    claim.assert_not_awaited()
    client.read_active_release.assert_not_awaited()
    assert repo.records == {}


def test_new_read_and_existing_thread_identities_are_mutually_exclusive():
    with pytest.raises(ValidationError):
        TypeAdapter(AnnualStatementReadIntent).validate_python(
            {
                "kind": "new_thread",
                "issuer_id": "0000000001",
                "creation_id": "56f29c65-fef4-4ccd-a6aa-cae123e9e71d",
                "thread_id": "thread-existing",
            }
        )
