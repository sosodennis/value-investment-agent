"""Independent arithmetic checks for retained provisional FCFF scenario reports."""

from __future__ import annotations

import argparse
import re
from collections.abc import Mapping
from dataclasses import asdict
from decimal import Decimal, DecimalException
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict

from .contracts import (
    CalculationArtifactV1,
    CapitalBridgeAssumptionsV1,
    QualityStatus,
    UncertaintyV1,
    ValuationInputV1,
    WaccAssumptionsV1,
)
from .numerical_policy import using_valuation_context
from .serialization import canonical_bytes, sha256_digest
from .verification import (
    PER_SHARE_TOLERANCE,
    VerificationRefusal,
    _within,
    compare_artifact,
    independent_calculate,
)

if TYPE_CHECKING:
    from .uncertainty import UncertaintyReportV1


class ConditionalArithmeticCheckV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scope: Literal["conditional-arithmetic-v1"] = "conditional-arithmetic-v1"
    status: Literal["pass", "fail"]
    input_digest: str
    production_report_digest: str
    reference_digest: str
    quality_status: QualityStatus
    checked_scenarios: tuple[str, ...]
    checked_sensitivity_paths: tuple[str, ...]
    findings: tuple[str, ...]
    limitations: tuple[str, ...] = (
        "Arithmetic agreement only; source completeness and usage rights are not certified.",
        "Provisional quality and what-if assumptions remain unchanged.",
        "No forecast calibration, error bounds, historical performance or caller approval is certified.",
    )

    @property
    def digest(self) -> str:
        return sha256_digest(self)


def _number(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (Decimal, str, int, float)):
        raise VerificationRefusal("SCENARIO_VALUE_INVALID", "finite numbers required")
    try:
        number = Decimal(str(value))
    except DecimalException as error:
        raise VerificationRefusal(
            "SCENARIO_VALUE_INVALID", "finite numbers required"
        ) from error
    if not number.is_finite():
        raise VerificationRefusal("SCENARIO_VALUE_INVALID", "finite numbers required")
    return number


def _variant(
    request: ValuationInputV1, changes: Mapping[str, object]
) -> ValuationInputV1:
    payload = request.model_dump(exclude={"caller_approval", "input_digest"})
    assumptions = payload["assumptions"]
    for path, value in changes.items():
        number = _number(value)
        parts = path.split(".")
        if parts == ["assumptions", "terminal_growth"]:
            assumptions["terminal_growth"] = number
            continue
        if len(parts) == 3 and parts[0] == "assumptions":
            group, field = parts[1:]
            fields = (
                WaccAssumptionsV1.model_fields
                if group == "wacc"
                else CapitalBridgeAssumptionsV1.model_fields
                if group == "capital_bridge"
                else {}
            )
            if field in fields:
                if group == "capital_bridge" and number < 0:
                    raise VerificationRefusal(
                        "SCENARIO_VALUE_INVALID", "capital operands must be nonnegative"
                    )
                assumptions[group][field] = number
                continue
        match = re.fullmatch(
            r"assumptions\.forecast\.(revenue_growth|operating_margin|reinvestment_rate)\[(0|[1-9][0-9]*)\]",
            path,
        )
        if match is not None:
            field, index_text = match.groups()
            values = list(assumptions["forecast"][field])
            index = int(index_text)
            if index < len(values):
                values[index] = number
                assumptions["forecast"][field] = tuple(values)
                continue
        raise VerificationRefusal(
            "SCENARIO_PATH_UNSUPPORTED", "unsupported assumption path"
        )
    payload["uncertainty"] = UncertaintyV1(mode="none")
    return ValuationInputV1.model_validate(payload).with_digest()


def _artifact_findings(
    request: ValuationInputV1, artifact: CalculationArtifactV1
) -> tuple[str, ...]:
    reference = independent_calculate(request, scope="conditional-arithmetic-v1")
    findings = list(compare_artifact(reference, artifact))
    for name, actual, expected in (
        ("input_digest", artifact.input_digest, request.input_digest),
        ("quality", artifact.quality_status, request.quality.status),
        ("completion", artifact.calculation_status.value, "completed"),
        ("assumptions", artifact.assumptions, request.assumptions),
        ("snapshot", artifact.snapshot_id, request.valuation_context.data_snapshot_id),
        (
            "valuation_timestamp",
            artifact.valuation_timestamp,
            request.valuation_context.valuation_timestamp,
        ),
        ("model_version", artifact.model_version, request.model_version),
        ("policy_id", artifact.policy_id, request.policy_id),
        ("policy_version", artifact.policy_version, request.provenance.policy_version),
        ("calculation_version", artifact.calculation_version, "calculator-v2"),
    ):
        if actual != expected:
            findings.append(name)
    digest = sha256_digest(
        artifact.model_dump(
            exclude={
                "result_hash",
                "artifact_references",
                "evaluated_at",
                "correlation_id",
                "policy_resolution",
            }
        )
    )
    if artifact.result_hash != digest:
        findings.append("result_hash")
    return tuple(findings)


