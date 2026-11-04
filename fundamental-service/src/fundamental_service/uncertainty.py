"""Explicit scenario, sensitivity, and seeded Monte Carlo execution."""

from __future__ import annotations

import math
import random
from decimal import Decimal
from statistics import NormalDist
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from .calculator import CalculationRefusal, calculate
from .contracts import (
    CalculationArtifactV1,
    QualityStatus,
    ScenarioInputV1,
    SensitivityInputV1,
    UncertaintyV1,
    ValuationInputV1,
)

ScenarioV1 = ScenarioInputV1
SensitivityRequestV1 = SensitivityInputV1


class MonteCarloRequestV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    uncertainty: UncertaintyV1
    sampler_version: Literal["python-random-v1"] = "python-random-v1"

    @model_validator(mode="after")
    def requires_monte_carlo(self) -> "MonteCarloRequestV1":
        if self.uncertainty.mode != "monte_carlo":
            raise ValueError("Monte Carlo request requires mode monte_carlo")
        return self


class UncertaintyReportV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: QualityStatus
    base: CalculationArtifactV1
    scenario_results: tuple[CalculationArtifactV1, ...] = ()
    sensitivity: dict[str, tuple[object, ...]] = {}
    requested_samples: int = 0
    valid_samples: int = 0
    invalid_samples: int = 0
    invalid_reasons: dict[str, int] = {}
    invalid_draw_policy: str | None = None
    seed: int | None = None
    sampler_version: str | None = None
    quantiles: dict[str, object] = {}
    convergence_diagnostics: dict[str, object] = {}
    dominant_drivers: tuple[str, ...] = ()


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
        field, index_text = path[len("assumptions.forecast.") :].split("[")
        index = int(index_text[:-1])
        values = list(getattr(request.assumptions.forecast, field))
        values[index] = value
        forecast = request.assumptions.forecast.model_copy(
            update={field: tuple(values)}
        )
        assumptions = request.assumptions.model_copy(update={"forecast": forecast})
    elif path.startswith("assumptions.wacc."):
        field = path[len("assumptions.wacc.") :]
        wacc = request.assumptions.wacc.model_copy(update={field: value})
        assumptions = request.assumptions.model_copy(update={"wacc": wacc})
    else:
        raise ValueError(f"unsupported assumption path: {path}")
    return request.model_copy(update={"assumptions": assumptions}).with_digest()


def _draw(parameter, rng: random.Random, z: float | None = None):
    lower, upper = parameter.lower, parameter.upper
    if parameter.distribution == "uniform":
        ratio = rng.random() if z is None else NormalDist().cdf(z)
        return lower + (upper - lower) * Decimal(str(ratio))
    if parameter.distribution == "triangular":
        return Decimal(
            str(rng.triangular(float(lower), float(upper), float(parameter.mode)))
        )
    mean = float(parameter.mean)
    spread = float((upper - lower) / 6)
    z = rng.gauss(0, 1) if z is None else z
    value = (
        math.exp(mean + spread * z)
        if parameter.distribution == "lognormal"
        else mean + spread * z
    )
    return Decimal(str(value))


def _draws(spec: UncertaintyV1, rng: random.Random) -> tuple[object, ...]:
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


def run_uncertainty(
    request: ValuationInputV1,
    *,
    monte_carlo: MonteCarloRequestV1 | None = None,
    scenarios: tuple[ScenarioV1, ...] = (),
    sensitivity: tuple[SensitivityRequestV1, ...] = (),
) -> UncertaintyReportV1:
    scenarios = scenarios or tuple(
        ScenarioV1.model_validate(item) for item in request.uncertainty.scenarios
    )
    sensitivity = sensitivity or tuple(
        SensitivityRequestV1.model_validate(item)
        for item in request.uncertainty.sensitivity
    )
    if monte_carlo is None and request.uncertainty.mode == "monte_carlo":
        monte_carlo = MonteCarloRequestV1(uncertainty=request.uncertainty)
    deterministic_request = request.model_copy(
        update={"uncertainty": UncertaintyV1(mode="none")}
    ).with_digest()
    base = calculate(deterministic_request)
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
            scenario_results.append(calculate(scenario_request))
    sensitivity_results: dict[str, tuple[object, ...]] = {}
    spreads: list[tuple[str, object]] = []
    for item in sensitivity:
        values = tuple(
            calculate(
                _with_path(deterministic_request, item.path, value)
            ).per_share_value
            for value in item.values
        )
        sensitivity_results[item.path] = values
        spreads.append((item.path, max(values) - min(values)))
    dominant = tuple(
        path for path, _ in sorted(spreads, key=lambda pair: pair[1], reverse=True)
    )
    if monte_carlo is None:
        return UncertaintyReportV1(
            status=QualityStatus.VERIFIED,
            base=base,
            scenario_results=tuple(scenario_results),
            sensitivity=sensitivity_results,
            dominant_drivers=dominant,
        )
    spec = monte_carlo.uncertainty
    rng = random.Random(spec.seed)
    values: list[object] = []
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
            values.append(calculate(sampled).per_share_value)
        except (CalculationRefusal, ValueError):
            invalid["CALCULATION_REFUSAL"] = invalid.get("CALCULATION_REFUSAL", 0) + 1
            if spec.invalid_draw_policy == "abstain":
                break
    minimum = max(2, min(spec.samples or 2, 10))
    sorted_values = sorted(values)
    status = (
        QualityStatus.VERIFIED
        if len(values) >= minimum
        and not (invalid and spec.invalid_draw_policy == "reject")
        else QualityStatus.ABSTAIN
    )
    quantiles: dict[str, object] = {}
    if sorted_values:
        quantiles = {
            "p05": sorted_values[max(0, int(len(sorted_values) * 0.05) - 1)],
            "p50": sorted_values[len(sorted_values) // 2],
            "p95": sorted_values[
                min(len(sorted_values) - 1, int(len(sorted_values) * 0.95))
            ],
        }
    diagnostics = {
        "minimum_valid_samples": minimum,
        "invalid_ratio": str(sum(invalid.values()) / max(1, spec.samples or 1)),
        "converged": len(values) >= minimum,
    }
    return UncertaintyReportV1(
        status=status,
        base=base,
        scenario_results=tuple(scenario_results),
        sensitivity=sensitivity_results,
        requested_samples=spec.samples or 0,
        valid_samples=len(values),
        invalid_samples=sum(invalid.values()),
        invalid_reasons=invalid,
        invalid_draw_policy=spec.invalid_draw_policy,
        seed=spec.seed,
        sampler_version=monte_carlo.sampler_version,
        quantiles=quantiles,
        convergence_diagnostics=diagnostics,
        dominant_drivers=dominant,
    )
