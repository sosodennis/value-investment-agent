from dataclasses import replace
from datetime import timedelta
import pytest

from test_automatic_source_acquisition import acquire
from test_automatic_source_mapping import statement_source_case
from test_original_preparation import case, execute
from fundamental_service.statement_release_builder import build_statement_release
from types import SimpleNamespace


def test_prepared_original_identity_survives_later_submissions_capture(
    tmp_path, monkeypatch
):
    value = case(tmp_path / "source", monkeypatch, statement_original=True)
    delegate = value.acquisition.adapter._request

    def independent_capture_times(uri, *, deadline_at=None):
        response = delegate(uri, deadline_at=deadline_at)
        offset = 600 if "/submissions/" in uri else 0
        return replace(
            response, available_at=response.available_at + timedelta(seconds=offset)
        )

    monkeypatch.setattr(
        value.acquisition.adapter, "_request", independent_capture_times
    )
    prepared, _ = execute(value)
    validation = value.service.read_validation(
        prepared.filings[0].validation.artifact_id
    )
    parser_calls = value.state.parser_calls
    original_ref = value.service.reference(
        prepared.artifact_id, "sec-original-preparation-v1"
    )
    request, *_ = statement_source_case(tmp_path / "request", monkeypatch)

    def forbid_primary(uri, *, deadline_at=None):
        assert "/submissions/" in uri, (
            "prepared acquisition recaptured primary evidence"
        )
        return independent_capture_times(uri, deadline_at=deadline_at)

    def forbid_parser(*args, **kwargs):
        raise AssertionError("prepared acquisition parsed or reevaluated the original")

    monkeypatch.setattr(value.acquisition.adapter, "_request", forbid_primary)
    monkeypatch.setattr(
        "fundamental_service.ingestion.parse_filing_offline", forbid_parser
    )
    monkeypatch.setattr(
        "fundamental_service.ingestion.evaluate_original_issuer", forbid_parser
    )
    request = request.model_copy(update={"original_preparation": original_ref})
    ingestion = acquire(request, value.acquisition)
    assert value.state.parser_calls == parser_calls
    snapshot = value.metadata.snapshots[ingestion.snapshot_id]
    assert snapshot.captured_at > validation.original.source.captured_at
    assert snapshot.sec_integrity_evidence == validation.integrity
    for retained in validation.captured_sources:
        record = next(
            item for item in snapshot.source_records if item.uri == retained.uri
        )
        assert record.content_hash == retained.content_hash
        assert record.available_at == retained.available_at
        assert record.captured_at == retained.captured_at
        assert record.publication_at == retained.publication_at
        assert record.filing_date == (
            validation.request.filing.filing_date
            if retained.source_id == "sec-filing-submission"
            else None
        )
    build_statement_release(
        original_ref,
        (ingestion,),
        originals=value.service,
        snapshots=SimpleNamespace(get=lambda key: value.metadata.snapshots[key]),
        facts=SimpleNamespace(get=lambda key: value.metadata.facts[key]),
        mappings=SimpleNamespace(get_mapping=lambda key: value.metadata.mappings[key]),
        artifacts=value.artifacts,
        source_revision=request.source_revision,
        mapping_version=request.mapping_version,
    )


