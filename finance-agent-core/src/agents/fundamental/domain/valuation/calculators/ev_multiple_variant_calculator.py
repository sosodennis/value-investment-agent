from __future__ import annotations

from typing import Protocol

from src.agents.fundamental.domain.valuation.parameterization.types import (
    TraceInput,
)

from ..engine.graphs.ev_multiple import create_ev_multiple_graph
from .calculator_runtime_support import (
    apply_trace_inputs,
    compute_upside,
    unwrap_traceable_value,
)


class EvMultipleVariantParams(Protocol):
    ticker: str
    cash: float
    total_debt: float
    preferred_stock: float
    shares_outstanding: float
    current_price: float | None
    trace_inputs: dict[str, TraceInput]


def calculate_ev_multiple_variant_valuation(
    params: EvMultipleVariantParams,
    *,
    target_metric: float,
    multiple: float,
) -> dict[str, float | str | dict[str, object]]:
    graph = create_ev_multiple_graph()

    inputs = {
        "target_metric": target_metric,
        "multiple": multiple,
        "cash": params.cash,
        "total_debt": params.total_debt,
        "preferred_stock": params.preferred_stock,
        "shares_outstanding": params.shares_outstanding,
    }

    try:
        traced_inputs = apply_trace_inputs(inputs, params.trace_inputs)
        results = graph.calculate(traced_inputs, trace=True)
        intrinsic_value = float(
            unwrap_traceable_value(results.get("intrinsic_value", 0.0))
        )
        implied_ev = float(unwrap_traceable_value(results.get("implied_ev", 0.0)))
        upside = compute_upside(intrinsic_value, params.current_price)

        details = {
            "target_metric": target_metric,
            "multiple": multiple,
            "implied_ev": implied_ev,
        }

        return {
            "ticker": params.ticker,
            "enterprise_value": implied_ev,
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
