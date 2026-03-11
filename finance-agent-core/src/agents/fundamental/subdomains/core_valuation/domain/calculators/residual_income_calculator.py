from __future__ import annotations

from typing import Protocol

from src.agents.fundamental.subdomains.core_valuation.domain.parameterization.types import (
    TraceInput,
)

from ..engine.graphs.residual_income import create_residual_income_graph
from .calculator_runtime_support import (
    apply_trace_inputs,
    compute_upside,
    unwrap_traceable_value,
)


class ResidualIncomeCalculatorParams(Protocol):
    ticker: str
    current_book_value: float
    projected_residual_incomes: list[float]
    required_return: float
    terminal_growth: float
    terminal_residual_income: float | None
    shares_outstanding: float
    current_price: float | None
    trace_inputs: dict[str, TraceInput]


def calculate_residual_income_valuation(
    params: ResidualIncomeCalculatorParams,
) -> dict[str, float | str | dict[str, object]]:
    graph = create_residual_income_graph()

    terminal_ri = (
        params.terminal_residual_income
        if params.terminal_residual_income is not None
        else params.projected_residual_incomes[-1]
    )

    inputs = {
        "current_book_value": params.current_book_value,
        "projected_residual_incomes": params.projected_residual_incomes,
        "required_return": params.required_return,
        "terminal_growth": params.terminal_growth,
        "terminal_residual_income": terminal_ri,
        "shares_outstanding": params.shares_outstanding,
    }

    try:
        traced_inputs = apply_trace_inputs(inputs, params.trace_inputs)
        results = graph.calculate(traced_inputs, trace=True)
        intrinsic_value = float(
            unwrap_traceable_value(results.get("intrinsic_value", 0.0))
        )
        upside = compute_upside(intrinsic_value, params.current_price)

        details = {
            "pv_projected_ri": float(
                unwrap_traceable_value(results.get("pv_projected_ri", 0.0))
            ),
            "terminal_value": float(
                unwrap_traceable_value(results.get("terminal_value", 0.0))
            ),
            "pv_terminal": float(
                unwrap_traceable_value(results.get("pv_terminal", 0.0))
            ),
        }

        return {
            "ticker": params.ticker,
            "equity_value": float(
                unwrap_traceable_value(results.get("total_value", 0.0))
            ),
            "intrinsic_value": intrinsic_value,
            "upside_potential": upside,
            "details": details,
            "trace": results,
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
