from __future__ import annotations

from src.shared.kernel.traceable import TraceableField

from ...types import TraceInput
from ..shared.common_output_assembly_service import (
    build_equity_value_params,
    build_sec_xbrl_base_params,
    build_shares_trace_inputs,
)
from ..shared.missing_metrics_service import extend_missing_fields


def extend_residual_income_missing_fields(*, missing: list[str]) -> None:
    extend_missing_fields(
        missing=missing,
        field_names=(
            "projected_residual_incomes",
            "required_return",
            "terminal_growth",
        ),
    )


def build_residual_income_trace_inputs(
    *,
    book_value_tf: TraceableField[float],
    shares_tf: TraceableField[float],
) -> dict[str, TraceInput]:
    return {
        "current_book_value": book_value_tf,
        **build_shares_trace_inputs(shares_tf=shares_tf),
    }


def build_residual_income_params(
    *,
    ticker: str | None,
    current_book_value: float | None,
    shares_outstanding: float | None,
    current_price: float | None,
) -> dict[str, object]:
    return {
        **build_sec_xbrl_base_params(ticker=ticker),
        "current_book_value": current_book_value,
        "projected_residual_incomes": None,
        "required_return": None,
        "terminal_growth": None,
        "terminal_residual_income": None,
        **build_equity_value_params(
            shares_outstanding=shares_outstanding,
            current_price=current_price,
        ),
    }
