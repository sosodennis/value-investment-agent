from __future__ import annotations

import copy
import hashlib
import json
from datetime import UTC, datetime

import pytest

from src.agents.fundamental.application.fundamental_service_port import (
    FundamentalServiceFailure,
)
from src.agents.fundamental.application.workflow_orchestrator.service_valuation_flow import (
    run_service_valuation_flow,
)
from src.agents.fundamental.application.workflow_orchestrator.services.service_request_producer import (
    prepare_service_valuation_request,
)
from src.agents.fundamental.infrastructure.valuation_revision_source_reader import (
    ArtifactFundamentalRevisionSourceReader,
)
from src.agents.fundamental.interface.fundamental_service_contracts import (
    FundamentalServiceResponseV1,
)
from src.agents.fundamental.interface.request_contracts import (
    FundamentalValuationIntentV1,
    FundamentalValuationRevisionSourceV1,
)
from src.analysis_runtime.application.execution_context import (
    WorkflowExecutionContext,
    reset_workflow_execution_context,
    set_workflow_execution_context,
)
from src.artifacts.domain.record import ArtifactRecord
from src.artifacts.public import ArtifactService, build_artifact_envelope
from src.shared.artifacts.artifact_data_models import FinancialReportsArtifactData
from src.shared.artifacts.fundamental_contracts import (
    FundamentalValuationPreparationResultV1,
    FundamentalValuationReportV1,
)
from src.shared.cross_agent.domain.market_identity import CompanyProfile
from src.shared.internal_services import (
    InternalPrincipal,
    reset_request_principal,
    set_request_principal,
)
from tests.agents.fundamental.test_fundamental_service_cutover import (
    _RELEASE_SELECTOR,
    _FactsOnlyClient,
    _Runtime,
)

_PRINCIPAL = InternalPrincipal(
    subject_id="caller-1", organization_id="org-1", membership_id="membership-1"
)
_NOW = datetime(2026, 11, 8, tzinfo=UTC)


class _RevisionClient(_FactsOnlyClient):
    def __init__(self):
        super().__init__(preparation_padding="retained-evidence" * 10000)
        self.stale = False
        self.bad_response = False
        self.ignored_revision = False

    async def prepare_valuation(self, input_payload, **kwargs):
        original = await super().prepare_valuation(input_payload, **kwargs)
        payload = original.model_dump(mode="json", exclude_unset=True)
        payload["input"]["assumptions"]["terminal_growth"] = "0.025"
        payload["assumptions_evidence"] = [
            {
                "path": "assumptions.terminal_growth",
                "value": payload["input"]["assumptions"]["terminal_growth"],
                "method": "approved_policy",
                "formula": "released policy",
                "policy_version": payload["policy_version"],
                "as_of": "2026-11-01T00:00:00Z",
                "editable": True,
            }
        ]
        payload.pop("preparation_digest")
        payload["preparation_digest"] = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if self.stale:
            payload["input"]["provenance"]["source_evidence"] = "changed"
        return FundamentalValuationPreparationResultV1.model_validate(payload)

    async def execute(self, operation, input_payload, **kwargs):
        if operation != "override_prepared_valuation":
            return await super().execute(operation, input_payload, **kwargs)
        self.calls.append((operation, copy.deepcopy(dict(input_payload))))
        payload = copy.deepcopy(input_payload["preparation"])
        if not self.ignored_revision:
            payload["input"]["assumptions"]["terminal_growth"] = input_payload["value"]
        payload["issue_codes"].append("MANUAL_OVERRIDE_APPLIED")
        if self.bad_response:
            payload["input"]["valuation_context"]["data_snapshot_id"] = "other"
        return FundamentalServiceResponseV1(
            contract_version="internal.v1",
            schema_version="fundamental.v1",
            correlation_id="revision-1",
            result=payload,
        )


