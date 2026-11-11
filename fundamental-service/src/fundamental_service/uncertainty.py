"""Explicit scenario, sensitivity, and seeded Monte Carlo execution."""

from __future__ import annotations

import math
import random
from decimal import Decimal
from statistics import NormalDist
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .calculator import CalculationRefusal, calculate
from .contracts import (
    ArtifactReferenceV1,
    CalculationArtifactV1,
    DistributionParameterV1,
    QualityStatus,
    ScenarioInputV1,
    SensitivityInputV1,
    UncertaintyV1,
    ValuationInputV1,
)
from .numerical_policy import using_valuation_context
from .serialization import sha256_digest

ScenarioV1 = ScenarioInputV1
SensitivityRequestV1 = SensitivityInputV1


class MonteCarloRequestV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    uncertainty: UncertaintyV1
    sampler_version: Literal["python-random-v1"] = "python-random-v1"

    @model_validator(mode="after")
    def requires_monte_carlo(self) -> MonteCarloRequestV1:
        if self.uncertainty.mode != "monte_carlo":
            raise ValueError("Monte Carlo request requires mode monte_carlo")
        return self


class UncertaintyReportV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: QualityStatus
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_hash: str = Field(default="0" * 64, pattern=r"^[0-9a-f]{64}$")
    base: CalculationArtifactV1
    scenario_results: tuple[CalculationArtifactV1, ...] = ()
    sensitivity: dict[str, tuple[object, ...]] = Field(default_factory=dict)
    requested_samples: int = 0
    valid_samples: int = 0
    invalid_samples: int = 0
    invalid_reasons: dict[str, int] = {}
    invalid_draw_policy: str | None = None
    seed: int | None = None
    sampler_version: str | None = None
    quantiles: dict[str, object] = Field(default_factory=dict)
    quantile_contract: dict[str, str] = Field(
        default_factory=lambda: {"bear": "p05", "base": "p50", "bull": "p95"}
    )
    convergence_diagnostics: dict[str, object] = Field(default_factory=dict)
    dominant_drivers: tuple[str, ...] = ()
    artifact_references: tuple[ArtifactReferenceV1, ...] = ()


class UncertaintyEvidenceV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["fundamental.v1"] = "fundamental.v1"
    request: dict[str, object]
    report: UncertaintyReportV1

    @model_validator(mode="after")
    def evidence_is_digest_bound(self) -> UncertaintyEvidenceV1:
        if "caller_approval" in self.request:
            raise ValueError("caller approval evidence must not be persisted")
        if sha256_digest(self.request) != self.report.input_digest:
            raise ValueError(
                "uncertainty evidence request digest does not match report"
            )
        uncertainty = self.request.get("uncertainty")
        if not isinstance(uncertainty, dict) or uncertainty.get("mode") == "none":
            raise ValueError("uncertainty evidence must contain caller controls")
        return self


def _path_value(request: ValuationInputV1, path: str) -> object:
    if path == "assumptions.terminal_growth":
        return request.assumptions.terminal_growth
    prefix = "assumptions.forecast."
    if path.startswith(prefix) and path.count("[") == 1 and path.endswith("]"):
        field, index_text = path[len(prefix) :].split("[")
        index = int(index_text[:-1])
        values = getattr(request.assumptions.forecast, field, None)
        if values is None or not 0 <= index < len(values):
            raise ValueError(f"unsupported assumption path: {path}")
        return values[index]
    prefix = "assumptions.wacc."
    if path.startswith(prefix):
        value = getattr(request.assumptions.wacc, path[len(prefix) :], None)
        if value is None:
            raise ValueError(f"unsupported assumption path: {path}")
        return value
    raise ValueError(f"unsupported assumption path: {path}")


def _with_path(request: ValuationInputV1, path: str, value: object) -> ValuationInputV1:
    if isinstance(value, str):
        value = Decimal(value)
    _path_value(request, path)
    if path == "assumptions.terminal_growth":
        assumptions = request.assumptions.model_copy(update={"terminal_growth": value})
    elif path.startswith("assumptions.forecast."):
        if request.assumptions.forecast is None:
            raise ValueError(f"unsupported assumption path: {path}")
        field, index_text = path[len("assumptions.forecast.") :].split("[")
        index = int(index_text[:-1])
        values = list(getattr(request.assumptions.forecast, field))
        values[index] = value
        forecast = request.assumptions.forecast.model_copy(
            update={field: tuple(values)}
        )
        assumptions = request.assumptions.model_copy(update={"forecast": forecast})
    elif path.startswith("assumptions.wacc."):
        if request.assumptions.wacc is None:
            raise ValueError(f"unsupported assumption path: {path}")
        field = path[len("assumptions.wacc.") :]
        wacc = request.assumptions.wacc.model_copy(update={field: value})
        assumptions = request.assumptions.model_copy(update={"wacc": wacc})
    else:
        raise ValueError(f"unsupported assumption path: {path}")
    return request.model_copy(update={"assumptions": assumptions}).with_digest()


