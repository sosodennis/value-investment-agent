from __future__ import annotations

from collections.abc import Callable

from src.shared.kernel.traceable import ManualProvenance, TraceableField

from ...types import TraceInput
from ..shared.common_output_assembly_service import (
    build_capital_structure_params,
    build_capital_structure_trace_inputs,
    build_monte_carlo_params,
    build_sec_xbrl_base_params,
    resolve_optional_trace_input,
)


def build_reit_trace_inputs(
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


def build_reit_params(
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
