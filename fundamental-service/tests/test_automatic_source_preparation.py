"""The installed preparation entrypoint accepts a mapping-free automatic plan."""

from datetime import UTC, datetime, timedelta
import json
from types import SimpleNamespace
from pathlib import Path
import subprocess
import sys

import pytest
from pydantic import ValidationError

from fundamental_service.contracts import CallerApprovalEnvelopeV1
from fundamental_service.data_releases import DataReleaseError
from fundamental_service.operations import ServiceError
from fundamental_service.snapshots import SnapshotError
from fundamental_service.preparation_runner import (
    SourcePreparationEvidenceV1,
    SourcePreparationRunner,
    main,
)
from fundamental_service.source_plan_contracts import (
    AutomaticSourcePreparationPlanV1,
    SOURCE_PREPARATION_PLAN,
)
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.automatic_mapping_batch import (
    AutomaticMappingBatchDecisionV1,
    AutomaticMappingProposalDecisionV1,
)
from test_automatic_source_acquisition import acquisition_case, acquire
from test_issuer_operating_release import inventory


def automatic_plan(request):
    return AutomaticSourcePreparationPlanV1(
        source_revision=request.source_revision,
        release_profile_id="automatic-original-fcff",
        model_id=request.model_id,
        ingestions=(request,),
    )


def runner_case(tmp_path, monkeypatch):
    request, acquisition, state, metadata, artifacts = acquisition_case(
        tmp_path, monkeypatch
    )

    def missing_release(_request):
        raise ServiceError(
            "SNAPSHOT_NOT_FOUND", "empty store", status_code=404, retryable=False
        )

    def forbidden(*args, **kwargs):
        pytest.fail(
            "an incomplete automatic original must not release, compose or calculate"
        )

    application = SimpleNamespace(
        resolve_snapshot=missing_release,
        artifact_store=artifacts,
        fact_repository=SimpleNamespace(get=metadata.facts.__getitem__),
        snapshot=metadata.snapshots.__getitem__,
        prepare_valuation=forbidden,
        calculate_valuation=forbidden,
    )
    monkeypatch.setattr(
        "fundamental_service.preparation_runner.compose_original_history", forbidden
    )
    runner = SourcePreparationRunner(
        application=application,
        metadata=metadata,
        acquisition=acquisition,
        artifacts=artifacts,
        canary=SimpleNamespace(validate=forbidden),
    )
    return automatic_plan(request), runner, state, metadata, artifacts


def run(runner, plan, **kwargs):
    return runner.run(
        plan,
        actor_id="caller",
        organization_id="org",
        correlation_id="automatic-source",
        deadline_at=datetime.now(UTC) + timedelta(minutes=1),
        **kwargs,
    )


def test_mapping_free_plan_retains_full_blocked_result_and_reuses_everything(
    tmp_path, monkeypatch
):
    plan, runner, state, metadata, artifacts = runner_case(tmp_path, monkeypatch)
    assert SOURCE_PREPARATION_PLAN.validate_json(canonical_bytes(plan)) == plan
    assert "mappings" not in plan.ingestions[0].model_dump()
    first = run(runner, plan)
    report = SourcePreparationEvidenceV1.model_validate_json(
        artifacts.read(first.artifact.artifact_id)
    )
    assert (
        report.status == "blocked" and report.preparation is report.calculation is None
    )
    assert report.source_plan_ref.role == plan.protocol
    assert artifacts.read(report.source_plan_ref.artifact_id) == canonical_bytes(plan)
    outcome = report.source_outcomes[0]
    assert (
        outcome.mapping_evidence_ref
        and outcome.mapping_evidence_ref.content_hash
        in first.artifact.dependency_hashes
    )
    assert artifacts.read(outcome.mapping_evidence_ref.artifact_id)
    assert "non_operating_assets" in outcome.missing_evidence
    fact_inventory = report.fact_evidence_inventory
    assert fact_inventory is not None
    assert fact_inventory.requirements_digest == plan.requirements_profile.digest
    roles = {row.normalized_field: row for row in fact_inventory.roles}
    assert roles["non_operating_assets"].state == "unknown"
    assert not roles["non_operating_assets"].observations
    batch = AutomaticMappingBatchDecisionV1.model_validate_json(
        artifacts.read(outcome.mapping_evidence_ref.artifact_id)
    )
    expected = {
        (role.normalized_field, index, proposal.reason_codes)
        for role in batch.roles
        for index, proposal in enumerate(role.proposal_decisions())
        if proposal.status == "abstain"
    }
    actual = {
        (row.normalized_field, item.proposal_index, item.reason_codes)
        for row in fact_inventory.roles
        for item in row.mapping_refusals
    }
    assert actual == expected
    assert roles["non_operating_assets"].mapping_refusals
    for row in fact_inventory.roles:
        for item in row.mapping_refusals:
            assert item.batch_ref == outcome.mapping_evidence_ref
            assert item.batch_ref.content_hash == sha256_digest(batch)
            assert item.accession_number == plan.ingestions[0].filing.accession_number
            assert item.source_content_hash in {
                source.content_hash
                for source in metadata.snapshots[report.snapshot_id].source_records
            }
    assert roles["stock_based_compensation"].observations
    assert metadata.mappings and len(metadata.acquisitions) == 1
    before = inventory(artifacts.root)
    audits = tuple(metadata.audits)
    calls = state.provider_calls, state.parser_calls
    second = run(runner, plan)
    assert second.artifact == first.artifact and not second.wrote
    assert calls == (state.provider_calls, state.parser_calls)
    assert before == inventory(artifacts.root)
    assert tuple(metadata.audits) == audits


