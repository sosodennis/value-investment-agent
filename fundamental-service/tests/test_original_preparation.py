"""Original bootstrap reuses validation while retaining every refusal."""

import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from fundamental_service.annual_discovery import AnnualDiscoveryRequestV1
from fundamental_service.annual_discovery_service import AnnualDiscovery
from fundamental_service.arelle_parser import ArelleParserError
from fundamental_service.operations import ServiceError
from fundamental_service.issuer_identity import DEFAULT_ORIGINAL_SECURITY_POLICY
from fundamental_service.original_preparation import (
    OriginalPreparation,
    OriginalPreparationRequestV1,
)
from fundamental_service.replay import ArtifactStore
from fundamental_service.sec_source import SecSourceError, _SecResponse
from fundamental_service.serialization import canonical_bytes
from fundamental_service.snapshots import SnapshotError
from test_annual_discovery_service import Locks, _inventory
from test_automatic_source_acquisition import acquisition_case
from test_automatic_source_mapping import source_case


def case(tmp_path, monkeypatch, *, multiple_originals=False):
    source, acquisition, state, metadata, artifacts = acquisition_case(
        tmp_path, monkeypatch
    )
    _, _, original, _, _ = source_case(tmp_path / "expected")
    delegate = acquisition.adapter._request

    def request(uri, *, deadline_at=None):
        response = delegate(uri, deadline_at=deadline_at)
        if "/submissions/" not in uri:
            return response
        payload = json.loads(response.content)
        rows = payload["filings"]["recent"]
        rows["reportDate"] = [
            original.original.report_period_end.isoformat() if form == "10-K" else ""
            for form in rows["form"]
        ]
        if multiple_originals:
            annual_index = rows["form"].index("10-K")
            older = {key: values[annual_index] for key, values in rows.items()}
            older["accessionNumber"] = "0000000001-26-999999"
            older["filingDate"] = (
                original.original.source.available_at.date() - timedelta(days=1)
            ).isoformat()
            older["acceptanceDateTime"] = (
                original.original.source.available_at - timedelta(days=1)
            ).isoformat()
            older["reportDate"] = (
                original.original.report_period_end - timedelta(days=365)
            ).isoformat()
            for key, values in rows.items():
                values.append(older[key])
        payload["tickers"] = ["UNTRUSTED-CURRENT-TICKER"]
        raw = canonical_bytes(payload)
        return _SecResponse(
            raw, 200, "application/json", response.available_at, (), len(raw)
        )

    monkeypatch.setattr(acquisition.adapter, "_request", request)
    locks = Locks()
    discovery = AnnualDiscovery(
        provider=acquisition.adapter,
        artifacts=artifacts,
        content=acquisition.content_store,
        capture_lock=locks,
    )
    annual_request = AnnualDiscoveryRequestV1(
        cik=source.cik,
        valuation_timestamp=source.valuation_timestamp,
        declared_source_revision=source.source_revision,
        original_count=2 if multiple_originals else 1,
        supported_filing_years=acquisition.settings.supported_filing_years,
    )
    deadline = datetime.now(UTC) + timedelta(minutes=5)
    annual, _ = discovery.execute(annual_request, deadline_at=deadline)
    assert not annual.selection.issue_codes
    service = OriginalPreparation(
        discovery=discovery,
        validator=acquisition,
        artifacts=artifacts,
        content=acquisition.content_store,
        capture_lock=locks,
    )
    prepared_request = OriginalPreparationRequestV1(
        annual=service.reference(
            annual.artifact_id, "sec-original-annual-discovery-v1"
        ),
        runtime=acquisition.original_validation_runtime(
            declared_source_revision=source.source_revision
        ),
    )
    return SimpleNamespace(
        service=service,
        request=prepared_request,
        acquisition=acquisition,
        state=state,
        metadata=metadata,
        artifacts=artifacts,
        discovery=discovery,
        expected_identity=source.identity,
        annual_request=annual_request,
        locks=locks,
        deadline=deadline,
    )


