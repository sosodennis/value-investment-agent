from __future__ import annotations

import copy
import gzip
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from pydantic import TypeAdapter, ValidationError

from src.agents.fundamental.application.fundamental_service_port import (
    FundamentalServiceFailure,
)
from src.agents.fundamental.application.statement_reader import (
    FiscalArtifactCurrentReader,
    StatementReaderService,
)
from src.agents.fundamental.application.statement_reader_contracts import (
    StatementReadIntentV2,
)
from src.agents.fundamental.composition.statement_routes import build_statement_router
from src.agents.fundamental.infrastructure.fundamental_service_client import (
    FundamentalServiceClientSettings,
    HttpFundamentalServiceClient,
)
from src.artifacts.public import ArtifactCurrentReadFailure, ArtifactService
from src.auth.entrypoint import (
    Principal,
    require_current_user,
    require_current_user_mutation,
)
from src.shared.artifacts.artifact_data_models import FinancialReportsArtifactData
from src.shared.artifacts.fiscal_statement_contracts import (
    FiscalReadRequestV2,
    FiscalReadResultV2,
    fiscal_digest,
)
from src.shared.artifacts.statement_read_artifact import (
    AnnualSavedReadV2,
    FiscalSavedReadV3,
    StatementEditionV2,
    StatementReadArtifactV3,
)
from src.shared.internal_services import InternalPrincipal

FIXTURES = Path(__file__).resolve().parents[4] / "contracts/fixtures"


def wire(frequency="quarter"):
    return json.loads(
        gzip.decompress(
            (FIXTURES / f"fiscal-statements-{frequency}.v2.json.gz").read_bytes()
        )
    )


def result(frequency="quarter"):
    return FiscalReadResultV2.model_validate(wire(frequency))


def edition(identity="aapl-historical"):
    binding = result().binding
    return StatementEditionV2(
        edition_id=identity,
        label="Historical Apple",
        ticker="AAPL",
        company_name="Apple Inc.",
        scope=binding.scope,
        cutoff_at=binding.cutoff_at,
        annual_manifest_digest="a" * 64,
        fiscal_manifest_digest=binding.manifest_digest,
    )


def intent(frequency="quarter", **changes):
    values = {
        "contract_version": "workspace.statement-reader.v2",
        "kind": "new_thread",
        "creation_id": "56f29c65-fef4-4ccd-a6aa-cae123e9e71d",
        "edition_id": "aapl-historical",
        "frequency": frequency,
        **changes,
    }
    if values["kind"] == "existing_thread":
        values.pop("creation_id", None)
    return TypeAdapter(StatementReadIntentV2).validate_python(values)


def principal():
    return InternalPrincipal(
        subject_id="reader", organization_id="org-1", membership_id="member-1"
    )


def limit():
    return datetime.now(UTC) + timedelta(seconds=30)


class Repository:
    def __init__(self):
        self.records = {}

    async def save(self, record):
        for existing in self.records.values():
            if existing.dedupe_key == record.dedupe_key:
                return existing.artifact_id
        self.records[record.artifact_id] = record
        return record.artifact_id

    async def get_by_id(self, artifact_id):
        return self.records.get(artifact_id)

    async def get_thread_id(self, artifact_id):
        record = self.records.get(artifact_id)
        return None if record is None else record.thread_id

    async def belongs_to_organization(self, **kwargs):
        return True

    async def is_agent_output_reference(self, **kwargs):
        return False

    async def is_referenced_artifact_reference(self, **kwargs):
        return False


def service(*, allowed=True):
    client = SimpleNamespace(
        read_fiscal_statements=AsyncMock(
            side_effect=lambda request, **kwargs: result(request.frequency)
        ),
        read_annual_statements=AsyncMock(),
        read_active_release=AsyncMock(),
    )
    repo = Repository()
    owns = AsyncMock(return_value=allowed)
    claim = AsyncMock(return_value=allowed)
    reader = StatementReaderService(
        client=client,
        artifacts=ArtifactService(repo),
        editions=(edition(), edition("aapl-current")),
        owns_thread=owns,
        claim_thread=claim,
    )
    return reader, client, repo, owns, claim