@pytest.fixture
async def published_source():
    client = _RevisionClient()
    runtime = _Runtime()
    token = set_request_principal(_PRINCIPAL)
    try:
        await run_service_valuation_flow(
            runtime,
            _state({"model_id": "fcff_dcf"}),
            client=client,
            release_selector=_RELEASE_SELECTOR,
            clock=lambda: _NOW,
        )
    finally:
        reset_request_principal(token)
    raw = runtime.saved_calls[0]["data"]
    report = FinancialReportsArtifactData.model_validate(raw).fundamental_service
    assert isinstance(report, FundamentalValuationReportV1)
    client.calls.clear()
    return client, raw, report


def _state(request):
    return {
        "valuation_request": request,
        "company_profile": CompanyProfile(ticker="AAPL", name="Apple Inc."),
        "fundamental_analysis": {"model_type": "dcf_standard"},
    }


def _revision(report):
    return {
        "contract_version": "fundamental.v1",
        "revision": {
            "source": {
                "thread_id": "thread-1",
                "run_id": "source-run",
                "artifact_id": "source-artifact",
                "preparation_digest": report.automatic_preparation.preparation_digest,
            },
            "path": "assumptions.terminal_growth",
            "value": "0.02",
            "reason": "Reviewed the retained assumptions",
        },
    }


class _SourceReader:
    def __init__(self, report):
        self.report = report
        self.calls = []

    async def read_source(self, source, **kwargs):
        self.calls.append((source, kwargs))
        return self.report


async def _prepare(client, report, request=None, **kwargs):
    return await prepare_service_valuation_request(
        _state(request or _revision(report)),
        client=client,
        principal=_PRINCIPAL,
        correlation_id="revision-1",
        deadline_at=_NOW,
        revision_source_reader=_SourceReader(report),
        current_thread_id="thread-1",
        clock=lambda: _NOW,
        **kwargs,
    )


async def test_revision_recovers_complete_published_source_and_builds_wire_request(
    published_source,
):
    client, _, report = published_source
    result = await _prepare(client, report)
    assert [operation for operation, _ in client.calls] == [
        "resolve_identity",
        "prepare_valuation",
        "override_prepared_valuation",
    ]
    assert client.calls[1][1] == {
        "contract_version": "fundamental.v1",
        "snapshot_id": report.snapshot_id,
        "data_release_manifest_digest": report.hashes.data_release_manifest_digest,
        "model_id": report.automatic_preparation.model_id,
    }
    wire = client.calls[2][1]
    original = report.automatic_preparation.model_dump(mode="json", exclude_unset=True)
    assert wire["preparation"] == original
    assert len(wire["preparation"]["input"]["provenance"]["source_evidence"]) > 100000
    assert wire["provenance"] == {
        "author": _PRINCIPAL.subject_id,
        "modified_at": _NOW.isoformat(),
        "reason": "Reviewed the retained assumptions",
        "automatic_preparation_digest": original["preparation_digest"],
    }
    assert result.valuation_request["assumptions"]["terminal_growth"] == "0.02"
    assert (
        report.automatic_preparation.input["assumptions"]["terminal_growth"] != "0.02"
    )


@pytest.mark.parametrize("mutation", ["digest", "share_class", "policy", "partial"])
async def test_revision_refuses_unbound_or_partial_sources(published_source, mutation):
    client, raw, report = published_source
    request = _revision(report)
    raw = copy.deepcopy(raw)
    if mutation == "digest":
        request["revision"]["source"]["preparation_digest"] = "0" * 64
    elif mutation == "share_class":
        raw["fundamental_service"]["automatic_preparation"]["input"]["identity"][
            "share_class"
        ] = "other-class"
    elif mutation == "policy":
        request["policy_id"] = "different-policy"
    else:
        raw["fundamental_service"]["automatic_preparation"]["input"]["provenance"].pop(
            "source_evidence"
        )
    source = FinancialReportsArtifactData.model_validate(raw).fundamental_service
    with pytest.raises(FundamentalServiceFailure) as error:
        await _prepare(client, source, request)
    assert error.value.code in {
        "REVISION_SOURCE_BINDING_MISMATCH",
        "REVISION_SOURCE_STALE",
    }
    assert "override_prepared_valuation" not in [op for op, _ in client.calls]


