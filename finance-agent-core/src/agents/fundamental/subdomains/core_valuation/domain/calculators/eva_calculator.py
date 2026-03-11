from __future__ import annotations

from ..engine.graphs.eva import create_eva_graph
from ..models.eva.contracts import EvaParams
from .calculator_runtime_support import (
    apply_trace_inputs,
    compute_upside,
    unwrap_traceable_value,
)


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
        inputs = apply_trace_inputs(inputs, params.trace_inputs)
        results = graph.calculate(inputs, trace=True)
        intrinsic_value = float(
            unwrap_traceable_value(results.get("intrinsic_value", 0.0))
        )
        upside = compute_upside(intrinsic_value, params.current_price)

        details = {
            "pv_projected_eva": float(
                unwrap_traceable_value(results.get("pv_projected_eva", 0.0))
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
            "firm_value": float(unwrap_traceable_value(results.get("firm_value", 0.0))),
            "equity_value": float(
                unwrap_traceable_value(results.get("equity_value", 0.0))
            ),
            "intrinsic_value": intrinsic_value,
            "upside_potential": upside,
            "details": details,
            "trace": results,
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
