"""Issuer-entry workflow delegates to the existing source owners."""

import json
import os
import subprocess
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from fundamental_service.contracts import SourceRole
from fundamental_service.current_preparation import (
    CurrentSourcePreparation,
    CurrentSourcePreparationPublicationV1,
    CurrentSourcePreparationRequestV1,
)
from fundamental_service.issuer_preparation_runner import _execute, _run_child
from fundamental_service.original_source_plan import OriginalSourcePlanEvidenceV1
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import CapturedSource, SnapshotError
from fundamental_service.source_capture import SourceCaptureRequest
from test_original_source_plan import (
    compiler_case,
    configuration,
    issuer_market_policy_template,
)
from test_original_preparation import case, execute
from test_public_acquisition import acquisition, file_lock, inventory


def _args(tmp_path, annual_request):
    config = configuration()
    config_path = tmp_path / "source-plan-configuration.json"
    config_path.write_bytes(canonical_bytes(config))
    return SimpleNamespace(
        cik=annual_request.cik,
        valuation_timestamp=annual_request.valuation_timestamp.isoformat(),
        current=False,
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
    clock_ticks = iter(range(100, 200))
    run_number = 0

    monkeypatch.setattr(
        "fundamental_service.issuer_preparation_runner.monotonic",
        lambda: next(clock_ticks),
    )

    def invoke(module, arguments, *, timeout_seconds):
        nonlocal run_number
        assert 0 < timeout_seconds <= 120
        calls.append((module, arguments, timeout_seconds))
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

    assert [module.rsplit(".", 1)[-1] for module, _, _ in calls[:2]] == [
        "annual_discovery_runner",
        "preparation_runner",
    ]
    assert [timeout for _, _, timeout in calls] == [118, 116, 118, 116]
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


@pytest.mark.parametrize("mode", ("success", "missing", "different_template"))
def test_current_issuer_entry_joins_real_selection_and_effective_plan_lineage(
    tmp_path, monkeypatch, mode
):
    original_case = case(tmp_path / "original", monkeypatch)
    prepared, _ = execute(original_case)
    config = configuration(
        issuer_market_policy_template=issuer_market_policy_template()
    )
    compiler, request = compiler_case(original_case, prepared, config)
    compiled, _ = compiler.execute(request)
    args = _args(tmp_path, original_case.annual_request)
    args.current = True
    args.source_plan_configuration.write_bytes(canonical_bytes(config))
    args.configuration_digest = config.digest
    template = compiled.plan
    at = template.ingestions[0].valuation_timestamp
    capture_time = at + timedelta(seconds=2)
    by_uri = {item.uri: item for item in template.public_sources}

    class Capture:
        def __init__(self):
            self.calls = 0

        def validate_capture(self, source_id, uri):
            item = by_uri[uri]
            return SourceCaptureRequest(source_id, uri, item.terms_reference)

        def capture(self, source_id, uri):
            self.calls += 1
            if mode == "missing":
                raise SnapshotError("SOURCE_HTTP_NOT_FOUND", "selected source missing")
            return CapturedSource(
                source_id=source_id,
                uri=uri,
                role=SourceRole.REFERENCE,
                content=b"synthetic retained source",
                media_type="application/octet-stream",
                http_status=200,
                available_at=capture_time,
                captured_at=capture_time,
            )

    provider = Capture()
    public = acquisition(
        tmp_path / "public", provider, artifacts=original_case.artifacts
    )
    selector = CurrentSourcePreparation(
        acquisitions=public,
        artifacts=original_case.artifacts,
        selection_lock=lambda key: file_lock(tmp_path / "selection-locks", key),
        clock=lambda: capture_time,
    )

    def invoke(module, arguments, *, timeout_seconds):
        assert 0 < timeout_seconds <= 120
        if module.endswith("annual_discovery_runner"):
            return _discovery_result(compiled, prepared)
        assert "--current" in arguments
        selected_template = template
        if mode == "different_template":
            selected_template = template.model_copy(
                update={"release_profile_id": "different-profile"}
            )
        selected, selected_receipt = selector.execute(
            CurrentSourcePreparationRequestV1(template=selected_template),
            deadline_at=capture_time + timedelta(minutes=1),
        )
        if selected.plan is None:
            final = selected_receipt
        else:
            # The preparation owner is independently exercised by current-owner tests.
            # This fixture tests only the CLI join to its effective-plan receipt.
            report = {"plan_digest": selected.plan.digest, "status": "blocked"}
            final = original_case.artifacts.put_with_receipt(
                f"source-preparation:{sha256_digest(report)}",
                report,
                (selected.plan.digest,),
            )
        return CurrentSourcePreparationPublicationV1(
            artifact=final.artifact,
            wrote=final.wrote,
            current_selection=selected,
            current_selection_publication=selected_receipt,
        ).model_dump(mode="json")

    monkeypatch.setattr(
        "fundamental_service.issuer_preparation_runner._run_child", invoke
    )
    if mode == "different_template":
        with pytest.raises(ValueError, match="differs from the compiled plan"):
            _execute(args)
        return
    result = _execute(args)
    before = inventory(original_case.artifacts.root)
    calls = provider.calls
    repeated = _execute(args)
    assert provider.calls == calls == len(template.public_sources)
    assert inventory(original_case.artifacts.root) == before
    assert not repeated["lineage"]["current_source_selection"]["wrote"]
    if mode == "missing":
        assert result["status"] == "blocked" and result["preparation"] is None
        assert "SOURCE_HTTP_NOT_FOUND" in result["current_source_issue_codes"]
        assert "source_preparation" not in result["lineage"]
    else:
        assert result["status"] == "preparation_attempted"
        effective_ref = result["effective_source_plan_ref"]
        assert effective_ref.content_hash != template.digest
        assert result["effective_valuation_timestamp"] == capture_time
        assert result["source_plan_ref"].content_hash == template.digest
        assert result["lineage"]["source_preparation"]["input_digest"] == (
            effective_ref.content_hash
        )
        assert result["lineage"]["source_preparation"]["source_artifact_id"] == (
            effective_ref.artifact_id
        )
        assert not repeated["preparation"]["wrote"]


def test_current_issuer_entry_requires_source_templates_before_discovery(
    tmp_path, monkeypatch
):
    original_case = case(tmp_path / "original", monkeypatch)
    args = _args(tmp_path, original_case.annual_request)
    args.current = True
    monkeypatch.setattr(
        "fundamental_service.issuer_preparation_runner._run_child",
        lambda *args, **kwargs: pytest.fail(
            "unconfigured current mode contacted sources"
        ),
    )
    with pytest.raises(ValueError, match="requires public-source templates"):
        _execute(args)


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

    def invoke(module, arguments, *, timeout_seconds):
        assert 0 < timeout_seconds <= 120
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
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("unexpected child call")
        ),
    )

    try:
        _execute(args)
    except ValueError as error:
        assert str(error) == "source-plan configuration digest differs"
    else:
        raise AssertionError("mismatched configuration digest was accepted")