def execute(value, request=None):
    return value.service.execute(request or value.request, deadline_at=value.deadline)


def test_original_bootstrap_and_reopened_repeat_need_no_identity_snapshot_or_mapping(
    tmp_path, monkeypatch
):
    value = case(tmp_path, monkeypatch)
    result, receipt = execute(value)
    assert receipt.wrote and not result.issue_codes
    assert result.filings[0].identity == value.expected_identity
    validation = value.service.read_validation(result.filings[0].validation.artifact_id)
    assert (
        validation.original.status == "matched"
        and validation.integrity.quality_decision == "pass"
    )
    assert len(validation.responses) == 4 and value.state.parser_calls == 1
    assert (
        value.metadata.snapshots
        == value.metadata.mappings
        == value.metadata.acquisitions
        == {}
    )
    assert (
        value.acquisition.ingestion.builder.repository.find(
            identity=value.expected_identity,
            valuation_timestamp=value.annual_request.valuation_timestamp,
        )
        == ()
    )
    before, calls = _inventory(tmp_path), value.state.provider_calls

    def forbidden(*args, **kwargs):
        raise AssertionError("repeat contacted provider/parser")

    monkeypatch.setattr(value.acquisition.adapter, "_request", forbidden)
    monkeypatch.setattr("fundamental_service.ingestion.parse_filing_offline", forbidden)
    artifacts = ArtifactStore(tmp_path / "artifacts")
    reopened = OriginalPreparation(
        discovery=value.discovery,
        validator=value.acquisition,
        artifacts=artifacts,
        content=value.acquisition.content_store,
        capture_lock=value.locks,
    )
    again, repeated = reopened.execute(value.request, deadline_at=value.deadline)
    assert (
        again == result and repeated.artifact == receipt.artifact and not repeated.wrote
    )
    assert reopened.read(result.artifact_id) == result
    assert _inventory(tmp_path) == before and value.state.provider_calls == calls


def test_changed_security_selector_reuses_original_validation_and_retains_refusal(
    tmp_path, monkeypatch
):
    value = case(tmp_path, monkeypatch)
    result, _ = execute(value)
    calls = value.state.provider_calls, value.state.parser_calls
    wrong = value.request.model_copy(update={"ticker": "OTHER"})
    refused, publication = execute(value, wrong)
    assert publication.wrote and refused.issue_codes == (
        "HISTORICAL_IDENTITY_MISMATCH",
    )
    assert refused.filings[0].identity is None
    assert refused.filings[0].validation == result.filings[0].validation
    selected, _ = execute(
        value,
        value.request.model_copy(
            update={
                "ticker": value.expected_identity.security_id,
                "share_class": value.expected_identity.share_class,
            }
        ),
    )
    assert (
        not selected.issue_codes
        and selected.filings[0].identity == result.filings[0].identity
    )
    assert (value.state.provider_calls, value.state.parser_calls) == calls
    before = _inventory(tmp_path)
    _, repeat = execute(value, wrong)
    assert not repeat.wrote and _inventory(tmp_path) == before


def test_versioned_security_policy_reuses_validation_and_preserves_legacy_request(
    tmp_path, monkeypatch
):
    value = case(tmp_path, monkeypatch)
    old_bytes = canonical_bytes(value.request)
    assert "security_selection_policy" not in json.loads(old_bytes)
    original, _ = execute(value)
    calls = value.state.provider_calls, value.state.parser_calls
    request = value.request.model_copy(
        update={"security_selection_policy": DEFAULT_ORIGINAL_SECURITY_POLICY}
    )
    prepared, publication = execute(value, request)
    assert publication.wrote and not prepared.issue_codes
    assert request.digest != value.request.digest
    assert prepared.filings == original.filings
    assert (
        prepared.request.security_selection_policy == DEFAULT_ORIGINAL_SECURITY_POLICY
    )
    assert (value.state.provider_calls, value.state.parser_calls) == calls
    before = _inventory(tmp_path)
    repeated, receipt = execute(value, request)
    assert repeated == prepared and not receipt.wrote
    assert value.service.read(original.artifact_id) == original
    assert canonical_bytes(value.request) == old_bytes
    assert _inventory(tmp_path) == before