@pytest.mark.parametrize("cross_midnight", (False, True))
def test_current_cutoff_preserves_original_selection_on_acquisition_and_replay(
    tmp_path, monkeypatch, cross_midnight
):
    from fundamental_service.current_preparation import (
        CurrentSourcePreparation,
        CurrentSourcePreparationRequestV1,
    )
    from fundamental_service.preparation_runner import SourcePreparationRunner
    from fundamental_service.source_plan_contracts import (
        AutomaticSourcePreparationPlanV1,
    )
    from test_automatic_source_mapping import source_case
    from test_public_acquisition import (
        Provider,
        acquisition,
        file_lock,
        request as public_request,
    )

    value = case(tmp_path / "source", monkeypatch)
    request, *_ = source_case(tmp_path / "request")
    preparation_request = value.request
    if cross_midnight:
        requested_at = request.valuation_timestamp.replace(hour=23, minute=55)
        annual, _ = value.discovery.execute(
            value.annual_request.model_copy(
                update={"valuation_timestamp": requested_at}
            ),
            deadline_at=value.deadline,
        )
        preparation_request = value.request.model_copy(
            update={
                "annual": value.service.reference(
                    annual.artifact_id, "sec-original-annual-discovery-v1"
                )
            }
        )
        filing_date = annual.selection.selected[0].filing_date
        lookback = (requested_at.date() - filing_date).days
        request = request.model_copy(
            update={
                "valuation_timestamp": requested_at,
                "filing": request.filing.model_copy(update={"lookback_days": lookback}),
            }
        )
    prepared, _ = execute(value, preparation_request)
    original_ref = value.service.reference(
        prepared.artifact_id, "sec-original-preparation-v1"
    )
    request = request.model_copy(update={"original_preparation": original_ref})
    requested_at = request.valuation_timestamp
    if cross_midnight:
        assert acquire(request, value.acquisition).snapshot_id is not None
    effective_at = requested_at + timedelta(seconds=600)
    provider = Provider()
    provider.source = replace(
        provider.source, captured_at=effective_at, available_at=effective_at
    )
    public = acquisition(tmp_path / "public", provider, artifacts=value.artifacts)
    public._content = value.acquisition.content_store
    template = AutomaticSourcePreparationPlanV1(
        source_revision=request.source_revision,
        release_profile_id="current-original-regression",
        model_id=request.model_id,
        ingestions=(request,),
        public_sources=(public_request(valuation_timestamp=requested_at),),
    )
    selector = CurrentSourcePreparation(
        acquisitions=public,
        artifacts=value.artifacts,
        selection_lock=lambda key: file_lock(tmp_path / "selection", key),
        clock=lambda: effective_at + timedelta(seconds=1),
    )
    selected, _ = selector.execute(
        CurrentSourcePreparationRequestV1(template=template), deadline_at=value.deadline
    )
    assert selected.plan is not None, selected.issue_codes
    plan = selected.plan
    frozen = plan.ingestions[0]
    assert frozen.public_source_cutoff.requested_at == requested_at
    assert frozen.valuation_timestamp == effective_at
    first = acquire(frozen, value.acquisition)
    assert first.snapshot_id is not None
    snapshot = value.metadata.snapshots[first.snapshot_id]
    assert snapshot.valuation_timestamp == effective_at
    validation = value.service.read_validation(
        prepared.filings[0].validation.artifact_id
    )
    assert validation.original.decision_at == requested_at

    from fundamental_service.operations import ServiceError

    def missing_release(_request):
        raise ServiceError(
            "SNAPSHOT_NOT_FOUND",
            "no activated release",
            status_code=404,
            retryable=False,
        )

    def incomplete_valuation(*args, **kwargs):
        pytest.fail("an incomplete original cannot authorize valuation")

    runner = SourcePreparationRunner(
        application=SimpleNamespace(
            snapshot=lambda key: value.metadata.snapshots[key],
            artifact_store=value.artifacts,
            resolve_snapshot=missing_release,
            fact_repository=SimpleNamespace(get=value.metadata.facts.__getitem__),
            prepare_valuation=incomplete_valuation,
            calculate_valuation=incomplete_valuation,
        ),
        metadata=value.metadata,
        acquisition=value.acquisition,
        artifacts=value.artifacts,
        canary=None,
        public_acquisition=public,
    )
    groups = runner._plan_mappings(plan)
    assert groups and groups[0]
    from fundamental_service.automatic_data_release import AutomaticDataReleasePolicyV1
    from fundamental_service.data_releases import ArtifactRefV1
    from fundamental_service.preparation_release import assemble_preparation_release

    batch = value.artifacts.get(first.mapping_evidence_ref)
    release = assemble_preparation_release(
        plan=plan,
        snapshot=snapshot,
        facts=tuple(value.metadata.facts[key] for key in first.canonical_fact_ids),
        mappings=tuple(
            value.metadata.mappings[ref.decision_id]
            for group in groups
            for ref in group
        ),
        batch_refs=(
            ArtifactRefV1(
                artifact_id=batch.artifact_id,
                content_hash=batch.content_hash,
                media_type=batch.media_type,
                role="automatic-mapping-batch-decision-v1",
            ),
        ),
        artifacts=value.artifacts,
        policy=AutomaticDataReleasePolicyV1(
            profile_id=plan.release_profile_id,
            scope="security",
            model_id=plan.model_id,
            model_version=frozen.model_version,
            mapping_version=frozen.mapping_version,
            requirements_profile_digest=plan.requirements_profile.digest,
            parser_version=snapshot.parser_version,
            quality_profile_digest="1" * 64,
            validation_profile_digest=snapshot.validation_profile_digest,
            verifier_id="synthetic-machine",
            workflow_identity="synthetic/automatic",
        ),
        working_capital_policy=None,
        conditional_capital_policy=None,
        prepared_refs=(),
    )
    assert release.source_plan == plan
    from fundamental_service.automatic_release_evidence import (
        require_automatic_release_sources,
    )
    from fundamental_service.automatic_data_release import AutomaticDataReleaseRequestV1
    from fundamental_service.preparation_release import (
        read_preparation_release_artifact,
    )

    assert require_automatic_release_sources(
        release.manifest,
        release.content,
        snapshots=SimpleNamespace(get=lambda key: value.metadata.snapshots[key]),
        mappings=SimpleNamespace(get_mapping=value.metadata.mappings.__getitem__),
        artifacts=value.artifacts,
        validation_profile_digest=snapshot.validation_profile_digest,
    )
    published = value.artifacts.put_with_receipt(
        "synthetic-current-assembled-release-" + release.manifest.manifest_digest,
        release,
    )
    released = read_preparation_release_artifact(
        value.artifacts,
        ArtifactRefV1(
            artifact_id=published.artifact.artifact_id,
            content_hash=published.artifact.content_hash,
            media_type=published.artifact.media_type,
            role="automatic-preparation-release-v1",
        ),
        AutomaticDataReleaseRequestV1,
    )
    assert released == release
    again = acquire(frozen, value.acquisition)
    assert again.status == "reused" and again.snapshot_id == first.snapshot_id
    assert runner._plan_mappings(plan) == groups
    assert value.acquisition._original_reads.get() is None

    from fundamental_service.preparation_runner import SourcePreparationEvidenceV1

    def prepare_current():
        return runner.run(
            plan,
            actor_id="caller",
            organization_id="org",
            correlation_id="current-original-regression",
            deadline_at=value.deadline,
            prepare_only=True,
        )

    receipt = prepare_current()
    report = SourcePreparationEvidenceV1.model_validate_json(
        value.artifacts.read(receipt.artifact.artifact_id)
    )
    assert report.public_source_cutoff == plan.public_source_cutoff
    assert report.status == "blocked"
    assert report.preparation is report.calculation is None
    assert "non_operating_assets" in report.source_outcomes[0].missing_evidence
    calls = value.state.provider_calls, value.state.parser_calls
    replay = prepare_current()
    assert not replay.wrote and replay.artifact == receipt.artifact
    assert (value.state.provider_calls, value.state.parser_calls) == calls

    from pydantic import ValidationError

    cutoff = frozen.public_source_cutoff
    with pytest.raises(ValidationError):
        type(cutoff).model_validate(
            cutoff.model_dump() | {"requested_at": requested_at + timedelta(seconds=1)}
        )
    with pytest.raises(ValidationError):
        type(frozen).model_validate(
            frozen.model_dump()
            | {"valuation_timestamp": effective_at + timedelta(seconds=1)}
        )
    capture = cutoff.captures[0]
    changed_cutoff = cutoff.model_copy(
        update={
            "captures": (
                capture.model_copy(update={"media_type": "application/changed"}),
            )
        }
    )
    changed = type(frozen).model_validate(
        frozen.model_dump() | {"public_source_cutoff": changed_cutoff.model_dump()}
    )
    calls = value.state.provider_calls, value.state.parser_calls
    with pytest.raises(ServiceError) as error:
        acquire(changed, value.acquisition)
    assert error.value.code == "CURRENT_CAPTURE_MISMATCH"
    changed = frozen.model_copy(
        update={
            "original_preparation": original_ref.model_copy(
                update={"content_hash": "0" * 64}
            )
        }
    )
    with pytest.raises(ServiceError) as error:
        acquire(changed, value.acquisition)
    assert error.value.code == "ORIGINAL_PREPARATION_INVALID"
    assert (value.state.provider_calls, value.state.parser_calls) == calls
    assert len(value.metadata.acquisitions) == (2 if cross_midnight else 1)


