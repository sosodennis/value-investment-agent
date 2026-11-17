"""Frozen SEC selection and current public captures retain their separate cutoffs."""

from dataclasses import replace
from datetime import timedelta

import pytest

from fundamental_service.current_preparation import (
    CurrentSourcePreparation,
    CurrentSourcePreparationRequestV1,
)
from fundamental_service.public_acquisition import PublicSourceAcquisition
from fundamental_service.operations import ServiceError
from fundamental_service.original_preparation import OriginalPreparation
from fundamental_service.snapshots import SnapshotError
from fundamental_service.source_plan_contracts import SOURCE_PREPARATION_PLAN
from test_automatic_mapping import EVALUATOR
from test_automatic_source_acquisition import acquire
from test_original_preparation import case, execute
from test_original_source_plan import compiler_case, configuration
from test_public_acquisition import Provider, request as public_request


def current_original_case(tmp_path, monkeypatch):
    value = case(tmp_path, monkeypatch, historical_annual=True)
    prepared, _ = execute(value)
    compiler, request = compiler_case(
        value, prepared, configuration().model_copy(update={"evaluator_id": EVALUATOR})
    )
    compiled, _ = compiler.execute(request)
    at = compiled.plan.ingestions[0].valuation_timestamp
    template = SOURCE_PREPARATION_PLAN.validate_python(
        compiled.plan.model_dump()
        | {"public_sources": (public_request(valuation_timestamp=at),)}
    )
    provider = Provider()
    provider.source = replace(
        provider.source,
        captured_at=at + timedelta(seconds=2),
        available_at=at + timedelta(seconds=2),
    )
    public = PublicSourceAcquisition(
        provider=provider,
        artifacts=value.artifacts,
        content=value.acquisition.content_store,
        capture_lock=value.locks,
    )
    selector = CurrentSourcePreparation(
        acquisitions=public,
        artifacts=value.artifacts,
        selection_lock=value.locks,
        clock=lambda: at + timedelta(seconds=3),
    )
    selected, _ = selector.execute(
        CurrentSourcePreparationRequestV1(template=template),
        deadline_at=at + timedelta(minutes=1),
    )
    return value, selected, provider


@pytest.mark.parametrize("completed", (False, True))
def test_retained_selection_reads_each_original_once_and_revalidates_next_call(
    tmp_path, monkeypatch, completed
):
    value, selected, _ = current_original_case(tmp_path, monkeypatch)
    ingestion = selected.plan.ingestions[0]
    if completed:
        acquire(ingestion, value.acquisition)
    preparation = value.service.read(ingestion.original_preparation.artifact_id)
    reference = preparation.filings[0].validation
    validation = value.service.read_validation(reference.artifact_id)
    calls = []
    read = OriginalPreparation.read_validation

    def observed(self, artifact_id, **kwargs):
        calls.append(artifact_id)
        return read(self, artifact_id, **kwargs)

    monkeypatch.setattr(OriginalPreparation, "read_validation", observed)
    first = value.acquisition.retained_acquisition(ingestion)
    assert calls == [reference.artifact_id]
    assert value.acquisition.retained_acquisition(ingestion) == first
    assert calls == [reference.artifact_id] * 2
    content = value.acquisition.content_store
    get = content.get
    monkeypatch.setattr(
        content,
        "get",
        lambda digest, **kwargs: b"corrupt"
        if digest == validation.original.source.content_hash
        else get(digest, **kwargs),
    )
    io = value.state.provider_calls, value.state.parser_calls
    with pytest.raises(SnapshotError) as failure:
        value.acquisition.retained_acquisition(ingestion)
    assert failure.value.code == "ORIGINAL_PREPARATION_INVALID"
    assert (value.state.provider_calls, value.state.parser_calls) == io


def test_compiled_historical_original_executes_at_frozen_current_capture_cutoff(
    tmp_path, monkeypatch
):
    value, selected, provider = current_original_case(tmp_path, monkeypatch)
    ingestion = selected.plan.ingestions[0]
    cutoff = selected.plan.public_source_cutoff
    assert cutoff.valuation_at == cutoff.requested_at + timedelta(seconds=2)
    first = acquire(ingestion, value.acquisition)
    assert first.snapshot_id and first.canonical_fact_ids
    snapshot = value.metadata.snapshots[first.snapshot_id]
    assert snapshot.valuation_timestamp == cutoff.valuation_at
    calls = (value.state.provider_calls, value.state.parser_calls, len(provider.calls))
    repeat = acquire(ingestion, value.acquisition, "current-replay")
    assert repeat.reused and repeat.snapshot_id == first.snapshot_id
    assert (
        value.state.provider_calls,
        value.state.parser_calls,
        len(provider.calls),
    ) == calls


@pytest.mark.parametrize("completed", (False, True))
@pytest.mark.parametrize("change", ("missing_cutoff", "receipt", "missing", "bytes"))
def test_current_original_refuses_changed_or_unavailable_cutoff_evidence(
    tmp_path, monkeypatch, completed, change
):
    value, selected, provider = current_original_case(tmp_path, monkeypatch)
    ingestion = selected.plan.ingestions[0]
    if completed:
        acquire(ingestion, value.acquisition)
    capture = selected.captures[0]
    if change == "missing_cutoff":
        ingestion = type(ingestion).model_validate(
            ingestion.model_dump() | {"public_source_cutoff": None}
        )
        expected = "ORIGINAL_PREPARATION_INVALID"
    elif change in {"receipt", "missing"}:
        read = value.artifacts.read

        def unavailable(artifact_id):
            if artifact_id == capture.artifact_id:
                if change == "missing":
                    raise SnapshotError("ARTIFACT_NOT_FOUND", "missing capture")
                return b"corrupt"
            return read(artifact_id)

        monkeypatch.setattr(value.artifacts, "read", unavailable)
        expected = (
            "PUBLIC_CAPTURE_INVALID" if change == "receipt" else "ARTIFACT_NOT_FOUND"
        )
    else:
        content = value.acquisition.content_store
        get = content.get
        monkeypatch.setattr(
            content,
            "get",
            lambda digest, **kwargs: b"corrupt"
            if digest == capture.source.content_sha256
            else get(digest, **kwargs),
        )
        expected = "PUBLIC_CAPTURE_HASH_MISMATCH"
    calls = (value.state.provider_calls, value.state.parser_calls, len(provider.calls))
    with pytest.raises(ServiceError) as failure:
        acquire(ingestion, value.acquisition)
    assert failure.value.code == expected
    assert (
        value.state.provider_calls,
        value.state.parser_calls,
        len(provider.calls),
    ) == calls
    assert value.metadata.audits[-1]["outcome"] == expected


def test_current_original_cutoff_cannot_diverge_from_plan_or_capture_time(
    tmp_path, monkeypatch
):
    _, selected, _ = current_original_case(tmp_path, monkeypatch)
    plan = selected.plan
    payload = plan.model_dump()
    payload["ingestions"][0].pop("public_source_cutoff")
    with pytest.raises(ValueError, match="plan cutoff"):
        SOURCE_PREPARATION_PLAN.validate_python(payload)
    cutoff = plan.public_source_cutoff
    for delta in (-1, 1):
        with pytest.raises(ValueError, match="last actual capture"):
            type(cutoff).model_validate(
                cutoff.model_dump()
                | {"valuation_at": cutoff.valuation_at + timedelta(seconds=delta)}
            )