def test_retained_partial_automatic_batch_supplies_only_approved_plan_mappings(
    tmp_path, monkeypatch
):
    plan, runner, _, metadata, _ = runner_case(tmp_path, monkeypatch)
    run(runner, plan)
    acquired = next(iter(metadata.acquisitions.values()))
    assert acquired.quality_status.value == "abstain"
    assert metadata.snapshots[acquired.snapshot_id].coverage_status.value == "verified"
    groups = runner._plan_mappings(plan)
    assert groups is not None
    assert {ref.decision_id for ref in groups[0]} == set(metadata.mappings)
    assert "stock_based_compensation" in {ref.normalized_field for ref in groups[0]}
    assert "non_operating_assets" not in {ref.normalized_field for ref in groups[0]}


def test_existing_release_without_plan_report_retains_mapping_refusals_without_reacquiring(
    tmp_path, monkeypatch
):
    plan, runner, state, metadata, artifacts = runner_case(tmp_path, monkeypatch)
    acquired = acquire(plan.ingestions[0], runner._acquisition)
    with pytest.raises(SnapshotError) as missing:
        artifacts.get("source-preparation-acquisitions:" + plan.digest)
    assert missing.value.code == "ARTIFACT_NOT_FOUND"
    calls = state.provider_calls, state.parser_calls

    def no_reacquisition(*args, **kwargs):
        pytest.fail("compatible active release must reuse its completed acquisition")

    def incomplete_preparation(_request):
        raise ServiceError(
            "VALUATION_REQUIRED_FACTS_MISSING",
            "synthetic compatible release remains financially incomplete",
            status_code=422,
            retryable=False,
        )

    # Isolate the existing-release branch; source acquisition and mapping evidence
    # use the real owners. No release or complete valuation is asserted here.
    monkeypatch.setattr(
        runner,
        "_resolve",
        lambda _: SimpleNamespace(
            snapshot_id=acquired.snapshot_id,
            data_release_manifest_digest="d" * 64,
        ),
    )
    monkeypatch.setattr(runner._acquisition, "execute", no_reacquisition)
    monkeypatch.setattr(
        runner._application, "prepare_valuation", incomplete_preparation
    )
    first = run(runner, plan)
    report = SourcePreparationEvidenceV1.model_validate_json(
        artifacts.read(first.artifact.artifact_id)
    )
    assert report.status == "blocked" and report.preparation is None
    assert report.source_outcomes[0].mapping_evidence_ref is not None
    row = next(
        item
        for item in report.fact_evidence_inventory.roles
        if item.normalized_field == "non_operating_assets"
    )
    assert row.state == "unknown" and row.mapping_refusals
    before = inventory(artifacts.root)
    second = run(runner, plan)
    assert second.artifact == first.artifact and not second.wrote
    assert inventory(artifacts.root) == before
    assert calls == (state.provider_calls, state.parser_calls)
    assert len(metadata.acquisitions) == 1