def _prepared_case(tmp_path, monkeypatch):
    value = case(tmp_path / "source", monkeypatch, statement_original=True)
    prepared, _ = execute(value)
    request, *_ = statement_source_case(tmp_path / "request", monkeypatch)
    request = request.model_copy(
        update={
            "original_preparation": value.service.reference(
                prepared.artifact_id, "sec-original-preparation-v1"
            )
        }
    )
    validation = value.service.read_validation(
        prepared.filings[0].validation.artifact_id
    )
    return value, prepared, request, validation


def _corrupt_retained(value, prepared, validation, target, monkeypatch):
    from fundamental_service.sec_capture import sec_response_artifact_id

    if target == "source_bytes":
        source = next(
            s for s in validation.captured_sources if s.source_id == "sec-filing"
        )
        value.acquisition.content_store._path(
            source.content_hash, source.media_type
        ).write_bytes(b"changed")
    elif target == "receipt_bytes":
        response = validation.responses[0]
        key = sec_response_artifact_id(response.scope, response.uri)
        record = value.artifacts.get(key)
        value.artifacts._artifact_path(
            record.content_hash, record.media_type
        ).write_bytes(b"{}")
    elif target == "receipt_metadata":
        response = validation.responses[0]
        value.artifacts.invalidate(
            sec_response_artifact_id(response.scope, response.uri)
        )
    elif target == "membership":
        get = value.artifacts.get

        def changed_membership(key):
            record = get(key)
            return (
                record.model_copy(update={"dependency_hashes": ()})
                if key == prepared.artifact_id
                else record
            )

        monkeypatch.setattr(value.artifacts, "get", changed_membership)
    elif target == "validation_metadata":
        value.artifacts.invalidate(prepared.filings[0].validation.artifact_id)
    else:
        raise AssertionError(target)


