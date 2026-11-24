from dataclasses import replace
from datetime import timedelta

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


def test_current_cutoff_preserves_original_selection_on_acquisition_and_replay(
    tmp_path, monkeypatch
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
    prepared, _ = execute(value)
    request, *_ = source_case(tmp_path / "request")
    original_ref = value.service.reference(
        prepared.artifact_id, "sec-original-preparation-v1"
    )
    request = request.model_copy(update={"original_preparation": original_ref})
    requested_at = request.valuation_timestamp
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
    runner = SourcePreparationRunner(
        application=SimpleNamespace(
            snapshot=lambda key: value.metadata.snapshots[key],
            artifact_store=value.artifacts,
        ),
        metadata=value.metadata,
        acquisition=value.acquisition,
        artifacts=value.artifacts,
        canary=None,
    )
    groups = runner._plan_mappings(plan)
    assert groups and groups[0]
    again = acquire(frozen, value.acquisition)
    assert again.status == "reused" and again.snapshot_id == first.snapshot_id
    assert runner._plan_mappings(plan) == groups
    assert value.acquisition._original_reads.get() is None