def _draw(
    parameter: DistributionParameterV1, rng: random.Random, z: float | None = None
) -> Decimal:
    lower, upper = parameter.lower, parameter.upper
    assert lower is not None and upper is not None
    if parameter.distribution == "uniform":
        ratio = rng.random() if z is None else NormalDist().cdf(z)
        return lower + (upper - lower) * Decimal(str(ratio))
    if parameter.distribution == "triangular":
        assert parameter.mode is not None
        return Decimal(
            str(rng.triangular(float(lower), float(upper), float(parameter.mode)))
        )
    assert parameter.mean is not None
    mean = float(parameter.mean)
    spread = float((upper - lower) / 6)
    z = rng.gauss(0, 1) if z is None else z
    value = (
        math.exp(mean + spread * z)
        if parameter.distribution == "lognormal"
        else mean + spread * z
    )
    return Decimal(str(value))


def _per_share(request: ValuationInputV1, allow_provisional: bool) -> Decimal:
    value = calculate(request, allow_provisional=allow_provisional).per_share_value
    assert value is not None
    return value


def _draws(spec: UncertaintyV1, rng: random.Random) -> tuple[Decimal, ...]:
    if not spec.correlations:
        return tuple(_draw(parameter, rng) for parameter in spec.parameters)
    indexes = {parameter.path: index for index, parameter in enumerate(spec.parameters)}
    z_values = [rng.gauss(0, 1) for _ in spec.parameters]
    for left, right, correlation in spec.correlations:
        left_index, right_index = indexes[left], indexes[right]
        coefficient = float(correlation)
        z_values[right_index] = (
            coefficient * z_values[left_index]
            + math.sqrt(1 - coefficient**2) * z_values[right_index]
        )
    return tuple(
        _draw(parameter, rng, z)
        for parameter, z in zip(spec.parameters, z_values, strict=True)
    )


def _report_result_hash(report: UncertaintyReportV1) -> str:
    return sha256_digest(
        {
            "status": report.status,
            "input_digest": report.input_digest,
            "base_result_hash": report.base.result_hash,
            "scenario_result_hashes": tuple(
                item.result_hash for item in report.scenario_results
            ),
            "sensitivity": report.sensitivity,
            "requested_samples": report.requested_samples,
            "valid_samples": report.valid_samples,
            "invalid_samples": report.invalid_samples,
            "invalid_reasons": report.invalid_reasons,
            "invalid_draw_policy": report.invalid_draw_policy,
            "seed": report.seed,
            "sampler_version": report.sampler_version,
            "quantiles": report.quantiles,
            "quantile_contract": report.quantile_contract,
            "convergence_diagnostics": report.convergence_diagnostics,
            "dominant_drivers": report.dominant_drivers,
        }
    )


def _with_report_result_hash(report: UncertaintyReportV1) -> UncertaintyReportV1:
    return report.model_copy(update={"result_hash": _report_result_hash(report)})


def is_service_owned_monte_carlo(request: ValuationInputV1) -> bool:
    return request.uncertainty.mode == "monte_carlo" and (
        request.uncertainty.policy_version is not None
        and all(
            parameter.provenance is not None
            for parameter in request.uncertainty.parameters
        )
    )


def validate_uncertainty_controls(
    request: ValuationInputV1,
    *,
    scenarios: tuple[ScenarioV1, ...] = (),
    sensitivity: tuple[SensitivityRequestV1, ...] = (),
) -> None:
    declared_scenarios = scenarios or tuple(
        ScenarioV1.model_validate(item) for item in request.uncertainty.scenarios
    )
    declared_sensitivity = sensitivity or tuple(
        SensitivityRequestV1.model_validate(item)
        for item in request.uncertainty.sensitivity
    )
    if request.uncertainty.mode == "scenarios" and not (
        declared_scenarios or declared_sensitivity
    ):
        raise ValueError("scenarios mode requires scenario or sensitivity inputs")


