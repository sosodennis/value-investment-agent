from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.shared.kernel.traceable import ManualProvenance, TraceableField

# Enterprise-grade policy note:
# - Do NOT silently assume values in production.
# - Defaults are allowed only for preview/prototyping and must be surfaced for review.
# - Every assumed value must be explicitly tagged with ManualProvenance.

DEFAULT_WACC = 0.10
DEFAULT_TERMINAL_GROWTH = 0.02
DEFAULT_DA_RATE = 0.04

BASELINE_HISTORICAL_WEIGHT = 0.30
BASELINE_CONSENSUS_WEIGHT = 0.50
BASELINE_ADJUSTMENT_WEIGHT = 0.20

MATURE_HISTORICAL_WEIGHT = 0.60
MATURE_CONSENSUS_WEIGHT = 0.35
MATURE_ADJUSTMENT_WEIGHT = 0.05

VOLATILE_HISTORICAL_WEIGHT = 0.10
VOLATILE_CONSENSUS_WEIGHT = 0.80
VOLATILE_ADJUSTMENT_WEIGHT = 0.10

MATURE_VOLATILITY_THRESHOLD = 0.05
DEFAULT_LONG_RUN_GROWTH_TARGET = 0.025
DEFAULT_HIGH_GROWTH_TRIGGER = 0.30


@dataclass(frozen=True)
class GrowthBlendWeights:
    historical: float
    consensus: float
    adjustment: float
    profile: str


@dataclass(frozen=True)
class GrowthBlendResult:
    blended_growth: float
    weights: GrowthBlendWeights
    rationale: str


def resolve_growth_blend_weights(
    historical_volatility: float | None,
) -> GrowthBlendWeights:
    if historical_volatility is None:
        return GrowthBlendWeights(
            historical=BASELINE_HISTORICAL_WEIGHT,
            consensus=BASELINE_CONSENSUS_WEIGHT,
            adjustment=BASELINE_ADJUSTMENT_WEIGHT,
            profile="baseline",
        )
    if historical_volatility < MATURE_VOLATILITY_THRESHOLD:
        return GrowthBlendWeights(
            historical=MATURE_HISTORICAL_WEIGHT,
            consensus=MATURE_CONSENSUS_WEIGHT,
            adjustment=MATURE_ADJUSTMENT_WEIGHT,
            profile="mature_stable",
        )
    return GrowthBlendWeights(
        historical=VOLATILE_HISTORICAL_WEIGHT,
        consensus=VOLATILE_CONSENSUS_WEIGHT,
        adjustment=VOLATILE_ADJUSTMENT_WEIGHT,
        profile="volatile_or_cyclical",
    )


def blend_growth_rate(
    *,
    historical_growth: float | None,
    consensus_growth: float | None,
    adjustment_growth: float | None = None,
    historical_volatility: float | None = None,
) -> GrowthBlendResult | None:
    weights = resolve_growth_blend_weights(historical_volatility)

    weighted_components: list[tuple[float, float, str]] = []
    if historical_growth is not None:
        weighted_components.append(
            (historical_growth, weights.historical, "historical")
        )
    if consensus_growth is not None:
        weighted_components.append((consensus_growth, weights.consensus, "consensus"))
    if adjustment_growth is not None:
        weighted_components.append(
            (adjustment_growth, weights.adjustment, "adjustment")
        )

    if not weighted_components:
        return None

    total_weight = sum(item[1] for item in weighted_components)
    blended = sum(value * weight for value, weight, _ in weighted_components) / (
        total_weight if total_weight > 0 else 1.0
    )

    components = ", ".join(name for _, _, name in weighted_components)
    rationale = (
        f"Context-aware growth blend ({weights.profile}); components={components}; "
        f"weights(historical={weights.historical:.2f}, "
        f"consensus={weights.consensus:.2f}, adjustment={weights.adjustment:.2f})"
    )
    return GrowthBlendResult(
        blended_growth=blended,
        weights=weights,
        rationale=rationale,
    )


def project_growth_rate_series(
    *,
    base_growth: float,
    projection_years: int,
    long_run_target: float = DEFAULT_LONG_RUN_GROWTH_TARGET,
    high_growth_trigger: float = DEFAULT_HIGH_GROWTH_TRIGGER,
) -> list[float]:
    if projection_years <= 0:
        raise ValueError("projection_years must be positive")

    if base_growth <= high_growth_trigger:
        return [base_growth] * projection_years

    if projection_years == 1:
        return [max(long_run_target, base_growth)]

    step = (base_growth - long_run_target) / float(projection_years - 1)
    series: list[float] = []
    for idx in range(projection_years):
        value = base_growth - (step * idx)
        series.append(max(long_run_target, value))
    return series


def assume_rate(name: str, value: float, description: str) -> TraceableField[float]:
    return TraceableField(
        name=name,
        value=value,
        provenance=ManualProvenance(
            description=description,
            author="PolicyDefault",
            modified_at=str(datetime.now()),
        ),
    )


def assume_rate_series(
    name: str, value: float, count: int, description: str
) -> TraceableField[list[float]]:
    return TraceableField(
        name=name,
        value=[value] * count,
        provenance=ManualProvenance(
            description=description,
            author="PolicyDefault",
            modified_at=str(datetime.now()),
        ),
    )