def test_concurrent_requests_publish_once_and_parse_once(tmp_path, monkeypatch):
    value = case(tmp_path, monkeypatch)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: execute(value), range(3)))
    assert len({e.digest for e, _ in results}) == 1
    assert sum(p.wrote for _, p in results) == 1 and value.state.parser_calls == 1
    assert value.state.provider_calls == 5


def test_interrupted_aggregate_publication_reuses_completed_validation(
    tmp_path, monkeypatch
):
    value = case(tmp_path, monkeypatch)
    delegate = value.artifacts.put_with_receipt
    interrupted = False

    def put(artifact_id, *args, **kwargs):
        nonlocal interrupted
        if artifact_id.startswith("original-preparation:") and not interrupted:
            interrupted = True
            raise OSError("simulated crash before atomic preparation publication")
        return delegate(artifact_id, *args, **kwargs)

    monkeypatch.setattr(value.artifacts, "put_with_receipt", put)
    with pytest.raises(OSError):
        execute(value)
    calls = value.state.provider_calls, value.state.parser_calls
    result, publication = execute(value)
    assert publication.wrote and not result.issue_codes
    assert (value.state.provider_calls, value.state.parser_calls) == calls
    _, repeated = execute(value)
    assert not repeated.wrote


def test_resource_retry_retains_attempt_and_captures_without_poisoning_cache(
    tmp_path, monkeypatch
):
    value = case(tmp_path, monkeypatch)
    from fundamental_service import ingestion

    delegate = ingestion.parse_filing_offline
    exhausted = True

    def parse(*args, **kwargs):
        nonlocal exhausted
        if exhausted:
            exhausted = False
            raise ArelleParserError(
                "PARSER_RESOURCE_EXHAUSTED", "temporary resource detail"
            )
        return delegate(*args, **kwargs)

    monkeypatch.setattr(ingestion, "parse_filing_offline", parse)
    attempt, first = execute(value)
    assert first.wrote and attempt.retryable
    assert attempt.issue_codes == ("PARSER_RESOURCE_EXHAUSTED",)
    validation = value.service.read_validation(
        attempt.filings[0].validation.artifact_id
    )
    assert len(validation.responses) == 4 and validation.retryable
    calls = value.state.provider_calls
    result, second = execute(value)
    assert second.wrote and not result.issue_codes and not result.retryable
    assert result.artifact_id != attempt.artifact_id
    assert value.state.provider_calls == calls
    assert value.service.read(attempt.artifact_id) == attempt
    assert value.service.read(result.artifact_id) == result
    before = _inventory(tmp_path)
    _, repeated = execute(value)
    assert not repeated.wrote and _inventory(tmp_path) == before


def test_regulatory_failure_is_retained_and_never_creates_snapshot(
    tmp_path, monkeypatch
):
    value = case(tmp_path, monkeypatch)
    value.state.mode = "no_regulatory_evidence"
    result, _ = execute(value)
    assert (
        result.issue_codes == ("VALIDATION_EVIDENCE_MISSING",) and not result.retryable
    )
    validation = value.service.read_validation(result.filings[0].validation.artifact_id)
    assert validation.original is None and validation.responses
    assert value.metadata.snapshots == value.metadata.mappings == {}
    before = _inventory(tmp_path)
    value.state.mode = "valid"
    _, repeated = execute(value)
    assert not repeated.wrote and _inventory(tmp_path) == before