@using_valuation_context
def run_uncertainty(
    request: ValuationInputV1,
    *,
    monte_carlo: MonteCarloRequestV1 | None = None,
    scenarios: tuple[ScenarioV1, ...] = (),
    sensitivity: tuple[SensitivityRequestV1, ...] = (),
    base_result: CalculationArtifactV1 | None = None,
    input_digest: str | None = None,
    allow_provisional: bool = False,
) -> UncertaintyReportV1:
    validate_uncertainty_controls(
        request,
        scenarios=scenarios,
        sensitivity=sensitivity,
    )
    scenarios = scenarios or tuple(
        ScenarioV1.model_validate(item) for item in request.uncertainty.scenarios
    )
    sensitivity = sensitivity or tuple(
        SensitivityRequestV1.model_validate(item)
        for item in request.uncertainty.sensitivity
    )
    if monte_carlo is None and request.uncertainty.mode == "monte_carlo":
        monte_carlo = MonteCarloRequestV1(uncertainty=request.uncertainty)
    deterministic_request = (
        request.base_input() if hasattr(request, "base_input") else request
    )
    deterministic_request = deterministic_request.model_copy(
        update={
            "uncertainty": UncertaintyV1(mode="none"),
            "caller_approval": None,
            "input_digest": None,
        }
    ).with_digest()
    base = base_result or calculate(
        deterministic_request,
        allow_provisional=allow_provisional,
    )
    resolved_digest = (
        input_digest or request.input_digest or request.with_digest().input_digest
    )
    assert resolved_digest is not None
    scenario_results: list[CalculationArtifactV1] = []
    if scenarios:
        if {scenario.name for scenario in scenarios} != {"base", "downside", "upside"}:
            raise ValueError(
                "scenarios must include base, downside, and upside exactly once"
            )
        for scenario in scenarios:
            scenario_request = deterministic_request
            for path, value in scenario.assumptions.items():
                scenario_request = _with_path(scenario_request, path, value)
            scenario_results.append(
                calculate(scenario_request, allow_provisional=allow_provisional)
            )
    sensitivity_results: dict[str, tuple[object, ...]] = {}
    spreads: list[tuple[str, Decimal]] = []
    for item in sensitivity:
        sensitivity_values = tuple(
            _per_share(
                _with_path(deterministic_request, item.path, value), allow_provisional
            )
            for value in item.values
        )
        sensitivity_results[item.path] = sensitivity_values
        spreads.append((item.path, max(sensitivity_values) - min(sensitivity_values)))
    dominant = tuple(
        path for path, _ in sorted(spreads, key=lambda pair: pair[1], reverse=True)
    )
    if monte_carlo is None:
        return _with_report_result_hash(
            UncertaintyReportV1(
                status=QualityStatus.VERIFIED,
                input_digest=resolved_digest,
                base=base,
                scenario_results=tuple(scenario_results),
                sensitivity=sensitivity_results,
                dominant_drivers=dominant,
            )
        )
    spec = monte_carlo.uncertainty
    rng = random.Random(spec.seed)
    values: list[Decimal] = []
    invalid: dict[str, int] = {}
    for _ in range(spec.samples or 0):
        draw = _draws(spec, rng)
        if any(
            value < parameter.lower or value > parameter.upper
            for value, parameter in zip(draw, spec.parameters, strict=True)
        ):
            invalid["OUT_OF_BOUNDS"] = invalid.get("OUT_OF_BOUNDS", 0) + 1
            continue
        try:
            sampled = deterministic_request
            for parameter, value in zip(spec.parameters, draw, strict=True):
                sampled = _with_path(sampled, parameter.path, value)
            values.append(_per_share(sampled, allow_provisional))
        except (CalculationRefusal, ValueError):
            invalid["CALCULATION_REFUSAL"] = invalid.get("CALCULATION_REFUSAL", 0) + 1
    minimum = max(2, min(spec.samples or 2, 10))
    requested_samples = spec.samples or 0
    invalid_samples = sum(invalid.values())
    invalid_ratio = invalid_samples / max(1, requested_samples)
    sorted_values = sorted(values)
    if len(values) < minimum or (
        spec.invalid_draw_policy in {"abstain", "reject"} and invalid
    ):
        status = QualityStatus.ABSTAIN
    elif invalid and spec.invalid_draw_policy == "skip":
        status = QualityStatus.DEGRADED
    else:
        status = request.quality.status
    quantiles: dict[str, object] = {}
    if sorted_values:
        lower = sorted_values[max(0, math.ceil(len(sorted_values) * 0.05) - 1)]
        median = sorted_values[max(0, math.ceil(len(sorted_values) * 0.50) - 1)]
        upper = sorted_values[max(0, math.ceil(len(sorted_values) * 0.95) - 1)]
        quantiles = {
            "p05": lower,
            "p50": median,
            "p95": upper,
            "lower": lower,
            "median": median,
            "upper": upper,
        }
    diagnostics = {
        "minimum_valid_samples": minimum,
        "invalid_ratio": str(invalid_ratio),
        "converged": len(values) >= minimum,
    }
    return _with_report_result_hash(
        UncertaintyReportV1(
            status=status,
            input_digest=resolved_digest,
            base=base,
            scenario_results=tuple(scenario_results),
            sensitivity=sensitivity_results,
            requested_samples=requested_samples,
            valid_samples=len(values),
            invalid_samples=invalid_samples,
            invalid_reasons=invalid,
            invalid_draw_policy=spec.invalid_draw_policy,
            seed=spec.seed,
            sampler_version=monte_carlo.sampler_version,
            quantiles=quantiles,
            convergence_diagnostics=diagnostics,
            dominant_drivers=dominant,
        )
    )