@pytest.mark.asyncio
async def test_named_editions_same_issuer_and_selected_frequency_without_workflow_or_other_closure():
    reader, client, repo, owns, claim = service()
    assert [entry.edition_id for entry in reader.catalog().entries] == [
        "aapl-historical",
        "aapl-current",
    ]
    responses = []
    for frequency in ("quarter", "quarter", "ttm"):
        responses.append(
            await reader.read(
                intent(frequency),
                principal=principal(),
                correlation_id="reader",
                deadline_at=limit(),
            )
        )
    assert responses[0] == responses[1]
    assert responses[0].thread_id == responses[2].thread_id
    assert responses[0].reference.artifact_id != responses[2].reference.artifact_id
    assert len(repo.records) == 2
    assert all("run_id" not in item.reference.download_url for item in responses)
    client.read_active_release.assert_not_awaited()
    client.read_annual_statements.assert_not_awaited()
    owns.assert_not_awaited()
    assert claim.await_count == 3
    for record in repo.records.values():
        payload = FinancialReportsArtifactData.model_validate(record.envelope.data)
        assert payload.statement_read is not None
        assert payload.statement_read.edition == edition()
        assert payload.ticker is None and payload.company_name is None
        fiscal = payload.statement_read.read
        assert isinstance(fiscal, FiscalSavedReadV3)
        expected = result(fiscal.request.frequency)
        assert fiscal.result_digest == fiscal_digest(expected)
        assert fiscal.result.model_dump(mode="json") == expected.model_dump(mode="json")
        assert fiscal.request.manifest_digest == edition().fiscal_manifest_digest


@pytest.mark.asyncio
async def test_existing_thread_owner_failure_precedes_current_reader_and_storage():
    reader, client, repo, owns, claim = service(allowed=False)
    with pytest.raises(FundamentalServiceFailure, match="Thread not found"):
        await reader.read(
            intent(kind="existing_thread", thread_id="wrong-thread", creation_id=None),
            principal=principal(),
            correlation_id="denied",
            deadline_at=limit(),
        )
    assert repo.records == {}
    client.read_fiscal_statements.assert_not_awaited()


@pytest.mark.parametrize(
    "change",
    [
        {"frequency": "monthly"},
        {"contract_version": "workspace.statement-reader.v3"},
        {"issuer_id": "0000320193"},
    ],
)
def test_unknown_protocol_and_free_selectors_are_rejected(change):
    with pytest.raises(ValidationError):
        intent(**change)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mismatch",
    [None, "manifest", "scope", "cutoff", "frequency", "protocol", "periodset"],
)
async def test_typed_signed_service_get_rejects_mismatched_request_binding(mismatch):
    payload = copy.deepcopy(wire())
    request = FiscalReadRequestV2(
        manifest_digest=result().binding.manifest_digest,
        scope=result().binding.scope,
        cutoff_at=result().binding.cutoff_at,
        frequency="quarter",
    )
    if mismatch == "manifest":
        payload["binding"]["manifest_digest"] = "b" * 64
    if mismatch == "scope":
        payload["binding"]["scope"]["issuer_id"] = "0000000002"
    if mismatch == "cutoff":
        payload["binding"]["cutoff_at"] = "2000-01-01T00:00:00Z"
    if mismatch == "frequency":
        payload = wire("ttm")
    if mismatch == "protocol":
        payload["contract_version"] = "fundamental.fiscal-statements.unsupported"
    if mismatch == "periodset":
        payload["binding"]["selected_period_set_digest"] = "b" * 64

    async def respond(incoming):
        assert incoming.method == "GET"
        assert incoming.url.path == "/v1/data/fiscal-statements"
        body = json.loads(incoming.content)
        assert body["input"] == request.model_dump(mode="json")
        assert body["context"]["signature"]
        assert body["context"]["principal"]["organization_id"] == "org-1"
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
                base_url="https://fundamental.test",
                service_token="test-key",
                max_attempts=1,
            ),
            client=transport,
        )
        if mismatch:
            with pytest.raises(FundamentalServiceFailure):
                await client.read_fiscal_statements(
                    request,
                    principal=principal(),
                    correlation_id="typed",
                    deadline_at=limit(),
                )
        else:
            actual = await client.read_fiscal_statements(
                request,
                principal=principal(),
                correlation_id="typed",
                deadline_at=limit(),
            )
            assert actual == result()


