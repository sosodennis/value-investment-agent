from src.shared.kernel.traceable import TraceableField

from ...engine.graphs.bank_ddm import create_bank_graph
from .schemas import BankParams


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


def calculate_bank_valuation(
    params: BankParams,
) -> dict[str, float | str | dict[str, object]]:
    """
    Executes the Bank DDM Valuation Graph.
    """
    graph = create_bank_graph()

    inputs = {
        "initial_net_income": params.initial_net_income,
        "income_growth_rates": params.income_growth_rates,
        "rwa_intensity": params.rwa_intensity,
        "tier1_target_ratio": params.tier1_target_ratio,
        "initial_capital": params.initial_capital,
        "cost_of_equity": params.cost_of_equity,
        "terminal_growth": params.terminal_growth,
    }

    try:
        inputs = _apply_trace_inputs(inputs, params.trace_inputs)
        results = graph.calculate(inputs, trace=True)
        return {
            "ticker": params.ticker,
            "equity_value": float(_unwrap(results.get("equity_value", 0.0))),
            "details": results,
            "trace": results,
        }
    except Exception as e:
        return {"error": str(e)}