@pytest.mark.parametrize("mutation", ["manual", "manual_provenance", "conditional_ref"])
async def test_manual_or_revised_source_is_read_only(published_source, mutation):
    client, raw, report = published_source
    raw = copy.deepcopy(raw)
    prep = raw["fundamental_service"]["automatic_preparation"]
    if mutation == "manual":
        prep["assumptions_evidence"][0]["method"] = "manual"
    elif mutation == "manual_provenance":
        prep["assumptions_evidence"][0]["manual_provenance"] = {
            "author": "caller-1",
            "modified_at": _NOW.isoformat(),
            "reason": "prior edit",
            "automatic_preparation_digest": prep["preparation_digest"],
        }
    else:
        raw["fundamental_service"]["valuation_input"]["provenance"][
            "conditional_revision_ref"
        ] = {"artifact_id": "conditional-revision-v1-" + "f" * 64}
    source = FinancialReportsArtifactData.model_validate(raw).fundamental_service
    with pytest.raises(FundamentalServiceFailure) as error:
        await _prepare(client, source, _revision(report))
    assert error.value.code == "REVISION_SOURCE_READ_ONLY"
    assert [op for op, _ in client.calls] == ["resolve_identity"]


async def test_changed_preparation_refuses_even_with_same_supplied_digest(
    published_source,
):
    client, _, report = published_source
    client.stale = True
    with pytest.raises(FundamentalServiceFailure) as error:
        await _prepare(client, report)
    assert error.value.code == "REVISION_SOURCE_STALE"
    assert [op for op, _ in client.calls] == ["resolve_identity", "prepare_valuation"]


async def test_override_service_cannot_change_source_snapshot(published_source):
    client, _, report = published_source
    client.bad_response = True
    with pytest.raises(FundamentalServiceFailure) as error:
        await _prepare(client, report)
    assert error.value.code == "UPSTREAM_MALFORMED"


async def test_override_service_must_return_the_requested_value(published_source):
    client, _, report = published_source
    client.ignored_revision = True
    with pytest.raises(FundamentalServiceFailure) as error:
        await _prepare(client, report)
    assert error.value.code == "UPSTREAM_MALFORMED"


async def test_supported_forward_reference_is_forwarded_without_reconstruction(
    published_source,
):
    client, _, report = published_source
    request = _revision(report)
    reference = {
        "claim_id": "claim-1",
        "source_url": "https://example.test/filing",
        "source_content_hash": "f" * 64,
        "citation": "A complete retained source citation for the reviewed assumption",
        "license_reference": "public-filing",
    }
    request["revision"]["forward_reference"] = reference
    await _prepare(client, report, request)
    assert client.calls[-1][1]["provenance"]["forward_reference"] == reference


async def test_source_failure_remains_typed_without_an_override_call(published_source):
    client, _, report = published_source

    class FailedSource:
        async def read_source(self, *_args, **_kwargs):
            raise FundamentalServiceFailure(
                "REVISION_SOURCE_NOT_FOUND",
                "unavailable",
                retryable=False,
                status_code=404,
            )

    with pytest.raises(FundamentalServiceFailure) as error:
        await prepare_service_valuation_request(
            _state(_revision(report)),
            client=client,
            principal=_PRINCIPAL,
            correlation_id="revision-1",
            deadline_at=_NOW,
            revision_source_reader=FailedSource(),
            current_thread_id="thread-1",
        )
    assert error.value.code == "REVISION_SOURCE_NOT_FOUND"
    assert [op for op, _ in client.calls] == ["resolve_identity"]