@pytest.mark.asyncio
async def test_current_reader_uses_exact_retained_request_and_named_revocation():
    value = result()
    request = FiscalReadRequestV2(
        manifest_digest=value.binding.manifest_digest,
        scope=value.binding.scope,
        cutoff_at=value.binding.cutoff_at,
        frequency="quarter",
    )
    artifact = FiscalSavedReadV3(
        request=request,
        result=value,
        result_digest=fiscal_digest(value),
    )
    client = SimpleNamespace(read_fiscal_statements=AsyncMock(return_value=value))
    reader = FiscalArtifactCurrentReader(client)
    await reader.check_current(
        artifact, principal=principal(), correlation_id="saved", deadline_at=limit()
    )
    assert client.read_fiscal_statements.await_args.args == (request,)
    client.read_fiscal_statements.side_effect = FundamentalServiceFailure(
        "FISCAL_AUTHORITY_REVOKED", "revoked", retryable=False, status_code=409
    )
    with pytest.raises(ArtifactCurrentReadFailure) as error:
        await reader.check_current(
            artifact, principal=principal(), correlation_id="saved", deadline_at=limit()
        )
    assert error.value.code == "FISCAL_AUTHORITY_REVOKED"


@pytest.mark.asyncio
async def test_authenticated_reader_new_thread_and_org_context():
    reader, client, repo, owns, claim = service()

    @asynccontextmanager
    async def factory():
        yield reader

    app = FastAPI()
    app.include_router(build_statement_router(factory))
    user = Principal(
        user_id="reader",
        subject="reader",
        email="reader@example.com",
        organization_id="org-1",
        membership_id="member-1",
    )
    app.dependency_overrides[require_current_user] = lambda: user
    app.dependency_overrides[require_current_user_mutation] = lambda: user
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as browser:
        catalog = await browser.get("/api/v1/fundamental/statements/catalog")
        assert len(catalog.json()["entries"]) == 2
        accepted = await browser.post(
            "/api/v1/fundamental/statements/read", json=intent().model_dump(mode="json")
        )
        assert accepted.status_code == 200
        assert accepted.json()["frequency"] == "quarter"
        denied = await browser.post(
            "/api/v1/fundamental/statements/read",
            json=intent().model_dump(mode="json"),
            headers={"X-Organization-ID": "other"},
        )
        assert denied.status_code == 403
    assert len(repo.records) == 1


@pytest.mark.asyncio
async def test_v2_annual_reads_pinned_manifest_only_and_preserves_v1_payload():
    from src.shared.artifacts.annual_statement_contracts import (
        AnnualStatementsReadResponseV1,
    )

    annual = AnnualStatementsReadResponseV1.model_validate_json(
        (FIXTURES / "annual-statements.v1.json").read_text()
    )
    selected = StatementEditionV2(
        edition_id="annual-control",
        label="Annual control",
        ticker="TEST",
        company_name="Example Issuer",
        scope=annual.statements.scope,
        cutoff_at=annual.statements.cutoff_at,
        annual_manifest_digest=annual.data_release_manifest_digest,
        fiscal_manifest_digest="f" * 64,
    )
    client = SimpleNamespace(
        read_annual_statements=AsyncMock(return_value=annual),
        read_fiscal_statements=AsyncMock(),
        read_active_release=AsyncMock(),
    )
    repo = Repository()
    reader = StatementReaderService(
        client=client,
        artifacts=ArtifactService(repo),
        editions=(selected,),
        owns_thread=AsyncMock(return_value=True),
        claim_thread=AsyncMock(return_value=True),
    )
    response = await reader.read(
        intent("annual", edition_id="annual-control"),
        principal=principal(),
        correlation_id="annual",
        deadline_at=limit(),
    )
    stored = next(iter(repo.records.values())).envelope.data
    saved = StatementReadArtifactV3.model_validate(stored["statement_read"])
    assert saved.edition == selected
    assert isinstance(saved.read, AnnualSavedReadV2)
    assert saved.read.response.model_dump(mode="json") == annual.model_dump(mode="json")
    assert stored["annual_statements"] is None
    assert "fiscal_statements" not in stored
    assert stored["ticker"] is None and stored["company_name"] is None
    assert response.frequency == "annual"
    assert (
        client.read_annual_statements.await_args.args[0].data_release_manifest_digest
        == selected.annual_manifest_digest
    )
    client.read_fiscal_statements.assert_not_awaited()
    client.read_active_release.assert_not_awaited()


