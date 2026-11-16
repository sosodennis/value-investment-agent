import ast
from decimal import Decimal
from pathlib import Path

import pytest

from fundamental_service.calculator import calculation_result_hash
from fundamental_service.contracts import (
    QualityStatus,
    ScenarioInputV1,
    SensitivityInputV1,
    UncertaintyV1,
)
from fundamental_service.scenario_verification import (
    main,
    verify_conditional_arithmetic,
)
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.testsupport import make_valuation
from fundamental_service.uncertainty import run_uncertainty
from fundamental_service.verification import VerificationRefusal


def _request(quality=QualityStatus.PROVISIONAL):
    request = make_valuation()
    controls = UncertaintyV1(
        mode="scenarios",
        scenarios=(
            ScenarioInputV1(name="base"),
            ScenarioInputV1(
                name="downside",
                assumptions={
                    "assumptions.wacc.debt_weight": "0.4",
                    "assumptions.wacc.equity_weight": "0.6",
                    "assumptions.capital_bridge.diluted_shares": "125",
                    "assumptions.capital_bridge.preferred_stock": "20",
                    "assumptions.forecast.reinvestment_rate[0]": "0.6",
                },
            ),
            ScenarioInputV1(
                name="upside",
                assumptions={
                    "assumptions.forecast.revenue_growth[0]": "0.1",
                    "assumptions.forecast.operating_margin[0]": "0.3",
                    "assumptions.terminal_growth": "0.03",
                },
            ),
        ),
        sensitivity=(
            SensitivityInputV1(
                path="assumptions.capital_bridge.preferred_stock", values=("0", "10")
            ),
            SensitivityInputV1(
                path="assumptions.forecast.reinvestment_rate[0]", values=("0.2", "0.6")
            ),
        ),
    )
    return request.model_copy(
        update={
            "quality": request.quality.model_copy(update={"status": quality}),
            "uncertainty": controls,
        }
    ).with_digest()


@pytest.mark.parametrize("quality", [QualityStatus.VERIFIED, QualityStatus.PROVISIONAL])
def test_joint_scenarios_and_sensitivity_match_without_upgrading_quality(quality):
    request = _request(quality)
    original = canonical_bytes(request)
    report = run_uncertainty(request, allow_provisional=True)

    first = verify_conditional_arithmetic(request, report)
    second = verify_conditional_arithmetic(request, report)

    assert first.status == "pass"
    assert first.findings == ()
    assert first.quality_status is quality
    assert first.input_digest == request.input_digest
    assert first.checked_scenarios == ("base", "downside", "upside")
    assert len(first.checked_sensitivity_paths) == 2
    assert first.limitations
    assert first.digest == second.digest
    assert canonical_bytes(request) == original


def _rehash(report):
    payload = report.model_dump(
        exclude={"result_hash", "base", "scenario_results", "artifact_references"}
    )
    payload.update(
        base_result_hash=report.base.result_hash,
        scenario_result_hashes=tuple(
            item.result_hash for item in report.scenario_results
        ),
    )
    return report.model_copy(update={"result_hash": sha256_digest(payload)})


@pytest.mark.parametrize(
    "mutation,expected",
    [
        ("base-node", "base:fcff_1:value"),
        ("scenario-node", "scenario:downside:fcff_1:value"),
        ("scenario-input", "scenario:downside:input_digest"),
        (
            "sensitivity",
            "sensitivity:assumptions.capital_bridge.preferred_stock:0:value",
        ),
        ("input", "input_digest"),
        ("quality", "quality"),
        ("scenario-count", "scenarios:count"),
        (
            "sensitivity-count",
            "sensitivity:assumptions.capital_bridge.preferred_stock:count",
        ),
        ("sampling", "unexpected_sampling_metadata"),
        ("result-hash", "result_hash"),
    ],
)
def test_rejects_altered_results_even_after_valid_rehash(mutation, expected):
    request = _request()
    report = run_uncertainty(request, allow_provisional=True)
    if mutation in {"base-node", "scenario-node", "scenario-input"}:
        artifact = (
            report.base if mutation == "base-node" else report.scenario_results[1]
        )
        if mutation == "scenario-input":
            artifact = artifact.model_copy(update={"input_digest": "0" * 64})
        else:
            nodes = tuple(
                node.model_copy(update={"value": node.value + Decimal(100)})
                if node.node_id == "fcff_1"
                else node
                for node in artifact.nodes
            )
            artifact = artifact.model_copy(update={"nodes": nodes})
        artifact = artifact.model_copy(
            update={"result_hash": calculation_result_hash(artifact)}
        )
        report = report.model_copy(
            update={"base": artifact}
            if mutation == "base-node"
            else {
                "scenario_results": (
                    report.scenario_results[0],
                    artifact,
                    report.scenario_results[2],
                )
            }
        )
    elif mutation.startswith("sensitivity"):
        values = dict(report.sensitivity)
        path = next(iter(values))
        values[path] = ("999", values[path][1]) if mutation == "sensitivity" else ()
        report = report.model_copy(update={"sensitivity": values})
    else:
        changes = {
            "input": {"input_digest": "0" * 64},
            "quality": {"status": QualityStatus.VERIFIED},
            "scenario-count": {"scenario_results": report.scenario_results[:-1]},
            "sampling": {"requested_samples": 1},
            "result-hash": {},
        }
        report = report.model_copy(update=changes[mutation])
    report = _rehash(report)
    if mutation == "result-hash":
        report = report.model_copy(update={"result_hash": "0" * 64})

    check = verify_conditional_arithmetic(request, report)

    assert check.status == "fail"
    assert expected in check.findings