@pytest.mark.parametrize("scoped", (False, True))
@pytest.mark.parametrize(
    "target",
    (
        "source_bytes",
        "receipt_bytes",
        "receipt_metadata",
        "membership",
        "validation_metadata",
    ),
)
def test_prepared_mutation_before_publication_refuses_without_snapshot_or_facts(
    tmp_path, monkeypatch, target, scoped
):
    from contextlib import nullcontext
    from fundamental_service.operations import ServiceError

    value, prepared, request, validation = _prepared_case(tmp_path, monkeypatch)
    prepare = value.acquisition.ingestion.prepare_original
    consumed = []

    def corrupt_after_materialization(**kwargs):
        result = prepare(**kwargs)
        consumed.append(value.acquisition._original_reads.get())
        _corrupt_retained(value, prepared, validation, target, monkeypatch)
        return result

    monkeypatch.setattr(
        value.acquisition.ingestion, "prepare_original", corrupt_after_materialization
    )
    with pytest.raises(ServiceError):
        with value.acquisition.evidence_operation() if scoped else nullcontext():
            acquire(request, value.acquisition)
    assert consumed and consumed[0].closed and consumed[0]._journal.closed
    assert value.acquisition._original_reads.get() is None
    assert (
        not value.metadata.snapshots
        and not value.metadata.facts
        and not value.metadata.acquisitions
    )
    calls = value.state.provider_calls, value.state.parser_calls
    with pytest.raises(ServiceError):
        acquire(request, value.acquisition)
    assert (value.state.provider_calls, value.state.parser_calls) == calls