@pytest.mark.parametrize(
    "field,value", [("value", 1.25), ("value", "NaN"), ("value", "not-a-number")]
)
def test_fiscal_boundary_rejects_noncanonical_wire_amounts(field, value):
    payload = wire()
    node = next(
        node
        for node in payload["evidence"]["nodes"]
        if node["availability"] in {"reported", "derived"}
    )
    node[field] = value
    with pytest.raises(ValidationError):
        FiscalReadResultV2.model_validate(payload)


def test_saved_fiscal_artifact_cannot_change_frequency_or_amount_digest():
    value = result()
    request = FiscalReadRequestV2(
        manifest_digest=value.binding.manifest_digest,
        scope=value.binding.scope,
        cutoff_at=value.binding.cutoff_at,
        frequency="quarter",
    )
    with pytest.raises(ValidationError):
        FiscalSavedReadV3(
            request=request.model_copy(update={"frequency": "ttm"}),
            result=value,
            result_digest=fiscal_digest(value),
        )
    with pytest.raises(ValidationError):
        FiscalSavedReadV3(
            request=request,
            result=value,
            result_digest="b" * 64,
        )


@pytest.mark.parametrize("frequency", ["quarter", "ttm"])
def test_compressed_fixture_preserves_original_current_read_identity(frequency):
    import hashlib

    manifest = json.loads((FIXTURES / "fiscal-statements.origin.v1.json").read_text())
    identity = manifest["responses"][frequency]
    compressed = (FIXTURES / identity["file"]).read_bytes()
    raw = gzip.decompress(compressed)
    assert hashlib.sha256(compressed).hexdigest() == identity["gzip_sha256"]
    assert hashlib.sha256(raw).hexdigest() == identity["sha256"]
    assert len(raw) == identity["bytes"]
    original = json.loads(raw)
    assert original["contract_version"] == "fundamental.fiscal-statements.v1"
    assert sum(len(row["cells"]) for row in original["rows"]) == identity["cells"]


