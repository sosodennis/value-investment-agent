from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from src.shared.kernel.traceable import TraceableField

from ....report_contract import FinancialReport, RealEstateExtension
from ...types import MonteCarloControls, TraceInput
from ..shared.capital_structure_value_extraction_service import (
    extract_filing_capital_structure_market_values,
)
from .reit_fallback_policy_service import (
    resolve_reit_depreciation_for_affo,
    resolve_reit_maintenance_capex_ratio,
)
from .reit_ffo_policy_service import resolve_reit_ffo_multiple
from .reit_output_assembly_service import (
    build_reit_params,
    build_reit_trace_inputs,
)


@dataclass(frozen=True)
class ReitBuilderDeps:
    default_maintenance_capex_ratio: float
    resolve_shares_outstanding: Callable[
        [TraceableField[float], Mapping[str, object] | None, list[str]],
        TraceableField[float],
    ]
    market_float: Callable[[Mapping[str, object] | None, str], float | None]
    value_or_missing: Callable[
        [TraceableField[float] | None, str, list[str]],
        float | None,
    ]
    resolve_monte_carlo_controls: Callable[
        [Mapping[str, object] | None, list[str]],
        MonteCarloControls,
    ]
    to_float: Callable[[object], float | None]
    missing_field: Callable[[str, str], TraceableField[float]]


@dataclass(frozen=True)
class ReitBuildPayload:
    params: dict[str, object]
    trace_inputs: dict[str, TraceInput]
    missing: list[str]
    assumptions: list[str]
    shares_source: str


def build_reit_payload(
    *,
    ticker: str | None,
    latest: FinancialReport,
    market_snapshot: Mapping[str, object] | None,
    deps: ReitBuilderDeps,
) -> ReitBuildPayload:
    missing: list[str] = []
    assumptions: list[str] = []
    base = latest.base
    extension = (
        latest.extension if isinstance(latest.extension, RealEstateExtension) else None
    )

    ffo_tf = extension.ffo if extension else None
    shares_tf = deps.resolve_shares_outstanding(
        base.shares_outstanding,
        market_snapshot,
        assumptions,
    )
    cash_tf = base.cash_and_equivalents
    debt_tf = base.total_debt
    preferred_tf = base.preferred_stock
    depreciation_tf = base.depreciation_and_amortization

    ffo = deps.value_or_missing(
        ffo_tf,
        "ffo",
        missing,
    )
    market_values = extract_filing_capital_structure_market_values(
        value_or_missing=deps.value_or_missing,
        missing=missing,
        shares_tf=shares_tf,
        cash_tf=cash_tf,
        debt_tf=debt_tf,
        preferred_tf=preferred_tf,
        market_float=deps.market_float,
        market_snapshot=market_snapshot,
    )
    shares_outstanding = market_values.shares_outstanding
    cash = market_values.cash
    total_debt = market_values.total_debt
    preferred_stock = market_values.preferred_stock
    current_price = market_values.current_price
    shares_source = market_values.shares_source
    (
        monte_carlo_iterations,
        monte_carlo_seed,
        monte_carlo_sampler,
    ) = deps.resolve_monte_carlo_controls(market_snapshot, assumptions)

    depreciation_and_amortization = resolve_reit_depreciation_for_affo(
        depreciation_tf=depreciation_tf,
        to_float=deps.to_float,
        assumptions=assumptions,
    )
    maintenance_capex_ratio = resolve_reit_maintenance_capex_ratio(
        market_snapshot=market_snapshot,
        market_float=deps.market_float,
        default_maintenance_capex_ratio=deps.default_maintenance_capex_ratio,
        assumptions=assumptions,
    )

    ffo_multiple, ffo_multiple_tf = resolve_reit_ffo_multiple(
        market_snapshot=market_snapshot,
        ffo=ffo,
        shares_outstanding=shares_outstanding,
        current_price=current_price,
        market_float=deps.market_float,
        assumptions=assumptions,
    )
    if ffo_multiple is None:
        missing.append("ffo_multiple")

    trace_inputs: dict[str, TraceInput] = build_reit_trace_inputs(
        ffo_tf=ffo_tf,
        ffo_multiple_tf=ffo_multiple_tf,
        cash_tf=cash_tf,
        debt_tf=debt_tf,
        preferred_tf=preferred_tf,
        shares_tf=shares_tf,
        depreciation_tf=depreciation_tf,
        maintenance_capex_ratio=maintenance_capex_ratio,
        missing_field=deps.missing_field,
    )

    params: dict[str, object] = build_reit_params(
        ticker=ticker,
        ffo=ffo,
        ffo_multiple=ffo_multiple,
        depreciation_and_amortization=depreciation_and_amortization,
        maintenance_capex_ratio=maintenance_capex_ratio,
        cash=cash,
        total_debt=total_debt,
        preferred_stock=preferred_stock,
        shares_outstanding=shares_outstanding,
        current_price=current_price,
        monte_carlo_iterations=monte_carlo_iterations,
        monte_carlo_seed=monte_carlo_seed,
        monte_carlo_sampler=monte_carlo_sampler,
    )

    return ReitBuildPayload(
        params=params,
        trace_inputs=trace_inputs,
        missing=missing,
        assumptions=assumptions,
        shares_source=shares_source,
    )
