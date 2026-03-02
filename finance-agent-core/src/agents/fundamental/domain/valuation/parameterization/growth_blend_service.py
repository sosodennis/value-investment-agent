from __future__ import annotations

from collections.abc import Mapping

from src.shared.kernel.traceable import (
    ManualProvenance,
    TraceableField,
)

from ..policies.growth_assumption_policy import (
    blend_growth_rate,
    project_growth_rate_series,
)
from .series_service import (
    computed_field,
    growth_observations_from_series,
    growth_rates_from_series,
    population_stddev,
)
from .snapshot_service import market_float


def build_saas_growth_rates(
    *,
    revenue_series: list[TraceableField[float]],
    market_snapshot: Mapping[str, object] | None,
    assumptions: list[str],
    projection_years: int,
    long_run_target: float,
    high_growth_trigger: float,
) -> TraceableField[list[float]]:
    historical_growth_tf = growth_rates_from_series(
        "Revenue Growth Rates (Historical Baseline)",
        revenue_series,
        projection_years,
    )

    historical_growth = None
    if historical_growth_tf.value:
        historical_growth = float(historical_growth_tf.value[0])

    historical_observations = growth_observations_from_series(revenue_series)
    historical_volatility = population_stddev(historical_observations)
    consensus_growth = market_float(market_snapshot, "consensus_growth_rate")

    blend_result = blend_growth_rate(
        historical_growth=historical_growth,
        consensus_growth=consensus_growth,
        historical_volatility=historical_volatility,
    )
    if blend_result is None:
        return historical_growth_tf

    blended_series = project_growth_rate_series(
        base_growth=blend_result.blended_growth,
        projection_years=projection_years,
        long_run_target=long_run_target,
        high_growth_trigger=high_growth_trigger,
    )

    blend_inputs: dict[str, TraceableField] = {}
    if historical_growth_tf.value is not None:
        blend_inputs["historical_growth"] = historical_growth_tf
    if consensus_growth is not None:
        provider_raw = (
            None if market_snapshot is None else market_snapshot.get("provider")
        )
        provider = provider_raw if isinstance(provider_raw, str) else "market_data"
        consensus_tf = TraceableField(
            name="Consensus Revenue Growth",
            value=consensus_growth,
            provenance=ManualProvenance(
                description=f"Consensus growth from market data provider={provider}",
                author="MarketDataService",
            ),
        )
        blend_inputs["consensus_growth"] = consensus_tf

    assumptions.append(
        "growth_rates blended via context-aware weights "
        f"(profile={blend_result.weights.profile})"
    )

    return computed_field(
        name="Revenue Growth Rates",
        value=blended_series,
        op_code="GROWTH_BLEND",
        expression=blend_result.rationale,
        inputs=blend_inputs,
    )