@pytest.mark.asyncio
async def test_public_annual_saved_selection_distinguishes_two_legal_editions_and_retries():
    from src.shared.artifacts.annual_statement_contracts import (
        AnnualStatementsReadResponseV1,
    )

    annual = AnnualStatementsReadResponseV1.model_validate_json(
        (FIXTURES / "annual-statements.v1.json").read_text()
    )
    editions = tuple(
        StatementEditionV2(
            edition_id=name,
            label="Saved annual control",
            ticker="TEST",
            company_name="Example Issuer",
            scope=annual.statements.scope,
            cutoff_at=annual.statements.cutoff_at,
            annual_manifest_digest=annual.data_release_manifest_digest,
            fiscal_manifest_digest=digest * 64,
        )
        for name, digest in (("edition-one", "a"), ("edition-two", "b"))
    )
    repo = Repository()
    client = SimpleNamespace(read_annual_statements=AsyncMock(return_value=annual))
    reader = StatementReaderService(
        client=client,
        artifacts=ArtifactService(repo),
        editions=editions,
        owns_thread=AsyncMock(return_value=True),
        claim_thread=AsyncMock(return_value=True),
    )

    @asynccontextmanager
    async def factory():
        yield reader

    app = FastAPI()
    app.include_router(build_statement_router(factory))
    app.dependency_overrides[require_current_user_mutation] = lambda: Principal(
        user_id="reader",
        subject="reader",
        email="reader@example.test",
        organization_id="org-1",
        membership_id="member-1",
    )
    responses = []
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as browser:
        for selected in (*editions, editions[0]):
            response = await browser.post(
                "/api/v1/fundamental/statements/read",
                json=intent("annual", edition_id=selected.edition_id).model_dump(
                    mode="json"
                ),
            )
            assert response.status_code == 200, response.text
            responses.append(response.json())
    assert responses[0]["reference"] != responses[1]["reference"]
    assert responses[0] == responses[2]
    assert len(repo.records) == 2
    snapshots = [
        StatementReadArtifactV3.model_validate(record.envelope.data["statement_read"])
        for record in repo.records.values()
    ]
    assert {saved.edition for saved in snapshots} == set(editions)
    for saved in snapshots:
        assert isinstance(saved.read, AnnualSavedReadV2)
        assert saved.read.response == annual