class _ArtifactRepository:
    def __init__(self, data):
        self.data = data
        self.thread_id = "thread-1"
        self.run_id = "source-run"
        self.artifact_id = "source-artifact"
        self.organization_id = "org-1"
        self.referenced = True
        self.content_reads = 0

    async def get_run_thread_id(self, *, run_id, organization_id):
        return (
            self.thread_id
            if (run_id, organization_id) == (self.run_id, self.organization_id)
            else None
        )

    async def get_thread_id(self, artifact_id):
        return self.thread_id if artifact_id == self.artifact_id else None

    async def is_referenced_artifact_for_run(self, **_kwargs):
        return self.referenced

    async def get_by_id(self, artifact_id):
        self.content_reads += 1
        if self.data is None:
            return None
        return ArtifactRecord(
            artifact_id=artifact_id,
            key=None,
            thread_id=self.thread_id,
            kind="financial_reports",
            envelope=build_artifact_envelope(
                kind="financial_reports", produced_by="fundamental", data=self.data
            ),
            dedupe_key=None,
        )


async def test_authenticated_revision_publishes_in_same_run_context(published_source):
    client, raw, report = published_source
    repository = _ArtifactRepository(raw)
    checked_owners = []

    async def owns_thread(subject_id, thread_id):
        checked_owners.append((subject_id, thread_id))
        return True

    reader = ArtifactFundamentalRevisionSourceReader(
        artifacts=ArtifactService(repository), owns_thread=owns_thread
    )
    runtime = _Runtime()
    auth = set_request_principal(_PRINCIPAL)
    context = set_workflow_execution_context(
        WorkflowExecutionContext(
            thread_id="thread-1",
            run_id="new-revision-run",
            principal_id=_PRINCIPAL.subject_id,
            organization_id=_PRINCIPAL.organization_id,
            membership_id=_PRINCIPAL.membership_id,
        )
    )
    try:
        result = await run_service_valuation_flow(
            runtime,
            _state(_revision(report)),
            client=client,
            revision_source_reader=reader,
            clock=lambda: _NOW,
        )
    finally:
        reset_workflow_execution_context(context)
        reset_request_principal(auth)
    assert checked_owners == [(_PRINCIPAL.subject_id, "thread-1")]
    assert result.update["fundamental_analysis"]["valuation_status"] == "completed"
    assert (
        result.update["fundamental_analysis"]["request_timing"]["valuation_timestamp"]
        == "2026-11-01T00:00:00Z"
    )
    published = FinancialReportsArtifactData.model_validate(
        runtime.saved_calls[0]["data"]
    ).fundamental_service
    assert isinstance(published, FundamentalValuationReportV1)
    assert published.snapshot_id == report.snapshot_id
    assert (
        published.automatic_preparation.input["assumptions"]["terminal_growth"]
        == "0.02"
    )
    assert "MANUAL_OVERRIDE_APPLIED" in published.automatic_preparation.issue_codes
    assert [op for op, _ in client.calls] == [
        "resolve_identity",
        "prepare_valuation",
        "override_prepared_valuation",
        "validate_with_policy",
        "calculate",
        "read_valuation_evidence",
    ]


@pytest.mark.parametrize(
    "scope", [None, "different-subject", "different-org", "different-membership"]
)
async def test_revision_requires_matching_authenticated_execution_context(
    published_source, scope
):
    client, _, report = published_source
    reader = _SourceReader(report)
    runtime = _Runtime()
    auth = set_request_principal(_PRINCIPAL)
    context = None
    if scope is not None:
        context = set_workflow_execution_context(
            WorkflowExecutionContext(
                thread_id="thread-1",
                run_id="new-revision-run",
                principal_id="other"
                if scope == "different-subject"
                else _PRINCIPAL.subject_id,
                organization_id="other"
                if scope == "different-org"
                else _PRINCIPAL.organization_id,
                membership_id="other"
                if scope == "different-membership"
                else _PRINCIPAL.membership_id,
            )
        )
    try:
        result = await run_service_valuation_flow(
            runtime,
            _state(_revision(report)),
            client=client,
            revision_source_reader=reader,
            clock=lambda: _NOW,
        )
    finally:
        if context is not None:
            reset_workflow_execution_context(context)
        reset_request_principal(auth)
    assert reader.calls == []
    assert (
        result.update["fundamental_analysis"]["service_failure"]["code"]
        == "REVISION_SOURCE_UNAVAILABLE"
    )
    assert "override_prepared_valuation" not in [op for op, _ in client.calls]


