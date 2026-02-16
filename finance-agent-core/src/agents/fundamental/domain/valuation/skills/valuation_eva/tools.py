from __future__ import annotations

from src.shared.kernel.traceable import TraceableField

from ...engine.graphs.eva import create_eva_graph
from .schemas import EvaParams


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


def calculate_eva_valuation(
    params: EvaParams,
) -> dict[str, float | str | dict[str, object]]:
    graph = create_eva_graph()

    terminal_eva = (
        params.terminal_eva
        if params.terminal_eva is not None
        else params.projected_evas[-1]
    )

    inputs = {
        "current_invested_capital": params.current_invested_capital,
        "projected_evas": params.projected_evas,
        "wacc": params.wacc,
        "terminal_growth": params.terminal_growth,
        "terminal_eva": terminal_eva,
        "cash": params.cash,
        "total_debt": params.total_debt,
        "preferred_stock": params.preferred_stock,
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
            "pv_projected_eva": float(_unwrap(results.get("pv_projected_eva", 0.0))),
            "terminal_value": float(_unwrap(results.get("terminal_value", 0.0))),
            "pv_terminal": float(_unwrap(results.get("pv_terminal", 0.0))),
        }

        return {
            "ticker": params.ticker,
            "firm_value": float(_unwrap(results.get("firm_value", 0.0))),
            "equity_value": float(_unwrap(results.get("equity_value", 0.0))),
            "intrinsic_value": intrinsic_value,
            "upside_potential": upside,
            "details": details,
            "trace": results,
        }
    except Exception as e:
        return {"error": str(e)}
