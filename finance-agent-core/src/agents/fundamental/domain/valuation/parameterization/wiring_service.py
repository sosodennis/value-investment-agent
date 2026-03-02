from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TypeVar

from src.shared.kernel.traceable import TraceableField

from ..report_contract import FinancialReport
from .model_builders.context import BuilderContext
from .types import MonteCarloControls

R = TypeVar("R")
ModelParamBuilder = Callable[
    [str | None, FinancialReport, list[FinancialReport], Mapping[str, object] | None],
    R,
]
LatestOnlyParamBuilder = Callable[
    [str | None, FinancialReport, Mapping[str, object] | None],
    R,
]


@dataclass(frozen=True)
class BuilderContextDeps:
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


def build_builder_context(
    *,
    projection_years: int,
    default_market_risk_premium: float,
    default_maintenance_capex_ratio: float,
    deps: BuilderContextDeps,
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


def _route_latest_only(
    builder: LatestOnlyParamBuilder[R],
) -> ModelParamBuilder[R]:
    def _route(
        ticker: str | None,
        latest: FinancialReport,
        _reports: list[FinancialReport],
        market_snapshot: Mapping[str, object] | None,
    ) -> R:
        return builder(
            ticker=ticker,
            latest=latest,
            market_snapshot=market_snapshot,
        )

    return _route


def build_model_builder_registry(
    *,
    dcf_standard: ModelParamBuilder[R],
    dcf_growth: ModelParamBuilder[R],
    saas: ModelParamBuilder[R],
    bank: ModelParamBuilder[R],
    ev_revenue: LatestOnlyParamBuilder[R],
    ev_ebitda: LatestOnlyParamBuilder[R],
    reit_ffo: LatestOnlyParamBuilder[R],
    residual_income: LatestOnlyParamBuilder[R],
    eva: LatestOnlyParamBuilder[R],
) -> dict[str, ModelParamBuilder[R]]:
    return {
        "dcf_standard": dcf_standard,
        "dcf_growth": dcf_growth,
        "saas": saas,
        "bank": bank,
        "ev_revenue": _route_latest_only(ev_revenue),
        "ev_ebitda": _route_latest_only(ev_ebitda),
        "reit_ffo": _route_latest_only(reit_ffo),
        "residual_income": _route_latest_only(residual_income),
        "eva": _route_latest_only(eva),
    }
