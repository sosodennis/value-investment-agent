from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from src.agents.fundamental.shared.contracts.traceable import (
    ManualProvenance,
    TraceableField,
)

from ....report_contract import FinancialReport, RealEstateExtension
from ...types import MonteCarloControls, TraceInput
from ..shared.capital_structure_value_extraction_service import (
    extract_filing_capital_structure_market_values,
)
from ..shared.parameter_assembly_service import (
    build_capital_structure_params,
    build_capital_structure_trace_inputs,
    build_monte_carlo_params,
    build_sec_xbrl_base_params,
    resolve_optional_trace_input,
)


def _resolve_reit_depreciation_for_affo(
    *,
    depreciation_tf: TraceableField[float],
    to_float: Callable[[object], float | None],
    assumptions: list[str],
) -> float:
    depreciation_and_amortization = to_float(depreciation_tf.value)
    if depreciation_and_amortization is None:
        assumptions.append("depreciation_and_amortization defaulted to 0.0 for AFFO")
        return 0.0
    return depreciation_and_amortization


def _resolve_reit_maintenance_capex_ratio(
    *,
    market_snapshot: Mapping[str, object] | None,
    market_float: Callable[[Mapping[str, object] | None, str], float | None],
    default_maintenance_capex_ratio: float,
    assumptions: list[str],
) -> float:
    maintenance_capex_ratio = market_float(market_snapshot, "maintenance_capex_ratio")
    if maintenance_capex_ratio is None:
        assumptions.append(
            "maintenance_capex_ratio defaulted to "
            f"{default_maintenance_capex_ratio:.2f}"
        )
        return default_maintenance_capex_ratio
    return maintenance_capex_ratio


def _resolve_reit_ffo_multiple(
    *,
    market_snapshot: Mapping[str, object] | None,
    ffo: float | None,
    shares_outstanding: float | None,
    current_price: float | None,
    market_float: Callable[[Mapping[str, object] | None, str], float | None],
    assumptions: list[str],
) -> tuple[float | None, TraceableField[float] | None]:
    market_multiple = market_float(market_snapshot, "ffo_multiple")
    if market_multiple is not None and market_multiple > 0:
        assumptions.append("ffo_multiple sourced from market data override")
        return (
            market_multiple,
            TraceableField(
                name="FFO Multiple",
                value=market_multiple,
                provenance=ManualProvenance(
                    description="FFO multiple provided by market snapshot override",
                    author="MarketDataService",
                ),
            ),
        )

    if (
        ffo is not None
        and ffo > 0
        and shares_outstanding is not None
        and shares_outstanding > 0
        and current_price is not None
        and current_price > 0
    ):
        ffo_per_share = ffo / shares_outstanding
        if ffo_per_share > 0:
            implied_multiple = current_price / ffo_per_share
            assumptions.append("ffo_multiple implied from market price and FFO/share")
            return (
                implied_multiple,
                TraceableField(
                    name="FFO Multiple",
                    value=implied_multiple,
                    provenance=ManualProvenance(
                        description=(
                            "Implied from market current_price / (ffo / shares_outstanding)"
                        ),
                        author="ValuationPolicy",
                    ),
                ),
            )

    return None, None


def _build_reit_trace_inputs(
    *,
    ffo_tf: TraceableField[float] | None,
    ffo_multiple_tf: TraceableField[float] | None,
    cash_tf: TraceableField[float],
    debt_tf: TraceableField[float],
    preferred_tf: TraceableField[float],
    shares_tf: TraceableField[float],
    depreciation_tf: TraceableField[float],
    maintenance_capex_ratio: float,
    missing_field: Callable[[str, str], TraceableField[float]],
) -> dict[str, TraceInput]:
    return {
        "ffo": resolve_optional_trace_input(
            trace_input=ffo_tf,
            field_name="FFO",
            missing_reason="Missing FFO",
            missing_field=missing_field,
        ),
        "ffo_multiple": resolve_optional_trace_input(
            trace_input=ffo_multiple_tf,
            field_name="FFO Multiple",
            missing_reason="Missing FFO multiple",
            missing_field=missing_field,
        ),
        **build_capital_structure_trace_inputs(
            cash_tf=cash_tf,
            debt_tf=debt_tf,
            preferred_tf=preferred_tf,
            shares_tf=shares_tf,
        ),
        "depreciation_and_amortization": depreciation_tf,
        "maintenance_capex_ratio": TraceableField(
            name="Maintenance CapEx Ratio",
            value=maintenance_capex_ratio,
            provenance=ManualProvenance(
                description="Configurable REIT maintenance capex heuristic ratio",
                author="ValuationPolicy",
            ),
        ),
    }


def _build_reit_params(
    *,
    ticker: str | None,
    ffo: float | None,
    ffo_multiple: float | None,
    depreciation_and_amortization: float,
    maintenance_capex_ratio: float,
    cash: float | None,
    total_debt: float | None,
    preferred_stock: float | None,
    shares_outstanding: float | None,
    current_price: float | None,
    monte_carlo_iterations: int,
    monte_carlo_seed: int | None,
    monte_carlo_sampler: str,
) -> dict[str, object]:
    return {
        **build_sec_xbrl_base_params(ticker=ticker),
        "ffo": ffo,
        "ffo_multiple": ffo_multiple,
        "depreciation_and_amortization": depreciation_and_amortization,
        "maintenance_capex_ratio": maintenance_capex_ratio,
        **build_capital_structure_params(
            cash=cash,
            total_debt=total_debt,
            preferred_stock=preferred_stock,
            shares_outstanding=shares_outstanding,
            current_price=current_price,
        ),
        **build_monte_carlo_params(
            monte_carlo_iterations=monte_carlo_iterations,
            monte_carlo_seed=monte_carlo_seed,
            monte_carlo_sampler=monte_carlo_sampler,
        ),
    }


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

    depreciation_and_amortization = _resolve_reit_depreciation_for_affo(
        depreciation_tf=depreciation_tf,
        to_float=deps.to_float,
        assumptions=assumptions,
    )
    maintenance_capex_ratio = _resolve_reit_maintenance_capex_ratio(
        market_snapshot=market_snapshot,
        market_float=deps.market_float,
        default_maintenance_capex_ratio=deps.default_maintenance_capex_ratio,
        assumptions=assumptions,
    )

    ffo_multiple, ffo_multiple_tf = _resolve_reit_ffo_multiple(
        market_snapshot=market_snapshot,
        ffo=ffo,
        shares_outstanding=shares_outstanding,
        current_price=current_price,
        market_float=deps.market_float,
        assumptions=assumptions,
    )
    if ffo_multiple is None:
        missing.append("ffo_multiple")

    trace_inputs: dict[str, TraceInput] = _build_reit_trace_inputs(
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

    params: dict[str, object] = _build_reit_params(
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
