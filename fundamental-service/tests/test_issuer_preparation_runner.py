"""Issuer-entry workflow delegates to the existing source owners."""

import json
from pathlib import Path
from types import SimpleNamespace

from fundamental_service.issuer_preparation_runner import _execute
from fundamental_service.original_source_plan import OriginalSourcePlanEvidenceV1
from fundamental_service.serialization import canonical_bytes
from test_original_source_plan import compiler_case, configuration
from test_original_preparation import case, execute


def _args(tmp_path, annual_request):
    config = configuration()
    config_path = tmp_path / "source-plan-configuration.json"
    config_path.write_bytes(canonical_bytes(config))
    return SimpleNamespace(
        cik=annual_request.cik,
        valuation_timestamp=annual_request.valuation_timestamp.isoformat(),
        source_revision=annual_request.declared_source_revision,
        source_plan_configuration=config_path,
        configuration_digest=config.digest,
        original_count=annual_request.original_count,
        lookback_days=annual_request.lookback_days,
        timeout_seconds=120,
        ticker=None,
        share_class=None,
        validation_profile_id=None,
        actor="service-operator",
        organization="test-organization",
        machine_private_key=tmp_path / "machine-key.pem",
        candidate=None,
        approval=None,
        market_policy_authorization=None,
        market_policy_authorization_digest=None,
    )


def _discovery_result(evidence, prepared, *, wrote=False):
    annual_ref = prepared.request.annual
    compilation = evidence
    lineage = {
        "annual_discovery": {
            "artifact_id": annual_ref.artifact_id,
            "input_digest": "a" * 64,
            "output_digest": annual_ref.content_hash,
            "wrote": False,
        },
        "original_preparation": {
            "artifact_id": prepared.artifact_id,
            "input_digest": prepared.request.digest,
            "output_digest": prepared.digest,
            "wrote": False,
            "source_artifact_id": annual_ref.artifact_id,
            "source_digest": annual_ref.content_hash,
        },
        "source_plan_compilation": {
            "artifact_id": compilation.artifact_id,
            "input_digest": compilation.request.digest,
            "output_digest": compilation.digest,
            "wrote": wrote,
            "source_artifact_id": prepared.artifact_id,
            "source_digest": prepared.digest,
        },
    }
    return {
        "input_digest": evidence.request.digest,
        "output_digest": evidence.digest,
        "evidence": evidence.model_dump(mode="json"),
        "wrote": wrote,
        "lineage": lineage,
    }


def test_issuer_entry_compiles_then_runs_formal_preparation(tmp_path, monkeypatch):
    original_case = case(tmp_path, monkeypatch)
    prepared, _ = execute(original_case)
    compiler, request = compiler_case(original_case, prepared)
    evidence, _ = compiler.execute(request)
    calls = []
    run_number = 0

    def invoke(module, arguments):
        nonlocal run_number
        calls.append((module, arguments))
        if module.endswith("annual_discovery_runner"):
            run_number += 1
            assert "--cik" in arguments
            assert "--valuation-timestamp" in arguments
            assert "--prepare-originals" in arguments
            return _discovery_result(evidence, prepared, wrote=run_number == 1)
        assert module.endswith("preparation_runner")
        plan_path = arguments[arguments.index("--plan") + 1]
        assert canonical_bytes(evidence.plan) == Path(plan_path).read_bytes()
        assert arguments[arguments.index("--plan-digest") + 1] == evidence.plan.digest
        assert arguments[arguments.index("--actor") + 1] == "service-operator"
        assert arguments[arguments.index("--organization") + 1] == "test-organization"
        assert "--approval" not in arguments
        return {
            "artifact": {
                "artifact_id": "source-preparation:abc",
                "content_hash": "b" * 64,
                "dependency_hashes": [evidence.plan.digest],
            },
            "wrote": run_number == 1,
        }

    monkeypatch.setattr(
        "fundamental_service.issuer_preparation_runner._run_child", invoke
    )
    result = _execute(_args(tmp_path, original_case.annual_request))
    repeated = _execute(_args(tmp_path, original_case.annual_request))

    assert [module.rsplit(".", 1)[-1] for module, _ in calls[:2]] == [
        "annual_discovery_runner",
        "preparation_runner",
    ]
    assert result["status"] == "preparation_attempted"
    assert result["original_preparation_artifact_id"] == prepared.artifact_id
    assert result["source_plan_ref"].content_hash == evidence.plan.digest
    assert result["preparation"]["wrote"] is True
    assert result["lineage"]["source_preparation"]["source_digest"] == (
        evidence.plan.digest
    )
    assert not Path(calls[1][1][1]).exists()
    assert repeated["preparation"]["wrote"] is False
    assert (
        repeated["source_plan_request_digest"] == result["source_plan_request_digest"]
    )
    assert (
        repeated["source_plan_compilation_digest"]
        == result["source_plan_compilation_digest"]
    )
    assert all(not stage["wrote"] for stage in repeated["lineage"].values())


def test_incomplete_original_evidence_is_retained_without_running_preparation(
    tmp_path, monkeypatch
):
    original_case = case(tmp_path, monkeypatch)
    prepared, _ = execute(original_case)
    compiler, request = compiler_case(original_case, prepared)
    complete, _ = compiler.execute(request)
    blocked_payload = complete.model_dump(mode="json")
    blocked_payload["plan"] = None
    blocked_payload["issue_codes"] = ["ORIGINAL_SOURCE_PLAN_IDENTITY_MISSING"]
    blocked = OriginalSourcePlanEvidenceV1.model_validate_json(
        json.dumps(blocked_payload)
    )
    calls = []

    def invoke(module, arguments):
        calls.append(module)
        return _discovery_result(blocked, prepared)

    monkeypatch.setattr(
        "fundamental_service.issuer_preparation_runner._run_child", invoke
    )
    result = _execute(_args(tmp_path, original_case.annual_request))

    assert calls == ["fundamental_service.annual_discovery_runner"]
    assert result["status"] == "blocked"
    assert result["source_plan_issue_codes"] == (
        "ORIGINAL_SOURCE_PLAN_IDENTITY_MISSING",
    )
    assert result["preparation"] is None


def test_configuration_digest_is_checked_before_source_commands(tmp_path, monkeypatch):
    original_case = case(tmp_path, monkeypatch)
    args = _args(tmp_path, original_case.annual_request)
    args.configuration_digest = "0" * 64
    monkeypatch.setattr(
        "fundamental_service.issuer_preparation_runner._run_child",
        lambda *_: (_ for _ in ()).throw(AssertionError("unexpected child call")),
    )

    try:
        _execute(args)
    except ValueError as error:
        assert str(error) == "source-plan configuration digest differs"
    else:
        raise AssertionError("mismatched configuration digest was accepted")
