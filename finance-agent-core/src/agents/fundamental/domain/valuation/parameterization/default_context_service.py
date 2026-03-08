from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from src.shared.kernel.traceable import TraceableField

from .core_ops_service import (
    missing_field as _missing_field,
)
from .core_ops_service import (
    ratio as _ratio,
)
from .core_ops_service import (
    repeat_rate as _repeat_rate,
)
from .core_ops_service import (
    subtract as _subtract,
)
from .core_ops_service import (
    value_or_missing as _value_or_missing,
)
from .growth_blend_service import (
    build_saas_growth_rates as _build_saas_growth_rates_service,
)
from .market_controls_service import (
    resolve_monte_carlo_controls as _resolve_monte_carlo_controls_service,
)
from .market_controls_service import (
    resolve_shares_outstanding as _resolve_shares_outstanding_service,
)
from .model_builders.context import BuilderContext
from .series_service import (
    computed_field as _computed_field,
)
from .series_service import (
    growth_rates_from_series as _growth_rates_from_series,
)
from .snapshot_service import (
    market_float as _market_float,
)
from .snapshot_service import (
    to_float as _to_float,
)
from .types import MonteCarloControls


@dataclass(frozen=True)
class _BuilderContextDeps:
    resolve_shares_outstanding: Callable[
        [TraceableField[float], Mapping[str, object] | None, list[str]],
        TraceableField[float],
    ]
    resolve_monte_carlo_controls: Callable[
        [Mapping[str, object] | None, list[str]],
        MonteCarloControls,
    ]
    market_float: Callable[[Mapping[str, object] | None, str], float | None]
    value_or_missing: Callable[
        [TraceableField[float] | None, str, list[str]],
        float | None,
    ]
    ratio: Callable[
        [str, TraceableField[float], TraceableField[float], str],
        TraceableField[float],
    ]
    subtract: Callable[
        [str, TraceableField[float], TraceableField[float], str],
        TraceableField[float],
    ]
    build_saas_growth_rates: Callable[
        [list[TraceableField[float]], Mapping[str, object] | None, list[str]],
        TraceableField[list[float]],
    ]
    repeat_rate: Callable[
        [str, TraceableField[float], int], TraceableField[list[float]]
    ]
    missing_field: Callable[[str, str], TraceableField[float]]
    to_float: Callable[[object], float | None]
    computed_field: Callable[
        [str, float | list[float], str, str, dict[str, TraceableField]],
        TraceableField,
    ]
    growth_rates_from_series: Callable[
        [str, list[TraceableField[float]], int],
        TraceableField[list[float]],
    ]


def _build_builder_context(
    *,
    projection_years: int,
    default_market_risk_premium: float,
    default_maintenance_capex_ratio: float,
    deps: _BuilderContextDeps,
) -> BuilderContext:
    return BuilderContext(
        projection_years=projection_years,
        default_market_risk_premium=default_market_risk_premium,
        default_maintenance_capex_ratio=default_maintenance_capex_ratio,
        resolve_shares_outstanding=deps.resolve_shares_outstanding,
        resolve_monte_carlo_controls=deps.resolve_monte_carlo_controls,
        market_float=deps.market_float,
        value_or_missing=deps.value_or_missing,
        ratio=deps.ratio,
        subtract=deps.subtract,
        build_saas_growth_rates=deps.build_saas_growth_rates,
        repeat_rate=deps.repeat_rate,
        missing_field=deps.missing_field,
        to_float=deps.to_float,
        computed_field=deps.computed_field,
        growth_rates_from_series=deps.growth_rates_from_series,
    )


def build_default_builder_context(
    *,
    projection_years: int,
    default_market_risk_premium: float,
    default_maintenance_capex_ratio: float,
    default_monte_carlo_iterations: int,
    default_monte_carlo_seed: int | None,
    default_monte_carlo_sampler: str,
    long_run_growth_target: float,
    high_growth_trigger: float,
    short_term_consensus_decay_years: int,
) -> BuilderContext:
    def _resolve_shares_outstanding(
        filing_shares_tf: TraceableField[float],
        market_snapshot: Mapping[str, object] | None,
        assumptions: list[str],
    ) -> TraceableField[float]:
        return _resolve_shares_outstanding_service(
            filing_shares_tf=filing_shares_tf,
            market_snapshot=market_snapshot,
            assumptions=assumptions,
        )

    def _resolve_monte_carlo(
        market_snapshot: Mapping[str, object] | None,
        assumptions: list[str],
    ) -> MonteCarloControls:
        return _resolve_monte_carlo_controls_service(
            market_snapshot=market_snapshot,
            assumptions=assumptions,
            default_iterations=default_monte_carlo_iterations,
            default_seed=default_monte_carlo_seed,
            default_sampler=default_monte_carlo_sampler,
        )

    def _build_saas_growth_rates(
        revenue_series: list[TraceableField[float]],
        market_snapshot: Mapping[str, object] | None,
        assumptions: list[str],
    ) -> TraceableField[list[float]]:
        return _build_saas_growth_rates_service(
            revenue_series=revenue_series,
            market_snapshot=market_snapshot,
            assumptions=assumptions,
            projection_years=projection_years,
            long_run_target=long_run_growth_target,
            high_growth_trigger=high_growth_trigger,
            short_term_consensus_decay_years=short_term_consensus_decay_years,
        )

    return _build_builder_context(
        projection_years=projection_years,
        default_market_risk_premium=default_market_risk_premium,
        default_maintenance_capex_ratio=default_maintenance_capex_ratio,
        deps=_BuilderContextDeps(
            resolve_shares_outstanding=_resolve_shares_outstanding,
            resolve_monte_carlo_controls=_resolve_monte_carlo,
            market_float=_market_float,
            value_or_missing=_value_or_missing,
            ratio=_ratio,
            subtract=_subtract,
            build_saas_growth_rates=_build_saas_growth_rates,
            repeat_rate=_repeat_rate,
            missing_field=_missing_field,
            to_float=_to_float,
            computed_field=_computed_field,
            growth_rates_from_series=_growth_rates_from_series,
        ),
    )