@pytest.mark.parametrize(
    "mutation",
    [
        "thread",
        "run",
        "artifact",
        "organization",
        "owner",
        "reference",
        "missing",
        "truncated",
    ],
)
async def test_reader_enforces_owner_run_artifact_and_complete_content(
    published_source, mutation
):
    _, raw, report = published_source
    repository = _ArtifactRepository(copy.deepcopy(raw))
    owns = True
    source = _revision(report)["revision"]["source"]
    if mutation in {"thread", "run", "artifact"}:
        source[mutation + "_id"] = "unrelated"
    elif mutation == "organization":
        repository.organization_id = "different-org"
    elif mutation == "owner":
        owns = False
    elif mutation == "reference":
        repository.referenced = False
    elif mutation == "missing":
        repository.data = None
    else:
        repository.data["fundamental_service"].pop("valuation_input")

    async def owns_thread(subject_id, thread_id):
        assert subject_id == _PRINCIPAL.subject_id
        assert thread_id == "thread-1"
        return owns

    reader = ArtifactFundamentalRevisionSourceReader(
        artifacts=ArtifactService(repository), owns_thread=owns_thread
    )
    with pytest.raises(FundamentalServiceFailure) as error:
        await reader.read_source(
            FundamentalValuationRevisionSourceV1.model_validate(source),
            principal=_PRINCIPAL,
            current_thread_id="thread-1",
        )
    assert error.value.code == (
        "REVISION_SOURCE_INVALID"
        if mutation == "truncated"
        else "REVISION_SOURCE_NOT_FOUND"
    )
    assert repository.content_reads == (
        1 if mutation in {"missing", "truncated"} else 0
    )


async def test_source_storage_failure_has_a_typed_retryable_outcome(published_source):
    _, raw, report = published_source

    class UnavailableRepository(_ArtifactRepository):
        async def get_run_thread_id(self, **_kwargs):
            raise RuntimeError("database unavailable")

    async def owns_thread(_subject_id, _thread_id):
        return True

    reader = ArtifactFundamentalRevisionSourceReader(
        artifacts=ArtifactService(UnavailableRepository(raw)), owns_thread=owns_thread
    )
    with pytest.raises(FundamentalServiceFailure) as error:
        await reader.read_source(
            FundamentalValuationRevisionSourceV1.model_validate(
                _revision(report)["revision"]["source"]
            ),
            principal=_PRINCIPAL,
            current_thread_id="thread-1",
        )
    assert error.value.code == "REVISION_SOURCE_UNAVAILABLE"
    assert error.value.retryable is True


@pytest.mark.parametrize("value", [0.02, 2, True, "NaN", "Infinity", "invalid"])
def test_revision_value_requires_finite_decimal_text(value):
    request = {
        "revision": {
            "source": {
                "thread_id": "t",
                "run_id": "r",
                "artifact_id": "a",
                "preparation_digest": "f" * 64,
            },
            "path": "assumptions.terminal_growth",
            "value": value,
            "reason": "reviewed",
        }
    }
    with pytest.raises(ValueError):
        FundamentalValuationIntentV1.model_validate(request)


@pytest.mark.parametrize(
    "mutation",
    ["path", "blank_reason", "author", "preparation", "uncertainty", "source_extra"],
)
async def test_revision_rejects_browser_authority_and_conflicting_controls(
    published_source, mutation
):
    _, _, report = published_source
    request = _revision(report)
    if mutation == "path":
        request["revision"]["path"] = "assumptions.capital_bridge.cash"
    elif mutation == "blank_reason":
        request["revision"]["reason"] = "   "
    elif mutation == "author":
        request["revision"]["author"] = "different-subject"
    elif mutation == "preparation":
        request["revision"]["preparation"] = {"input": {}}
    elif mutation == "uncertainty":
        request["uncertainty"] = {"mode": "monte_carlo", "samples": 10}
    else:
        request["revision"]["source"]["subject_id"] = "different-subject"
    with pytest.raises(ValueError):
        FundamentalValuationIntentV1.model_validate(request)
