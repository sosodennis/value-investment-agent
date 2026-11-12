"""Model pins identify executable specifications before research publication."""

import sys

import pytest
from pydantic import ValidationError

from fundamental_service import (
    operating_comparison_runner,
    operating_projection,
    operating_scenario_runner,
)
from fundamental_service.calculator import CalculationRefusal, calculate
from fundamental_service.operating_projection import OperatingProjectionError
from fundamental_service.operating_scenario_contracts import OperatingScenarioRequestV1
from fundamental_service.operating_scenarios import replay_operating_scenarios
from fundamental_service.policies import initial_model_specs
from fundamental_service.replay import ArtifactStore
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.testsupport import make_valuation
from test_operating_forecast import operating_facts, prepare
from test_operating_labels import comparison_request
from test_operating_scenarios import request


INVALID_VERSIONS = (
    ("unimplemented-v999", "unimplemented-v999"),
    ("fcff_dcf-v3", "transition_fcff_dcf-v2"),
    ("fcff_dcf-v2", "transition_fcff_dcf-v1"),
    ("transition_fcff_dcf-v2", "fcff_dcf-v2"),
)


@pytest.mark.parametrize("versions", INVALID_VERSIONS)
def test_validated_request_rejects_invented_stale_and_swapped_versions(versions):
    payload = request().model_dump()
    payload["model_versions"] = dict(
        zip(payload["model_versions"], versions, strict=True)
    )
    with pytest.raises(ValidationError, match="requires executable version"):
        OperatingScenarioRequestV1.model_validate(payload)
    with pytest.raises(ValidationError, match="requires executable version"):
        OperatingScenarioRequestV1.model_validate_json(canonical_bytes(payload))


def test_supported_models_report_resolved_versions_and_specification_digests():
    original = request()
    result = replay_operating_scenarios(original)
    specs = {spec.model_id: spec for spec in initial_model_specs()}
    assert result.contract_version == "fundamental.operating-scenario-replay.v2"
    for row in result.results:
        spec = specs[row.model_id]
        assert row.model_version == spec.model_version
        assert row.model_spec_digest == sha256_digest(spec)
        assert row.supported_history_threshold is None
    assert result.results[0].status == "provisional_scenario"
    assert result.results[1].issue_codes[-1] == "TRANSITION_EVIDENCE_MISSING"
    assert (
        sha256_digest(result.results[0].nodes)
        == "a32de79eff01917d331fa7af44f97cc2154505ca2d9e8eb0cb06bd413245fe30"
    )


@pytest.mark.parametrize("comparison", (False, True))
def test_publication_rejects_mutated_model_pins_without_writing_artifacts(
    tmp_path, comparison
):
    req = comparison_request() if comparison else request()
    decision = req.decision if comparison else req
    changed = decision.model_copy(
        update={
            "model_versions": {
                key: "unimplemented-v999" for key in decision.model_versions
            }
        }
    )
    if comparison:
        req = req.model_copy(
            update={
                "decision": changed,
                "decision_input_digest": sha256_digest(changed),
            }
        )
        publish = operating_comparison_runner.publish_operating_comparison
    else:
        req = changed
        publish = operating_scenario_runner.publish_scenario_replay
    with pytest.raises(OperatingProjectionError) as caught:
        publish(
            req, artifacts=ArtifactStore(tmp_path), execution={"exact_commit": "a" * 40}
        )
    assert caught.value.code == "MODEL_VERSION_UNSUPPORTED"
    assert not tuple(tmp_path.rglob("*.artifact"))


@pytest.mark.parametrize(
    "runner", (operating_scenario_runner, operating_comparison_runner)
)
@pytest.mark.parametrize("versions", INVALID_VERSIONS)
def test_runner_input_validation_fails_before_forecast_publication(
    tmp_path, monkeypatch, runner, versions
):
    req = comparison_request() if runner is operating_comparison_runner else request()
    payload = req.model_dump()
    decision = payload["decision"] if runner is operating_comparison_runner else payload
    decision["model_versions"] = dict(
        zip(decision["model_versions"], versions, strict=True)
    )
    if runner is operating_comparison_runner:
        payload["decision_input_digest"] = sha256_digest(decision)
    request_path = tmp_path / "request.json"
    request_path.write_bytes(canonical_bytes(payload))
    output = tmp_path / "artifacts"
    revision = "a" * 40

    def git_state(command, **kwargs):
        if command == ["git", "rev-parse", "HEAD"]:
            return revision + "\n"
        assert command == ["git", "status", "--porcelain"]
        return ""

    monkeypatch.setattr(runner.subprocess, "check_output", git_state)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            runner.__name__,
            "--request",
            str(request_path),
            "--artifacts",
            str(output),
            "--implementation-commit",
            revision,
        ],
    )
    with pytest.raises(ValidationError, match="requires executable version"):
        runner.main()
    assert not output.exists()


@pytest.mark.parametrize("model", ("fcff_dcf", "transition_fcff_dcf"))
@pytest.mark.parametrize("version", ("unimplemented-v999", "fcff_dcf-v3"))
def test_operating_forecast_and_calculator_reject_unexecutable_versions(model, version):
    with pytest.raises(OperatingProjectionError) as operating:
        prepare(operating_facts(), model_id=model, model_version=version)
    assert operating.value.code == "MODEL_VERSION_UNSUPPORTED"
    valuation = make_valuation().model_copy(
        update={"model_id": model, "model_version": version}
    )
    with pytest.raises(CalculationRefusal) as calculation:
        calculate(valuation)
    assert calculation.value.code == "MODEL_VERSION_UNSUPPORTED"


@pytest.mark.parametrize(
    "change",
    (
        {"formula_graph": "unimplemented-graph-v999"},
        {"numerical_policy": "unimplemented-numerics-v999"},
    ),
)
def test_specifications_must_match_the_executed_graph_and_numerical_policy(
    monkeypatch, change
):
    req = request()
    specs = initial_model_specs()
    monkeypatch.setattr(
        operating_projection,
        "initial_model_specs",
        lambda: tuple(spec.model_copy(update=change) for spec in specs),
    )
    with pytest.raises(ValidationError, match="differs from the executable"):
        OperatingScenarioRequestV1.model_validate(req.model_dump())
    with pytest.raises(OperatingProjectionError) as scenario:
        replay_operating_scenarios(req)
    assert scenario.value.code == "MODEL_SPEC_EXECUTION_MISMATCH"
    with pytest.raises(OperatingProjectionError) as exact:
        prepare(operating_facts())
    assert exact.value.code == "MODEL_SPEC_EXECUTION_MISMATCH"
    with pytest.raises(CalculationRefusal) as calculation:
        calculate(make_valuation())
    assert calculation.value.code == "MODEL_SPEC_EXECUTION_MISMATCH"