def test_child_timeout_is_bounded_and_classified(monkeypatch):
    observed = {}

    def expire(command, **kwargs):
        observed["timeout"] = kwargs["timeout"]
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(
        "fundamental_service.issuer_preparation_runner.subprocess.run", expire
    )

    try:
        _run_child("fundamental_service.test_child", [], timeout_seconds=2.5)
    except RuntimeError as error:
        assert str(error) == (
            "fundamental_service.test_child exceeded the issuer preparation deadline"
        )
    else:
        raise AssertionError("timed-out child was accepted")

    assert observed == {"timeout": 2.5}


def test_real_child_preserves_typed_contracts_shared_with_its_consumers(
    tmp_path, monkeypatch
):
    (tmp_path / "typed_preparation_child.py").write_text(
        "from pydantic import BaseModel\n"
        "import sys\n"
        "class Plan(BaseModel):\n"
        "    values: tuple[str, ...]\n"
        "def main(argv=None):\n"
        "    from typed_preparation_consumer import Request\n"
        "    plan = Plan(values=sys.argv[1:] if argv is None else argv)\n"
        "    print(Request(plan=plan).model_dump_json())\n"
        "    return 0\n"
        "if __name__ == '__main__':\n"
        "    raise SystemExit(main())\n"
    )
    (tmp_path / "typed_preparation_consumer.py").write_text(
        "from pydantic import BaseModel\n"
        "from typed_preparation_child import Plan\n"
        "class Request(BaseModel):\n"
        "    plan: Plan\n"
    )
    monkeypatch.setenv("PYTHONPATH", str(tmp_path), prepend=os.pathsep)
    arguments = ["--current", "literal spaces; $value", "line one\nline two"]

    result = _run_child("typed_preparation_child", arguments, timeout_seconds=10)

    assert result == {"plan": {"values": arguments}}