def controlled_annual(selected):
    import hashlib

    from src.shared.artifacts.annual_statement_contracts import (
        AnnualStatementsReadResponseV1,
    )

    raw = json.loads((FIXTURES / "annual-statements.v1.json").read_text())
    raw["data_release_manifest_digest"] = selected.annual_manifest_digest
    statements = raw["statements"]
    statements["scope"] = selected.scope.model_dump(mode="json")
    statements["cutoff_at"] = selected.cutoff_at.isoformat().replace("+00:00", "Z")
    for field in (
        "tables",
        "candidate_evidence",
        "source_outcomes",
        "coverage",
        "comparability",
        "reconciliations",
    ):
        statements[field] = []
    statements["statement_id"] = hashlib.sha256(
        json.dumps(
            {key: value for key, value in statements.items() if key != "statement_id"},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    return AnnualStatementsReadResponseV1.model_validate(raw)


def saved_intent(response, frequency, **changes):
    return TypeAdapter(StatementReadIntentV2).validate_python(
        {
            "contract_version": "workspace.statement-reader.v2",
            "kind": "saved_artifact",
            "thread_id": response.thread_id,
            "artifact_id": response.reference.artifact_id,
            "frequency": frequency,
            **changes,
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("catalog_mode", ["empty", "reused"])
async def test_saved_public_switch_uses_original_pair_and_destination_only_after_catalog_change(
    catalog_mode,
):
    original = edition()
    annual = controlled_annual(original)
    repo = Repository()
    client = SimpleNamespace(
        read_annual_statements=AsyncMock(return_value=annual),
        read_fiscal_statements=AsyncMock(
            side_effect=lambda request, **kwargs: result(request.frequency)
        ),
        read_active_release=AsyncMock(),
    )

    def reader(editions):
        return StatementReaderService(
            client=client,
            artifacts=ArtifactService(repo),
            editions=editions,
            owns_thread=AsyncMock(return_value=True),
            claim_thread=AsyncMock(return_value=True),
        )

    active = reader((original,))

    @asynccontextmanager
    async def factory():
        yield active

    app = FastAPI()
    app.include_router(build_statement_router(factory))
    app.dependency_overrides[require_current_user_mutation] = lambda: Principal(
        user_id="reader",
        subject="reader",
        email="reader@example.test",
        organization_id="org-1",
        membership_id="member-1",
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as browser:
        created = await browser.post(
            "/api/v1/fundamental/statements/read",
            json=intent("annual").model_dump(mode="json"),
        )
        assert created.status_code == 200, created.text
        from src.agents.fundamental.application.statement_reader_contracts import (
            StatementArtifactResponseV2,
        )

        first = StatementArtifactResponseV2.model_validate(created.json())
        active = reader(
            ()
            if catalog_mode == "empty"
            else (
                original.model_copy(
                    update={
                        "annual_manifest_digest": "b" * 64,
                        "fiscal_manifest_digest": "c" * 64,
                        "ticker": "OTHER",
                        "company_name": "Reused selection",
                    }
                ),
            )
        )
        previous = first
        references = []
        for frequency in ("quarter", "ttm", "annual"):
            before = (
                client.read_annual_statements.await_count,
                client.read_fiscal_statements.await_count,
            )
            response = await browser.post(
                "/api/v1/fundamental/statements/read",
                json=saved_intent(previous, frequency).model_dump(mode="json"),
            )
            assert response.status_code == 200, response.text
            previous = StatementArtifactResponseV2.model_validate(response.json())
            references.append(previous.reference.artifact_id)
            stored = repo.records[previous.reference.artifact_id].envelope.data
            selection = StatementReadArtifactV3.model_validate(stored["statement_read"])
            assert selection.edition == original
            assert selection.frequency == frequency
            after = (
                client.read_annual_statements.await_count,
                client.read_fiscal_statements.await_count,
            )
            assert after == (
                before[0] + (frequency == "annual"),
                before[1] + (frequency != "annual"),
            )
            if frequency != "annual":
                request = client.read_fiscal_statements.await_args.args[0]
                assert request.manifest_digest == original.fiscal_manifest_digest
                assert (
                    request.scope == original.scope
                    and request.cutoff_at == original.cutoff_at
                )
            else:
                assert (
                    client.read_annual_statements.await_args.args[
                        0
                    ].data_release_manifest_digest
                    == original.annual_manifest_digest
                )
        assert references[-1] == first.reference.artifact_id
        assert len(set(references)) == 3
        assert len(repo.records) == 3
        client.read_active_release.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "denied", ["owner", "organization", "thread", "workflow", "child"]
)
async def test_saved_selection_authorization_precedes_payload_and_upstream(denied):
    artifacts = AsyncMock()
    artifacts.get_artifact_thread_id.return_value = "saved-thread"
    artifacts.belongs_to_organization.return_value = denied != "organization"
    artifacts.is_agent_output_reference.return_value = denied == "workflow"
    artifacts.is_referenced_artifact_reference.return_value = denied == "child"
    client = SimpleNamespace(
        read_annual_statements=AsyncMock(), read_fiscal_statements=AsyncMock()
    )
    reader = StatementReaderService(
        client=client,
        artifacts=artifacts,
        editions=(),
        owns_thread=AsyncMock(return_value=denied != "owner"),
        claim_thread=AsyncMock(),
    )
    request = TypeAdapter(StatementReadIntentV2).validate_python(
        {
            "contract_version": "workspace.statement-reader.v2",
            "kind": "saved_artifact",
            "thread_id": "wrong-thread" if denied == "thread" else "saved-thread",
            "artifact_id": "saved-artifact",
            "frequency": "ttm",
        }
    )
    with pytest.raises(FundamentalServiceFailure) as error:
        await reader.read(
            request, principal=principal(), correlation_id="denied", deadline_at=limit()
        )
    assert error.value.status_code == 404
    artifacts.get_artifact_envelope.assert_not_awaited()
    artifacts.save_thread_artifact.assert_not_awaited()
    client.read_annual_statements.assert_not_awaited()
    client.read_fiscal_statements.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["legacy", "version", "producer", "kind", "invalid"])
async def test_saved_selection_requires_original_typed_wrapper_without_catalog_inference(
    source,
):
    from src.artifacts.public import build_artifact_envelope

    selected = edition()
    annual = controlled_annual(selected)
    data = FinancialReportsArtifactData(
        statement_read=StatementReadArtifactV3.from_annual(
            edition=selected, response=annual
        ),
        model_type="statement_read",
        status="done",
    ).model_dump(mode="json")
    if source == "legacy":
        data = FinancialReportsArtifactData(
            annual_statements=annual, model_type="annual_statements"
        ).model_dump(mode="json")
    if source == "invalid":
        data["statement_read"]["edition"]["annual_manifest_digest"] = "e" * 64
    envelope = build_artifact_envelope(
        kind="other" if source == "kind" else "financial_reports",
        produced_by="other" if source == "producer" else "fundamental_analysis",
        version="v0" if source == "version" else "v1",
        data=data,
    )
    artifacts = AsyncMock()
    artifacts.get_artifact_thread_id.return_value = "saved-thread"
    artifacts.belongs_to_organization.return_value = True
    artifacts.is_agent_output_reference.return_value = False
    artifacts.is_referenced_artifact_reference.return_value = False
    artifacts.get_artifact_envelope.return_value = envelope
    client = SimpleNamespace(
        read_annual_statements=AsyncMock(), read_fiscal_statements=AsyncMock()
    )
    reader = StatementReaderService(
        client=client,
        artifacts=artifacts,
        editions=(selected,),
        owns_thread=AsyncMock(return_value=True),
        claim_thread=AsyncMock(),
    )
    request = TypeAdapter(StatementReadIntentV2).validate_python(
        {
            "contract_version": "workspace.statement-reader.v2",
            "kind": "saved_artifact",
            "thread_id": "saved-thread",
            "artifact_id": "saved-artifact",
            "frequency": "ttm",
        }
    )
    with pytest.raises(FundamentalServiceFailure) as error:
        await reader.read(
            request, principal=principal(), correlation_id="legacy", deadline_at=limit()
        )
    assert error.value.code == "STATEMENT_SAVED_SELECTION_UNAVAILABLE"
    client.read_annual_statements.assert_not_awaited()
    client.read_fiscal_statements.assert_not_awaited()
    artifacts.save_thread_artifact.assert_not_awaited()


@pytest.mark.parametrize(
    "field,value",
    [
        ("edition_id", "caller-edition"),
        ("annual_manifest_digest", "a" * 64),
        ("fiscal_manifest_digest", "b" * 64),
        ("scope", {}),
        ("cutoff_at", "2000-01-01T00:00:00Z"),
    ],
)
def test_saved_intent_rejects_caller_selection_authority(field, value):
    with pytest.raises(ValidationError):
        TypeAdapter(StatementReadIntentV2).validate_python(
            {
                "contract_version": "workspace.statement-reader.v2",
                "kind": "saved_artifact",
                "thread_id": "saved-thread",
                "artifact_id": "saved-artifact",
                "frequency": "ttm",
                field: value,
            }
        )


@pytest.mark.parametrize("frequency", ["annual", "quarter", "ttm"])
@pytest.mark.parametrize(
    "field,value",
    [
        ("scope", "EUR"),
        ("cutoff_at", "2000-01-01T00:00:00Z"),
        ("manifest", "b" * 64),
    ],
)
def test_saved_wrapper_binds_complete_edition_to_its_actual_read(
    frequency, field, value
):
    selected = edition()
    if frequency == "annual":
        saved = StatementReadArtifactV3.from_annual(
            edition=selected, response=controlled_annual(selected)
        )
    else:
        expected = result(frequency)
        saved = StatementReadArtifactV3.from_fiscal(
            edition=selected,
            result=expected,
            request=FiscalReadRequestV2(
                manifest_digest=selected.fiscal_manifest_digest,
                scope=selected.scope,
                cutoff_at=selected.cutoff_at,
                frequency=frequency,
            ),
        )
    raw = saved.model_dump(mode="json")
    key = (
        (
            "annual_manifest_digest"
            if frequency == "annual"
            else "fiscal_manifest_digest"
        )
        if field == "manifest"
        else field
    )
    if field == "scope":
        raw["edition"]["scope"]["currency"] = value
    else:
        raw["edition"][key] = value
    with pytest.raises(ValidationError, match="saved edition"):
        StatementReadArtifactV3.model_validate(raw)


@pytest.mark.parametrize(
    "extra",
    [
        {"ticker": "OTHER"},
        {"company_name": "Other company"},
        {"annual_statements": "annual"},
        {"valuation_preview": {}},
        {"diagnostics": {}},
        {"model_type": "annual_statements"},
    ],
)
def test_saved_wrapper_has_one_display_and_standalone_payload_owner(extra):
    selected = edition()
    annual = controlled_annual(selected)
    values = {
        "statement_read": StatementReadArtifactV3.from_annual(
            edition=selected, response=annual
        ),
        "model_type": "statement_read",
        "status": "done",
    }
    if extra.get("annual_statements") == "annual":
        extra = {"annual_statements": annual}
    with pytest.raises(ValidationError):
        FinancialReportsArtifactData(**(values | extra))


@pytest.mark.parametrize(
    "field", ["manifest", "scope", "cutoff", "frequency", "digest"]
)
def test_fiscal_saved_read_binds_exact_request_and_full_result(field):
    value = result()
    raw = FiscalSavedReadV3(
        request=FiscalReadRequestV2(
            manifest_digest=value.binding.manifest_digest,
            scope=value.binding.scope,
            cutoff_at=value.binding.cutoff_at,
            frequency="quarter",
        ),
        result=value,
        result_digest=fiscal_digest(value),
    ).model_dump(mode="json")
    if field == "manifest":
        raw["request"]["manifest_digest"] = "b" * 64
    elif field == "scope":
        raw["request"]["scope"]["currency"] = "EUR"
    elif field == "cutoff":
        raw["request"]["cutoff_at"] = "2000-01-01T00:00:00Z"
    elif field == "frequency":
        raw["request"]["frequency"] = "ttm"
    else:
        raw["result_digest"] = "b" * 64
    with pytest.raises(ValidationError, match="exact read request"):
        FiscalSavedReadV3.model_validate(raw)


@pytest.mark.asyncio
async def test_current_reader_refuses_complete_result_digest_change():
    value = result()
    saved = FiscalSavedReadV3(
        request=FiscalReadRequestV2(
            manifest_digest=value.binding.manifest_digest,
            scope=value.binding.scope,
            cutoff_at=value.binding.cutoff_at,
            frequency="quarter",
        ),
        result=value,
        result_digest=fiscal_digest(value),
    )
    changed_wire = value.model_dump(mode="json")
    changed_wire["rows"][0]["row"]["label"] += " (current)"
    changed = FiscalReadResultV2.model_validate(changed_wire)
    client = SimpleNamespace(read_fiscal_statements=AsyncMock(return_value=changed))
    with pytest.raises(ArtifactCurrentReadFailure) as error:
        await FiscalArtifactCurrentReader(client).check_current(
            saved,
            principal=principal(),
            correlation_id="mismatch",
            deadline_at=limit(),
        )
    assert error.value.code == "STATEMENT_ARTIFACT_CURRENT_MISMATCH"


@pytest.mark.parametrize("frequency", ["quarter", "ttm"])
def test_v2_migration_fixture_preserves_financial_content_and_declares_synthetic_origin(
    frequency,
):
    origin = json.loads((FIXTURES / "fiscal-statements.origin.v2.json").read_text())
    assert origin["kind"] == "synthetic_contract_migration"
    adapted = json.loads(
        gzip.decompress(
            (FIXTURES / origin["responses"][frequency]["file"]).read_bytes()
        )
    )
    original = json.loads(
        gzip.decompress(
            (FIXTURES / f"fiscal-statements-{frequency}.v1.json.gz").read_bytes()
        )
    )
    parsed = FiscalReadResultV2.model_validate(adapted)
    assert fiscal_digest(parsed) == origin["responses"][frequency]["sha256"]
    assert adapted["rows"] == original["rows"]
    assert adapted["evidence"] == original["evidence"]
    for key in (
        "scope",
        "cutoff_at",
        "columns",
        "selected_period_set_digest",
        "projection_digest",
    ):
        assert adapted["binding"][key] == original["binding"][key]
