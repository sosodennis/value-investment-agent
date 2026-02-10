from __future__ import annotations

from src.common.traceable import TraceableField

from ...engine.graphs.saas_fcff import create_saas_graph
from .schemas import SaaSParams

CalcDetails = dict[str, float | list[float] | dict[str, float | list[float]]]
CalcTrace = dict[str, object]
CalcResult = dict[str, float | str | CalcDetails | CalcTrace]


def _calculate_fcfe_valuation(
    fcfe_projections: list[float],
    required_return: float,
    terminal_growth: float,
    shares_outstanding: float,
) -> dict[str, float | list[float]]:
    if terminal_growth >= required_return:
        raise ValueError("Terminal growth rate must be less than required return")

    pv_fcfe = 0.0
    pv_details: list[float] = []
    for t, fcfe in enumerate(fcfe_projections):
        pv = fcfe / ((1 + required_return) ** (t + 1))
        pv_fcfe += pv
        pv_details.append(pv)

    terminal_value = (fcfe_projections[-1] * (1 + terminal_growth)) / (
        required_return - terminal_growth
    )
    pv_terminal = terminal_value / ((1 + required_return) ** len(fcfe_projections))
    equity_value = pv_fcfe + pv_terminal

    intrinsic_value = (
        equity_value / shares_outstanding if shares_outstanding > 0 else 0.0
    )

    return {
        "equity_value": equity_value,
        "terminal_value": terminal_value,
        "pv_terminal": pv_terminal,
        "pv_fcfe": pv_fcfe,
        "intrinsic_value": intrinsic_value,
        "pv_details": pv_details,
    }


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


def calculate_saas_valuation(params: SaaSParams) -> CalcResult:
    """
    Executes the SaaS FCFF Valuation Graph using provided parameters.
    """
    graph = create_saas_graph()

    inputs = {
        "initial_revenue": params.initial_revenue,
        "growth_rates": params.growth_rates,
        "operating_margins": params.operating_margins,
        "tax_rate": params.tax_rate,
        "da_rates": params.da_rates,
        "capex_rates": params.capex_rates,
        "wc_rates": params.wc_rates,
        "sbc_rates": params.sbc_rates,
        "wacc": params.wacc,
        "terminal_growth": params.terminal_growth,
        "cash": params.cash,
        "total_debt": params.total_debt,
        "preferred_stock": params.preferred_stock,
        "shares_outstanding": params.shares_outstanding,
    }

    try:
        inputs = _apply_trace_inputs(inputs, params.trace_inputs)
        results = graph.calculate(inputs, trace=True)
        intrinsic_value_raw = results.get("intrinsic_value", 0.0)
        intrinsic_value = float(_unwrap(intrinsic_value_raw))
        current_price = params.current_price or 0.0
        upside = 0.0
        if current_price > 0:
            upside = (intrinsic_value - current_price) / current_price

        details: CalcDetails = {
            "fcff": _unwrap(results.get("fcff", [])),
            "projected_revenue": _unwrap(results.get("projected_revenue", [])),
            "pv_fcff": float(_unwrap(results.get("pv_fcff", 0.0))),
            "terminal_value": float(_unwrap(results.get("terminal_value", 0.0))),
            "pv_terminal": float(_unwrap(results.get("pv_terminal", 0.0))),
            "enterprise_value": float(_unwrap(results.get("enterprise_value", 0.0))),
        }

        if (
            params.fcfe_projections is not None
            and params.required_return is not None
            and params.terminal_growth_fcfe is not None
        ):
            details["fcfe"] = _calculate_fcfe_valuation(
                params.fcfe_projections,
                params.required_return,
                params.terminal_growth_fcfe,
                params.shares_outstanding,
            )

        return {
            "ticker": params.ticker,
            "enterprise_value": float(_unwrap(results.get("enterprise_value", 0.0))),
            "equity_value": float(_unwrap(results.get("equity_value", 0.0))),
            "intrinsic_value": intrinsic_value,
            "upside_potential": upside,
            "details": details,
            "trace": results,
        }
    except Exception as e:
        return {"error": str(e)}
