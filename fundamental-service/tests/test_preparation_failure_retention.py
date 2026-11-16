"""Incomplete histories retain every original without calculation or activation."""

from types import SimpleNamespace

import pytest

from fundamental_service.contracts import QualityStatus
from fundamental_service.operations import ServiceError
from fundamental_service.preparation_runner import (
    SourceAcquisitionOutcomeV1,
    SourcePreparationAcquisitionsV1,
)
from fundamental_service.source_plan_contracts import SourcePreparationPlanV2
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import SnapshotError
from test_preparation_runner import (
    _acquisition,
    _fixture,
    _reader,
    _run,
    _runner,
)


def _history_plan(fixture):
    first = fixture.plan.ingestions[0]
    return SourcePreparationPlanV2.model_validate(
        {
            **fixture.plan.model_dump(),
            "ingestions": tuple(
                first.model_copy(
                    update={
                        "filing": first.filing.model_copy(
                            update={
                                "accession_number": f"0000000001-{year}-000001",
                                "forms": ("10-K",),
                            }
                        )
                    }
                )
                for year in (23, 24, 25)
            ),
        }
    )


@pytest.mark.parametrize("failed_index", [0, 1, 2])
@pytest.mark.parametrize("failure", ["provisional", "abstain", "source", "snapshot"])
def test_incomplete_original_retains_entire_plan_and_reuses_report(
    tmp_path, monkeypatch, failed_index, failure
):
    fixture = _fixture(tmp_path, released=False)
    plan = _history_plan(fixture)
    calls = []
    base = _acquisition(fixture)
    repeated = False

    def execute(request, **kwargs):
        index = plan.ingestions.index(request)
        calls.append(index)
        if index == failed_index and failure in {"source", "snapshot"}:
            if failure == "source":
                raise ServiceError(
                    "ORIGINAL_SOURCE_INVALID",
                    "invalid",
                    status_code=422,
                    retryable=False,
                )
            raise SnapshotError("PARSER_VALIDATION_BLOCKED", "invalid")
        result = base.execute(request, **kwargs)
        if index == failed_index:
            result = result.model_copy(
                update={
                    "quality_status": QualityStatus(failure),
                    "issue_codes": ("REQUIRED_FACTS_UNAVAILABLE",),
                    "missing_evidence": ("revenue",),
                }
            )
        if repeated:
            result = result.model_copy(update={"status": "reused", "reused": True})
        return result

    def forbidden(*args, **kwargs):
        pytest.fail("incomplete originals must not compose, release or calculate")

    monkeypatch.setattr(
        "fundamental_service.preparation_runner.compose_original_history", forbidden
    )
    runner = _runner(
        fixture,
        acquisition=SimpleNamespace(execute=execute),
        canary=SimpleNamespace(validate=forbidden),
    )
    first = _run(runner, plan)
    evidence = _reader(fixture, first)
    assert evidence.source_plan_ref is not None
    retained_plan = fixture.artifacts.read(evidence.source_plan_ref.artifact_id)
    assert retained_plan == canonical_bytes(plan)
    assert SourcePreparationPlanV2.model_validate_json(retained_plan) == plan
    assert evidence.source_plan_ref.content_hash == evidence.plan_digest == plan.digest
    assert calls == [0, 1, 2]
    assert first.wrote is True
    assert evidence.status == "blocked"
    assert evidence.preparation is evidence.calculation is None
    assert tuple(o.request_digest for o in evidence.source_outcomes) == tuple(
        sha256_digest(r) for r in plan.ingestions
    )
    assert tuple(o.accession_number for o in evidence.source_outcomes) == tuple(
        r.filing.accession_number for r in plan.ingestions
    )
    assert [
        i
        for i, o in enumerate(evidence.source_outcomes)
        if o.quality_status is not QualityStatus.VERIFIED
    ] == [failed_index]
    failed = evidence.source_outcomes[failed_index]
    assert failed.missing_evidence == evidence.missing_evidence
    assert failed.issue_codes == evidence.issue_codes
    assert failed.missing_evidence == (
        tuple(sorted(plan.ingestions[failed_index].required_fields))
        if failure in {"source", "snapshot"}
        else ("revenue",)
    )
    before = {
        str(path.relative_to(tmp_path)): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    repeated = True
    second = _run(runner, plan, correlation="second-transport-context")
    assert calls == [0, 1, 2, 0, 1, 2]
    assert second.artifact == first.artifact
    assert second.wrote is False
    assert canonical_bytes(_reader(fixture, second)) == canonical_bytes(evidence)
    assert before == {
        str(path.relative_to(tmp_path)): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert {o.request_digest for o in evidence.source_outcomes} <= set(
        first.artifact.dependency_hashes
    )


def test_different_original_failures_retain_all_diagnostics(tmp_path):
    fixture = _fixture(tmp_path, released=False)
    plan = _history_plan(fixture)
    base = _acquisition(fixture)

    def execute(request, **kwargs):
        index = plan.ingestions.index(request)
        if index == 1:
            raise ServiceError(
                "PARSER_VALIDATION_BLOCKED", "invalid", status_code=422, retryable=False
            )
        return base.execute(request, **kwargs).model_copy(
            update={
                "quality_status": QualityStatus.ABSTAIN,
                "issue_codes": (f"MAPPING_MISSING_{index}",),
                "missing_evidence": (("revenue", "capital_expenditure")[index // 2],),
            }
        )

    receipt = _run(_runner(fixture, acquisition=SimpleNamespace(execute=execute)), plan)
    evidence = _reader(fixture, receipt)
    assert len(evidence.source_outcomes) == 3
    assert evidence.issue_codes == (
        "MAPPING_MISSING_0",
        "MAPPING_MISSING_2",
        "PARSER_VALIDATION_BLOCKED",
    )
    assert evidence.missing_evidence == tuple(
        sorted(plan.ingestions[1].required_fields)
    )


@pytest.mark.parametrize("status,retryable", [(403, False), (409, True), (503, True)])
def test_transport_or_authorization_failure_still_stops_acquisition(
    tmp_path, status, retryable
):
    fixture = _fixture(tmp_path, released=False)
    plan = _history_plan(fixture)
    calls = []

    def execute(request, **kwargs):
        calls.append(request)
        raise ServiceError(
            "UNAVAILABLE", "unavailable", status_code=status, retryable=retryable
        )

    with pytest.raises(ServiceError, match="unavailable"):
        _run(_runner(fixture, acquisition=SimpleNamespace(execute=execute)), plan)
    assert calls == [plan.ingestions[0]]


@pytest.mark.parametrize(
    "changes",
    [
        {"manifest_digest": "a" * 64},
        {"quality_status": QualityStatus.VERIFIED},
        {"issue_codes": ()},
        {"missing_evidence": ("revenue", "capex")},
        {"issue_codes": ("Z", "A")},
    ],
)
def test_outcome_rejects_incomplete_or_unordered_evidence(changes):
    with pytest.raises(ValueError):
        SourceAcquisitionOutcomeV1.model_validate(
            {
                "request_digest": "a" * 64,
                "quality_status": None,
                "issue_codes": ("SOURCE_INVALID",),
                **changes,
            }
        )


@pytest.mark.parametrize("failure", ["invalidated", "plan", "request", "bytes"])
def test_retained_outcome_corruption_refuses_before_resolution(
    tmp_path, monkeypatch, failure
):
    fixture = _fixture(tmp_path)
    plan = fixture.plan
    outcomes = (
        SourceAcquisitionOutcomeV1(
            request_digest=(
                "0" * 64 if failure == "request" else sha256_digest(plan.ingestions[0])
            ),
            quality_status=None,
            issue_codes=("SOURCE_INVALID",),
        ),
    )
    artifact_id = f"source-preparation-acquisitions:{plan.digest}"
    publication = fixture.artifacts.put_with_receipt(
        artifact_id,
        SourcePreparationAcquisitionsV1(
            plan_digest="0" * 64 if failure == "plan" else plan.digest,
            source_outcomes=outcomes,
        ),
    )
    if failure == "invalidated":
        fixture.artifacts.invalidate(artifact_id)
    elif failure == "bytes":
        record = publication.artifact
        path = fixture.artifacts._artifact_path(record.content_hash, record.media_type)
        path.write_bytes(b"{}")

    def forbidden(*args, **kwargs):
        pytest.fail("invalid retained outcomes must refuse before release resolution")

    monkeypatch.setattr(
        "fundamental_service.preparation_runner.SourcePreparationRunner._resolve",
        forbidden,
    )
    with pytest.raises((ValueError, SnapshotError)):
        _run(_runner(fixture), plan)


def test_source_coverage_cannot_launder_verified_acquisition_quality():
    with pytest.raises(ValueError, match="verified source coverage"):
        SourceAcquisitionOutcomeV1(
            request_digest="a" * 64,
            quality_status=QualityStatus.VERIFIED,
            snapshot_id="source",
            manifest_digest="b" * 64,
            source_coverage_status=QualityStatus.PROVISIONAL,
        )