def test_diagnostics_retain_secondary_proposal_refusals_and_bind_the_original(
    tmp_path, monkeypatch
):
    plan, runner, _, metadata, artifacts = runner_case(tmp_path, monkeypatch)
    first = run(runner, plan)
    report = SourcePreparationEvidenceV1.model_validate_json(
        artifacts.read(first.artifact.artifact_id)
    )
    (outcome,) = report.source_outcomes
    batch = AutomaticMappingBatchDecisionV1.model_validate_json(
        artifacts.read(outcome.mapping_evidence_ref.artifact_id)
    )
    extra = AutomaticMappingProposalDecisionV1(
        status="abstain",
        reason_codes=("MAPPING_DISCLOSURE_SCALE_UNRESOLVED",),
        decision=None,
        approval=None,
    )
    changed = batch.model_copy(
        update={
            "roles": tuple(
                role.model_copy(update={"additional_decisions": (extra,)})
                if role.normalized_field == "stock_based_compensation"
                else role
                for role in batch.roles
            )
        }
    )
    publication = artifacts.put_with_receipt("batch-with-secondary-refusal", changed)
    reference = outcome.mapping_evidence_ref.model_copy(
        update={
            "artifact_id": publication.artifact.artifact_id,
            "content_hash": publication.artifact.content_hash,
        }
    )
    changed_outcome = outcome.model_copy(update={"mapping_evidence_ref": reference})
    refusals = runner._mapping_refusals((changed_outcome,))
    secondary = next(
        item for item in refusals if item.normalized_field == "stock_based_compensation"
    )
    assert (
        secondary.proposal_index == 1 and secondary.reason_codes == extra.reason_codes
    )
    assert secondary.batch_ref == reference
    assert secondary.source_content_hash in {
        source.content_hash
        for source in metadata.snapshots[outcome.snapshot_id].source_records
        if source.source_id == "sec-filing"
    }


@pytest.mark.parametrize("change", ("digest", "input", "original", "snapshot"))
def test_diagnostics_refuse_mismatched_batch_input_original_or_snapshot(
    tmp_path, monkeypatch, change
):
    plan, runner, _, _, artifacts = runner_case(tmp_path, monkeypatch)
    first = run(runner, plan)
    report = SourcePreparationEvidenceV1.model_validate_json(
        artifacts.read(first.artifact.artifact_id)
    )
    (outcome,) = report.source_outcomes
    if change == "digest":
        reference = outcome.mapping_evidence_ref.model_copy(
            update={"content_hash": "f" * 64}
        )
        outcome = outcome.model_copy(update={"mapping_evidence_ref": reference})
    elif change == "snapshot":
        outcome = outcome.model_copy(update={"manifest_digest": "f" * 64})
    elif change == "original":
        outcome = outcome.model_copy(
            update={"accession_number": "0000000002-26-000001"}
        )
    else:
        batch = AutomaticMappingBatchDecisionV1.model_validate_json(
            artifacts.read(outcome.mapping_evidence_ref.artifact_id)
        )
        original_read = artifacts.read

        def changed_read(artifact_id):
            raw = original_read(artifact_id)
            if artifact_id == "automatic-mapping-batch-input-v2-" + batch.input_digest:
                value = json.loads(raw)
                value["original_ref"]["content_hash"] = "f" * 64
                return canonical_bytes(value)
            return raw

        monkeypatch.setattr(artifacts, "read", changed_read)
    with pytest.raises(
        (DataReleaseError, ValueError),
        match="exact retained JSON|exact original|issuer evidence digest mismatch",
    ):
        runner._mapping_refusals((outcome,))


@pytest.mark.parametrize(
    "changes",
    [
        {"source_revision": "b" * 40},
        {"model_id": "transition_fcff_dcf"},
    ],
)
def test_plan_rejects_incoherent_model_or_source_revision(
    tmp_path, monkeypatch, changes
):
    plan, _, _, _, _ = runner_case(tmp_path, monkeypatch)
    with pytest.raises(ValidationError):
        AutomaticSourcePreparationPlanV1.model_validate(
            {**plan.model_dump(), **changes}
        )


