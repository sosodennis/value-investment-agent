from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from src.shared.kernel.traceable import TraceableField

from .bank import BankBuilderDeps
from .eva import EvaBuilderDeps
from .multiples import MultiplesBuilderDeps
from .reit import ReitBuilderDeps
from .residual_income import ResidualIncomeBuilderDeps
from .saas import SaasBuilderDeps


@dataclass(frozen=True)
class BuilderContext:
    projection_years: int
    default_market_risk_premium: float
    default_maintenance_capex_ratio: float
    resolve_shares_outstanding: Callable[
        [TraceableField[float], Mapping[str, object] | None, list[str]],
        TraceableField[float],
    ]
    resolve_monte_carlo_controls: Callable[
        [Mapping[str, object] | None, list[str]],
        tuple[int, int | None],
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

    def saas_deps(self) -> SaasBuilderDeps:
        return SaasBuilderDeps(
            projection_years=self.projection_years,
            resolve_shares_outstanding=self.resolve_shares_outstanding,
            market_float=self.market_float,
            value_or_missing=self.value_or_missing,
            ratio=self.ratio,
            subtract=self.subtract,
            build_growth_rates=self.build_saas_growth_rates,
            repeat_rate=self.repeat_rate,
            resolve_monte_carlo_controls=self.resolve_monte_carlo_controls,
            missing_field=self.missing_field,
        )

    def bank_deps(self) -> BankBuilderDeps:
        return BankBuilderDeps(
            projection_years=self.projection_years,
            default_market_risk_premium=self.default_market_risk_premium,
            resolve_shares_outstanding=self.resolve_shares_outstanding,
            growth_rates_from_series=self.growth_rates_from_series,
            ratio=self.ratio,
            value_or_missing=self.value_or_missing,
            missing_field=self.missing_field,
            market_float=self.market_float,
            resolve_monte_carlo_controls=self.resolve_monte_carlo_controls,
        )

    def reit_deps(self) -> ReitBuilderDeps:
        return ReitBuilderDeps(
            default_maintenance_capex_ratio=self.default_maintenance_capex_ratio,
            resolve_shares_outstanding=self.resolve_shares_outstanding,
            market_float=self.market_float,
            value_or_missing=self.value_or_missing,
            resolve_monte_carlo_controls=self.resolve_monte_carlo_controls,
            to_float=self.to_float,
            missing_field=self.missing_field,
        )

    def multiples_deps(self) -> MultiplesBuilderDeps:
        return MultiplesBuilderDeps(
            resolve_shares_outstanding=self.resolve_shares_outstanding,
            market_float=self.market_float,
            value_or_missing=self.value_or_missing,
        )

    def residual_income_deps(self) -> ResidualIncomeBuilderDeps:
        return ResidualIncomeBuilderDeps(
            resolve_shares_outstanding=self.resolve_shares_outstanding,
            market_float=self.market_float,
            value_or_missing=self.value_or_missing,
        )

    def eva_deps(self) -> EvaBuilderDeps:
        return EvaBuilderDeps(
            resolve_shares_outstanding=self.resolve_shares_outstanding,
            market_float=self.market_float,
            value_or_missing=self.value_or_missing,
            missing_field=self.missing_field,
            computed_field=self.computed_field,
        )