def test_corrupt_original_refuses_without_download_or_reparse(tmp_path, monkeypatch):
    value = case(tmp_path, monkeypatch)
    result, _ = execute(value)
    validation = value.service.read_validation(result.filings[0].validation.artifact_id)
    source = validation.responses[0]
    value.acquisition.content_store._path(
        source.content_hash, source.media_type
    ).write_bytes(b"corrupt")
    calls = value.state.provider_calls, value.state.parser_calls
    with pytest.raises(SnapshotError):
        execute(value)
    assert (value.state.provider_calls, value.state.parser_calls) == calls


def test_original_failure_retains_other_selected_original(tmp_path, monkeypatch):
    value = case(tmp_path, monkeypatch, multiple_originals=True)
    delegate = value.acquisition.adapter._request

    def request(uri, *, deadline_at=None):
        if "/000000000126999999/" in uri:
            raise SecSourceError("SEC_HTTP_NOT_FOUND", "missing original")
        return delegate(uri, deadline_at=deadline_at)

    monkeypatch.setattr(value.acquisition.adapter, "_request", request)
    result, publication = execute(value)
    assert publication.wrote and len(result.filings) == 2
    assert result.issue_codes == ("SEC_HTTP_NOT_FOUND",)
    assert sum(f.identity is not None for f in result.filings) == 1
    validations = tuple(
        value.service.read_validation(f.validation.artifact_id) for f in result.filings
    )
    assert {v.request.filing.accession_number for v in validations} == {
        f.accession_number
        for f in value.discovery.read(
            value.request.annual.artifact_id
        ).selection.selected
    }
    assert {v.issue_codes for v in validations} == {(), ("SEC_HTTP_NOT_FOUND",)}
    before = _inventory(tmp_path)
    again, repeated = execute(value)
    assert again == result and not repeated.wrote and _inventory(tmp_path) == before


def test_corrupt_retained_receipt_refuses_without_replacement_io(tmp_path, monkeypatch):
    value = case(tmp_path, monkeypatch)
    result, _ = execute(value)
    validation = value.service.read_validation(result.filings[0].validation.artifact_id)
    from fundamental_service.sec_capture import sec_response_artifact_id

    receipt = validation.responses[0]
    receipt_id = sec_response_artifact_id(receipt.scope, receipt.uri)
    delegate = value.artifacts.read

    def read(artifact_id):
        return b"{}" if artifact_id == receipt_id else delegate(artifact_id)

    monkeypatch.setattr(value.artifacts, "read", read)
    calls = value.state.provider_calls, value.state.parser_calls
    with pytest.raises(SnapshotError) as raised:
        execute(value)
    assert raised.value.code == "ORIGINAL_PREPARATION_INVALID"
    assert (value.state.provider_calls, value.state.parser_calls) == calls


def test_runtime_catalog_mismatch_retains_annual_without_parsing(tmp_path, monkeypatch):
    value = case(tmp_path, monkeypatch)
    request = value.request.model_copy(
        update={
            "runtime": value.request.runtime.model_copy(
                update={"supported_filing_years": (2024,)}
            )
        }
    )
    result, _ = execute(value, request)
    assert result.issue_codes == ("ORIGINAL_RUNTIME_CATALOG_MISMATCH",)
    assert not result.filings and value.state.parser_calls == 0
    assert value.state.provider_calls == 1


def test_requested_taxonomy_cannot_override_service_runtime(tmp_path, monkeypatch):
    value = case(tmp_path, monkeypatch)
    request = value.request.model_copy(
        update={
            "runtime": value.request.runtime.model_copy(
                update={"taxonomy_cache_sha256": "f" * 64}
            )
        }
    )
    with pytest.raises(ServiceError) as raised:
        execute(value, request)
    assert raised.value.code == "ORIGINAL_VALIDATION_RUNTIME_MISMATCH"
    assert value.state.provider_calls == 1 and value.state.parser_calls == 0