@pytest.mark.parametrize("reader", ("execute", "retained"))
@pytest.mark.parametrize(
    "target",
    (
        "source_bytes",
        "receipt_bytes",
        "receipt_metadata",
        "membership",
        "validation_metadata",
    ),
)
def test_cached_prepared_acquisition_rechecks_admitted_evidence_before_return(
    tmp_path, monkeypatch, target, reader
):
    from fundamental_service.operations import ServiceError
    from fundamental_service.snapshots import SnapshotError
    from test_issuer_operating_release import inventory

    value, prepared, request, validation = _prepared_case(tmp_path, monkeypatch)
    result = acquire(request, value.acquisition)
    before = inventory(value.artifacts.root)
    get = value.metadata.get_sec_ingestion
    consumed = []

    def corrupt_after_admission(*args, **kwargs):
        result = get(*args, **kwargs)
        consumed.append(value.acquisition._original_reads.get())
        _corrupt_retained(value, prepared, validation, target, monkeypatch)
        return result

    monkeypatch.setattr(value.metadata, "get_sec_ingestion", corrupt_after_admission)
    calls = value.state.provider_calls, value.state.parser_calls
    with pytest.raises((ServiceError, SnapshotError)):
        if reader == "execute":
            acquire(request, value.acquisition)
        else:
            value.acquisition.retained_acquisition(request)
    assert consumed and consumed[0].closed and consumed[0]._journal.closed
    assert value.acquisition._original_reads.get() is None
    assert (value.state.provider_calls, value.state.parser_calls) == calls
    assert tuple(value.metadata.acquisitions.values()) == (result,)
    if target in {"source_bytes", "membership"}:
        assert inventory(value.artifacts.root) == before


@pytest.mark.parametrize("scoped", (False, True))
@pytest.mark.parametrize("reader", ("publish", "execute", "retained"))
def test_prepared_build_drift_refuses_at_publication_and_cached_read_boundaries(
    tmp_path, monkeypatch, reader, scoped
):
    from contextlib import nullcontext
    import fundamental_service.parser_action_identity as identity

    configuration = ["original image"]
    monkeypatch.setattr(
        identity, "_immutable_build_configuration", lambda: (configuration[0], ())
    )
    monkeypatch.setattr(identity, "_runtime_identity", lambda **kwargs: "2" * 64)
    value, _, request, _ = _prepared_case(tmp_path, monkeypatch)
    consumed = []
    if reader == "publish":
        prepare = value.acquisition.ingestion.prepare_original

        def drift_after_materialization(**kwargs):
            result = prepare(**kwargs)
            scope = value.acquisition._original_reads.get()
            scope.builds.current()
            consumed.append(scope)
            configuration[0] = "changed image"
            return result

        monkeypatch.setattr(
            value.acquisition.ingestion, "prepare_original", drift_after_materialization
        )
    else:
        acquire(request, value.acquisition)
        get = value.metadata.get_sec_ingestion

        def drift_after_admission(*args, **kwargs):
            result = get(*args, **kwargs)
            scope = value.acquisition._original_reads.get()
            scope.builds.current()
            consumed.append(scope)
            configuration[0] = "changed image"
            return result

        monkeypatch.setattr(value.metadata, "get_sec_ingestion", drift_after_admission)
    with pytest.raises(identity.IncompleteParserClosure, match="configuration changed"):
        with value.acquisition.evidence_operation() if scoped else nullcontext():
            if reader == "retained":
                value.acquisition.retained_acquisition(request)
            else:
                acquire(request, value.acquisition)
    assert consumed and consumed[0].closed and consumed[0]._journal.closed
    assert value.acquisition._original_reads.get() is None
    if reader == "publish":
        assert (
            not value.metadata.snapshots
            and not value.metadata.facts
            and not value.metadata.acquisitions
        )


