from __future__ import annotations

from src.shared.kernel.traceable import TraceableField

from ...types import TraceInput
from ..shared.common_output_assembly_service import (
    build_capital_structure_params,
    build_capital_structure_trace_inputs,
    build_sec_xbrl_base_params,
)
from ..shared.missing_metrics_service import extend_missing_fields


def extend_eva_missing_fields(*, missing: list[str]) -> None:
    extend_missing_fields(
        missing=missing,
        field_names=("projected_evas", "wacc", "terminal_growth"),
    )


def build_eva_trace_inputs(
    *,
    invested_capital_tf: TraceableField[float],
    cash_tf: TraceableField[float],
    debt_tf: TraceableField[float],
    preferred_tf: TraceableField[float],
    shares_tf: TraceableField[float],
) -> dict[str, TraceInput]:
    return {
        "current_invested_capital": invested_capital_tf,
        **build_capital_structure_trace_inputs(
            cash_tf=cash_tf,
            debt_tf=debt_tf,
            preferred_tf=preferred_tf,
            shares_tf=shares_tf,
        ),
    }


def build_eva_params(
    *,
    ticker: str | None,
    current_invested_capital: float | None,
    cash: float | None,
    total_debt: float | None,
    preferred_stock: float | None,
    shares_outstanding: float | None,
    current_price: float | None,
) -> dict[str, object]:
    return {
        **build_sec_xbrl_base_params(ticker=ticker),
        "current_invested_capital": current_invested_capital,
        "projected_evas": None,
        "wacc": None,
        "terminal_growth": None,
        "terminal_eva": None,
        **build_capital_structure_params(
            cash=cash,
            total_debt=total_debt,
            preferred_stock=preferred_stock,
            shares_outstanding=shares_outstanding,
            current_price=current_price,
        ),
    }
