from __future__ import annotations

from src.shared.kernel.traceable import TraceableField

from ...engine.graphs.residual_income import create_residual_income_graph
from .schemas import ResidualIncomeParams


def _unwrap(value: float | list[float] | TraceableField) -> float | list[float]:
    if isinstance(value, TraceableField):
        inner = value.value
        if inner is None:
            raise ValueError("TraceableField value is None")
        if isinstance(inner, list):
            return [float(v) for v in inner]
        return float(inner)
    if isinstance(value, list):
        return [float(v) for v in value]
    return float(value)


def _apply_trace_inputs(
    inputs: dict[str, object],
    trace_inputs: dict[str, TraceableField],
) -> dict[str, object]:
    if not trace_inputs:
        return inputs
    merged = inputs.copy()
    for key, value in trace_inputs.items():
        if key in merged and value is not None:
            merged[key] = value
    return merged


def calculate_residual_income_valuation(
    params: ResidualIncomeParams,
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
        inputs = _apply_trace_inputs(inputs, params.trace_inputs)
        results = graph.calculate(inputs, trace=True)
        intrinsic_value = float(_unwrap(results.get("intrinsic_value", 0.0)))
        current_price = params.current_price or 0.0
        upside = 0.0
        if current_price > 0:
            upside = (intrinsic_value - current_price) / current_price

        details = {
            "pv_projected_ri": float(_unwrap(results.get("pv_projected_ri", 0.0))),
            "terminal_value": float(_unwrap(results.get("terminal_value", 0.0))),
            "pv_terminal": float(_unwrap(results.get("pv_terminal", 0.0))),
        }

        return {
            "ticker": params.ticker,
            "equity_value": float(_unwrap(results.get("total_value", 0.0))),
            "intrinsic_value": intrinsic_value,
            "upside_potential": upside,
            "details": details,
            "trace": results,
        }
    except Exception as e:
        return {"error": str(e)}