def test_reconstructed_clock_cannot_replace_the_exact_prepared_original(
    tmp_path, monkeypatch
):
    from fundamental_service.automatic_mapping_batch import (
        StatementMappingBatchDecisionV1,
        StatementMappingBatchRequestV1,
    )
    from fundamental_service.data_releases import DataReleaseError
    from fundamental_service.mapping_input_identity import MappingInputDigests
    from fundamental_service.mapping_input_storage import (
        publish_mapping_input,
        read_mapping_batch_input,
    )
    from fundamental_service.operations import ServiceError
    from fundamental_service.original_issuer import evaluate_original_issuer
    from test_issuer_operating_release import inventory

    value, _, request, _ = _prepared_case(tmp_path, monkeypatch)
    result = acquire(request, value.acquisition)
    batch = StatementMappingBatchDecisionV1.model_validate_json(
        value.artifacts.read(result.mapping_evidence_ref)
    )
    _, batch_input = read_mapping_batch_input(
        batch.input_digest, StatementMappingBatchRequestV1, artifacts=value.artifacts
    )
    rebuilt = evaluate_original_issuer(
        batch_input.original.report,
        source=batch_input.original.source.model_copy(
            update={
                "captured_at": batch_input.original.source.captured_at
                + timedelta(seconds=1)
            }
        ),
        decision_at=batch_input.original.decision_at,
    )
    assert rebuilt.report.facts == batch_input.original.report.facts
    assert rebuilt.report.parsed_at != batch_input.original.report.parsed_at
    changed = batch_input.model_copy(
        update={
            "original": rebuilt,
            "integrity": batch_input.integrity.model_copy(
                update={"captured_at": rebuilt.source.captured_at}
            ),
        }
    )
    publish_mapping_input(
        changed,
        rebuilt,
        artifacts=value.artifacts,
        evidence_refs=changed.evidence_refs,
        batch=True,
    )
    digest = MappingInputDigests().input_digest(changed)
    record = value.artifacts.put(
        "synthetic-reconstructed-clock-" + digest,
        batch.model_copy(update={"input_digest": digest}),
    )
    substituted = result.model_copy(update={"mapping_evidence_ref": record.artifact_id})
    with pytest.raises(DataReleaseError) as error:
        build_statement_release(
            request.original_preparation,
            (substituted,),
            originals=value.service,
            snapshots=SimpleNamespace(get=lambda key: value.metadata.snapshots[key]),
            facts=SimpleNamespace(get=lambda key: value.metadata.facts[key]),
            mappings=SimpleNamespace(
                get_mapping=lambda key: value.metadata.mappings[key]
            ),
            artifacts=value.artifacts,
            source_revision=request.source_revision,
            mapping_version=request.mapping_version,
        )
    assert error.value.code == "STATEMENT_RELEASE_MAPPING_CONTEXT_MISMATCH"
    key = next(iter(value.metadata.acquisitions))
    value.metadata.acquisitions[key] = substituted
    before = inventory(value.artifacts.root)
    with pytest.raises(ServiceError) as error:
        acquire(request, value.acquisition)
    assert error.value.code == "ORIGINAL_PREPARATION_INVALID"
    assert value.metadata.acquisitions[key] == substituted
    assert inventory(value.artifacts.root) == before
