from __future__ import annotations

from typing import cast

from src.shared.kernel.traceable import TraceableField

from ...engine.graphs.saas_fcff import create_saas_graph
from ...engine.monte_carlo import (
    CorrelationGroup,
    DistributionSpec,
    MonteCarloConfig,
    MonteCarloEngine,
)
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


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _shift_series(
    values: list[float], shock: float, lower: float, upper: float
) -> list[float]:
    return [_clamp(v + shock, lower, upper) for v in values]


def _run_saas_monte_carlo(
    *,
    graph,
    base_inputs: dict[str, float | list[float]],
    params: SaaSParams,
) -> dict[str, object]:
    config = MonteCarloConfig(
        iterations=params.monte_carlo_iterations,
        seed=params.monte_carlo_seed,
    )
    engine = MonteCarloEngine(config=config)

    distributions: dict[str, DistributionSpec] = {
        "growth_shock": DistributionSpec(
            kind="normal",
            mean=0.0,
            std=params.growth_shock_std,
            min_bound=-0.30,
            max_bound=0.30,
        ),
        "margin_shock": DistributionSpec(
            kind="normal",
            mean=0.0,
            std=params.margin_shock_std,
            min_bound=-0.20,
            max_bound=0.20,
        ),
        "wacc": DistributionSpec(
            kind="normal",
            mean=params.wacc,
            std=params.wacc_std,
            min_bound=0.03,
            max_bound=0.30,
        ),
        "terminal_growth": DistributionSpec(
            kind="normal",
            mean=params.terminal_growth,
            std=params.terminal_growth_std,
            min_bound=-0.02,
            max_bound=0.06,
        ),
    }

    correlation_groups = (
        CorrelationGroup(
            variables=("growth_shock", "margin_shock"),
            matrix=(
                (1.0, params.corr_growth_margin),
                (params.corr_growth_margin, 1.0),
            ),
        ),
        CorrelationGroup(
            variables=("wacc", "terminal_growth"),
            matrix=(
                (1.0, params.corr_wacc_terminal_growth),
                (params.corr_wacc_terminal_growth, 1.0),
            ),
        ),
    )

    base_numeric_inputs = {
        "growth_shock": 0.0,
        "margin_shock": 0.0,
        "wacc": float(params.wacc),
        "terminal_growth": float(params.terminal_growth),
    }

    def evaluate(sampled: dict[str, float]) -> float:
        iter_inputs = dict(base_inputs)
        growth_shock = sampled["growth_shock"]
        margin_shock = sampled["margin_shock"]
        iter_inputs["growth_rates"] = _shift_series(
            cast(list[float], base_inputs["growth_rates"]),
            growth_shock,
            -0.80,
            1.50,
        )
        iter_inputs["operating_margins"] = _shift_series(
            cast(list[float], base_inputs["operating_margins"]),
            margin_shock,
            -0.50,
            0.70,
        )

        sampled_wacc = sampled["wacc"]
        sampled_terminal = sampled["terminal_growth"]
        if sampled_terminal >= sampled_wacc:
            sampled_terminal = sampled_wacc - 0.001

        iter_inputs["wacc"] = sampled_wacc
        iter_inputs["terminal_growth"] = sampled_terminal

        raw_result = graph.calculate(iter_inputs)
        raw_intrinsic = raw_result.get("intrinsic_value", 0.0)
        return float(_unwrap(raw_intrinsic))

    result = engine.run(
        base_inputs=base_numeric_inputs,
        distributions=distributions,
        evaluator=evaluate,
        correlation_groups=correlation_groups,
    )
    return {
        "summary": result.summary,
        "diagnostics": result.diagnostics,
    }


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

    raw_inputs = {
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
        inputs = _apply_trace_inputs(raw_inputs, params.trace_inputs)
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

        if params.monte_carlo_iterations > 0:
            details["distribution_summary"] = _run_saas_monte_carlo(
                graph=graph,
                # MC evaluator requires plain numeric/list inputs.
                # TraceableField wrappers are only for deterministic trace output.
                base_inputs=raw_inputs,
                params=params,
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
