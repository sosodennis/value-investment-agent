"""The installed preparation entrypoint accepts a mapping-free automatic plan."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from pathlib import Path
import subprocess
import sys

import pytest
from pydantic import ValidationError

from fundamental_service.contracts import CallerApprovalEnvelopeV1
from fundamental_service.data_releases import DataReleaseError
from fundamental_service.operations import ServiceError
from fundamental_service.preparation_runner import (
    AutomaticSourcePreparationPlanV1,
    SOURCE_PREPARATION_PLAN,
    SourcePreparationEvidenceV1,
    SourcePreparationRunner,
    main,
)
from fundamental_service.serialization import canonical_bytes
from test_automatic_source_acquisition import acquisition_case
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
    assert metadata.mappings and len(metadata.acquisitions) == 1
    before = inventory(artifacts.root)
    audits = tuple(metadata.audits)
    calls = state.provider_calls, state.parser_calls
    second = run(runner, plan)
    assert second.artifact == first.artifact and not second.wrote
    assert calls == (state.provider_calls, state.parser_calls)
    assert before == inventory(artifacts.root)
    assert tuple(metadata.audits) == audits


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