@pytest.mark.parametrize("quality", [QualityStatus.ABSTAIN, QualityStatus.DEGRADED])
def test_refuses_ineligible_quality(quality):
    good = _request()
    report = run_uncertainty(good, allow_provisional=True)
    with pytest.raises(VerificationRefusal) as caught:
        verify_conditional_arithmetic(_request(quality), report)
    assert caught.value.code == "QUALITY_NOT_VERIFIED"


def test_sensitivity_only_is_checked_and_other_uncertainty_modes_are_refused():
    request = _request()
    request = request.model_copy(
        update={"uncertainty": request.uncertainty.model_copy(update={"scenarios": ()})}
    ).with_digest()
    report = run_uncertainty(request, allow_provisional=True)
    assert verify_conditional_arithmetic(request, report).status == "pass"
    for controls in (
        UncertaintyV1(mode="none"),
        UncertaintyV1(
            mode="monte_carlo",
            samples=10,
            seed=42,
            invalid_draw_policy="reject",
            parameters=(
                {
                    "path": "assumptions.terminal_growth",
                    "distribution": "uniform",
                    "lower": Decimal("0.01"),
                    "upper": Decimal("0.03"),
                },
            ),
        ),
    ):
        other = request.model_copy(update={"uncertainty": controls}).with_digest()
        with pytest.raises(VerificationRefusal) as caught:
            verify_conditional_arithmetic(other, report)
        assert caught.value.code == "SCOPE_UNSUPPORTED"


@pytest.mark.parametrize(
    "path,value,code",
    [
        ("assumptions.forecast.base_revenue", "200", "SCENARIO_PATH_UNSUPPORTED"),
        (
            "assumptions.forecast.reinvestment_rate[9]",
            "0.5",
            "SCENARIO_PATH_UNSUPPORTED",
        ),
        ("assumptions.terminal_growth", "NaN", "SCENARIO_VALUE_INVALID"),
        ("assumptions.terminal_growth", True, "SCENARIO_VALUE_INVALID"),
        ("assumptions.capital_bridge.cash", "-1", "SCENARIO_VALUE_INVALID"),
    ],
)
def test_refuses_unsupported_or_invalid_scenario_operands(path, value, code):
    request = _request()
    report = run_uncertainty(request, allow_provisional=True)
    scenarios = request.uncertainty.scenarios
    controls = request.uncertainty.model_copy(
        update={
            "scenarios": (
                scenarios[0].model_copy(update={"assumptions": {path: value}}),
                *scenarios[1:],
            )
        }
    )
    request = request.model_copy(update={"uncertainty": controls}).with_digest()
    with pytest.raises(VerificationRefusal) as caught:
        verify_conditional_arithmetic(request, report)
    assert caught.value.code == code


def test_cli_checks_retained_files_and_preserves_limitations(tmp_path, capsys):
    request = _request()
    report = run_uncertainty(request, allow_provisional=True)
    input_path, report_path, output_path = (
        tmp_path / name for name in ("input.json", "report.json", "check.json")
    )
    input_path.write_bytes(canonical_bytes(request))
    report_path.write_bytes(canonical_bytes(report))
    assert (
        main(
            [
                "--request",
                str(input_path),
                "--production-report",
                str(report_path),
                "--output",
                str(output_path),
            ]
        )
        == 0
    )
    assert output_path.read_text() == capsys.readouterr().out.strip()
    assert '"scope":"conditional-arithmetic-v1"' in output_path.read_text()
    assert '"quality_status":"provisional"' in output_path.read_text()


def test_challenger_imports_only_uncertainty_schema_and_no_production_calculator():
    source = (
        Path(__file__).parents[1] / "src/fundamental_service/scenario_verification.py"
    )
    tree = ast.parse(source.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.endswith("calculator")
            if node.module.endswith("uncertainty"):
                assert {item.name for item in node.names} == {"UncertaintyReportV1"}