def test_transport_budget_change_has_a_new_validation_identity(tmp_path, monkeypatch):
    value = case(tmp_path, monkeypatch)
    first, _ = execute(value)
    calls = value.state.provider_calls, value.state.parser_calls
    value.acquisition.adapter.policy = replace(
        value.acquisition.adapter.policy, max_submission_bytes=32_000_000
    )
    request = value.request.model_copy(
        update={
            "runtime": value.acquisition.original_validation_runtime(
                declared_source_revision=value.annual_request.declared_source_revision
            )
        }
    )
    assert request.digest != value.request.digest
    result, publication = execute(value, request)
    assert publication.wrote and not result.issue_codes
    assert first.filings[0].validation != result.filings[0].validation
    assert value.state.provider_calls == calls[0]
    assert value.state.parser_calls == calls[1] + 1
    assert value.service.read(first.artifact_id) == first


def test_existing_command_prepares_originals_and_retrieves_without_io(
    tmp_path, monkeypatch, capsys
):
    from fundamental_service import annual_discovery_runner, app

    value = case(tmp_path, monkeypatch)

    @asynccontextmanager
    async def lifespan(_):
        yield

    fake_app = SimpleNamespace(
        router=SimpleNamespace(lifespan_context=lifespan),
        state=SimpleNamespace(
            application=SimpleNamespace(
                ready=True,
                content_store=value.acquisition.content_store,
                artifact_store=value.artifacts,
            ),
            sec_acquisition=value.acquisition,
            metadata_store=value.metadata,
        ),
    )
    monkeypatch.setattr(app, "app", fake_app)
    monkeypatch.setattr(
        annual_discovery_runner, "PostgresPublicCaptureLock", lambda _: value.locks
    )
    args = [
        "--cik",
        value.annual_request.cik,
        "--valuation-timestamp",
        value.annual_request.valuation_timestamp.isoformat(),
        "--source-revision",
        value.annual_request.declared_source_revision,
        "--original-count",
        "1",
        "--prepare-originals",
    ]
    assert annual_discovery_runner.main(args) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["wrote"] and not first["evidence"]["issue_codes"]
    before, calls = _inventory(tmp_path), value.state.provider_calls
    assert annual_discovery_runner.main(args) == 0
    second = json.loads(capsys.readouterr().out)
    assert second == {**first, "wrote": False}
    assert (
        annual_discovery_runner.main(
            ["--artifact-id", first["artifact"]["artifact_id"]]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == second
    validation_id = first["evidence"]["filings"][0]["validation"]["artifact_id"]
    assert annual_discovery_runner.main(["--artifact-id", validation_id]) == 0
    validated = json.loads(capsys.readouterr().out)
    assert (
        not validated["wrote"] and validated["artifact"]["artifact_id"] == validation_id
    )
    assert validated["evidence"]["original"]["status"] == "matched"
    assert _inventory(tmp_path) == before and value.state.provider_calls == calls


@pytest.mark.parametrize(
    "extra",
    [
        ["--ticker", "EXAMPLE"],
        ["--share-class", "Common stock"],
        ["--validation-profile-id", "sec-efm-us-dqc-v31.0.3"],
        ["--prepare-originals", "--ticker", "invalid ticker"],
    ],
)
def test_invalid_security_selection_refuses_before_storage(monkeypatch, extra):
    from fundamental_service import annual_discovery_runner

    def forbidden(*args, **kwargs):
        raise AssertionError("invalid selectors opened storage")

    monkeypatch.setattr(annual_discovery_runner, "_run_command", forbidden)
    args = [
        "--cik",
        "0000000001",
        "--valuation-timestamp",
        "2026-01-01T00:00:00Z",
        "--source-revision",
        "a" * 40,
    ]
    if "--prepare-originals" in extra:
        assert annual_discovery_runner.main(args + extra) == 2
    else:
        with pytest.raises(SystemExit) as raised:
            annual_discovery_runner.main(args + extra)
        assert raised.value.code == 2