def test_invalid_caller_approval_refuses_before_automatic_source_io(
    tmp_path, monkeypatch
):
    plan, runner, state, metadata, _ = runner_case(tmp_path, monkeypatch)
    approval = CallerApprovalEnvelopeV1(
        input_digest="a" * 64,
        decision="approved",
        caller_id="different-caller",
        decided_at=datetime.now(UTC),
    )
    with pytest.raises(ServiceError):
        run(runner, plan, approval=approval)
    assert state.provider_calls == state.parser_calls == 0
    assert not metadata.acquisitions and not metadata.mappings


def test_cli_rejects_wrong_automatic_plan_digest_before_startup(
    tmp_path, monkeypatch, capsys
):
    plan, _, state, metadata, _ = runner_case(tmp_path, monkeypatch)
    path = tmp_path / "plan.json"
    path.write_bytes(canonical_bytes(plan))
    assert (
        main(
            [
                "--plan",
                str(path),
                "--plan-digest",
                "b" * 64,
                "--actor",
                "caller",
                "--organization",
                "org",
            ]
        )
        == 2
    )
    assert "plan digest does not match" in capsys.readouterr().err
    assert state.provider_calls == state.parser_calls == 0 and not metadata.acquisitions


def test_automatic_runtime_mismatch_refuses_before_source_io(tmp_path, monkeypatch):
    plan, runner, state, metadata, _ = runner_case(tmp_path, monkeypatch)
    request = plan.ingestions[0].model_copy(update={"mapping_policy_digest": "b" * 64})
    plan = plan.model_copy(update={"ingestions": (request,)})
    with pytest.raises(DataReleaseError, match="installed runtime"):
        run(runner, plan)
    assert state.provider_calls == state.parser_calls == 0
    assert not metadata.acquisitions and not metadata.mappings


def test_installed_cli_resolves_shared_contract_from_an_unrelated_directory(
    tmp_path, monkeypatch
):
    plan, *_ = runner_case(tmp_path, monkeypatch)
    path = tmp_path / "plan.json"
    path.write_bytes(canonical_bytes(plan))
    process = subprocess.run(
        [
            str(Path(sys.executable).parent / "fundamental-prepare-source"),
            "--plan",
            str(path),
            "--plan-digest",
            "b" * 64,
            "--actor",
            "caller",
            "--organization",
            "org",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert process.returncode == 2
    assert "plan digest does not match" in process.stderr
    assert "ModuleNotFoundError" not in process.stderr


def test_report_interruption_reuses_completed_automatic_acquisition(
    tmp_path, monkeypatch
):
    plan, runner, state, metadata, artifacts = runner_case(tmp_path, monkeypatch)
    original = artifacts.put_with_receipt

    def interrupt(key, *args, **kwargs):
        if key.startswith("source-preparation:"):
            raise OSError("synthetic report publication interruption")
        return original(key, *args, **kwargs)

    monkeypatch.setattr(artifacts, "put_with_receipt", interrupt)
    with pytest.raises(OSError, match="publication interruption"):
        run(runner, plan)
    assert len(metadata.acquisitions) == 1 and metadata.mappings
    calls = state.provider_calls, state.parser_calls
    monkeypatch.setattr(artifacts, "put_with_receipt", original)
    recovered = run(runner, plan)
    before = inventory(artifacts.root)
    repeated = run(runner, plan)
    assert recovered.wrote and not repeated.wrote
    assert recovered.artifact == repeated.artifact
    assert calls == (state.provider_calls, state.parser_calls)
    assert before == inventory(artifacts.root)


def test_discriminator_preserves_manual_plan_and_refuses_automatic_manual_refs(
    tmp_path, monkeypatch
):
    from test_preparation_runner import _fixture

    manual = _fixture(tmp_path / "manual").plan
    assert SOURCE_PREPARATION_PLAN.validate_json(canonical_bytes(manual)) == manual
    automatic, *_ = runner_case(tmp_path / "automatic", monkeypatch)
    payload = automatic.model_dump()
    payload["ingestions"][0]["mappings"] = manual.ingestions[0].mappings
    with pytest.raises(ValidationError, match="Extra inputs"):
        SOURCE_PREPARATION_PLAN.validate_python(payload)