@using_valuation_context
def verify_conditional_arithmetic(
    request: ValuationInputV1, report: UncertaintyReportV1
) -> ConditionalArithmeticCheckV1:
    """Compare each declared joint scenario and sensitivity with reference equations.

    This reads a completed report; it never admits sources, signs a release,
    invokes the production calculator, or creates caller approval.
    """
    request = ValuationInputV1.model_validate(request.model_dump()).with_digest()
    assert request.input_digest is not None
    if request.uncertainty.mode != "scenarios":
        raise VerificationRefusal("SCOPE_UNSUPPORTED", "scenario reports required")
    controls = request.uncertainty
    if not (controls.scenarios or controls.sensitivity):
        raise VerificationRefusal("SCENARIOS_MISSING", "scenario controls are empty")
    names = tuple(item.name for item in controls.scenarios)
    if names and (len(names) != 3 or set(names) != {"base", "downside", "upside"}):
        raise VerificationRefusal(
            "SCENARIOS_INVALID", "three distinct scenarios required"
        )
    paths = tuple(item.path for item in controls.sensitivity)
    if len(set(paths)) != len(paths):
        raise VerificationRefusal(
            "SENSITIVITY_INVALID", "sensitivity paths must be unique"
        )
    base = _variant(request, {})
    reference = independent_calculate(base, scope="conditional-arithmetic-v1")
    findings = ["base:" + item for item in _artifact_findings(base, report.base)]
    if report.input_digest != request.input_digest:
        findings.append("input_digest")
    if report.status != request.quality.status:
        findings.append("quality")
    if len(report.scenario_results) != len(controls.scenarios):
        findings.append("scenarios:count")
    scenario_references = []
    for index, scenario in enumerate(controls.scenarios):
        variant = _variant(request, scenario.assumptions)
        scenario_references.append(
            independent_calculate(variant, scope="conditional-arithmetic-v1")
        )
        if index < len(report.scenario_results):
            findings.extend(
                "scenario:" + scenario.name + ":" + item
                for item in _artifact_findings(variant, report.scenario_results[index])
            )
    if set(report.sensitivity) != set(paths):
        findings.append("sensitivity:paths")
    sensitivity: dict[str, tuple[Decimal, ...]] = {}
    for item in controls.sensitivity:
        expected = tuple(
            independent_calculate(
                _variant(request, {item.path: value}), scope="conditional-arithmetic-v1"
            ).per_share_value
            for value in item.values
        )
        sensitivity[item.path] = expected
        actual = report.sensitivity.get(item.path, ())
        if len(actual) != len(expected):
            findings.append("sensitivity:" + item.path + ":count")
        for index, (value, target) in enumerate(zip(actual, expected)):
            try:
                matches = _within(_number(value), target, PER_SHARE_TOLERANCE)
            except VerificationRefusal:
                matches = False
            if not matches:
                findings.append(f"sensitivity:{item.path}:{index}:value")
    dominant = tuple(
        sorted(
            paths,
            key=lambda path: max(sensitivity[path]) - min(sensitivity[path]),
            reverse=True,
        )
    )
    if report.dominant_drivers != dominant:
        findings.append("dominant_drivers")
    if (
        report.requested_samples
        or report.valid_samples
        or report.invalid_samples
        or report.invalid_reasons
        or report.seed is not None
        or report.sampler_version is not None
        or report.invalid_draw_policy is not None
        or report.quantiles
        or report.convergence_diagnostics
    ):
        findings.append("unexpected_sampling_metadata")
    hash_payload = report.model_dump(
        exclude={"result_hash", "base", "scenario_results", "artifact_references"}
    )
    hash_payload.update(
        base_result_hash=report.base.result_hash,
        scenario_result_hashes=tuple(
            item.result_hash for item in report.scenario_results
        ),
    )
    if report.result_hash != sha256_digest(hash_payload):
        findings.append("result_hash")
    return ConditionalArithmeticCheckV1(
        status="fail" if findings else "pass",
        input_digest=request.input_digest,
        production_report_digest=sha256_digest(report),
        reference_digest=sha256_digest(
            {
                "base": asdict(reference),
                "scenarios": tuple(asdict(item) for item in scenario_references),
                "sensitivity": sensitivity,
            }
        ),
        quality_status=request.quality.status,
        checked_scenarios=names,
        checked_sensitivity_paths=paths,
        findings=tuple(findings),
    )


def main(argv: list[str] | None = None) -> int:
    from .uncertainty import UncertaintyReportV1

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--production-report", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    request = ValuationInputV1.model_validate_json(args.request.read_bytes())
    report = UncertaintyReportV1.model_validate_json(
        args.production_report.read_bytes()
    )
    check = verify_conditional_arithmetic(request, report)
    payload = canonical_bytes({"check": check, "digest": check.digest})
    if args.output:
        args.output.write_bytes(payload)
    print(payload.decode())
    return 0 if check.status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
