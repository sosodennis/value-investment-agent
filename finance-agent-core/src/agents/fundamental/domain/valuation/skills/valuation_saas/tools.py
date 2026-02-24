from __future__ import annotations

from collections.abc import Mapping

import numpy as np

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


def _run_saas_monte_carlo(
    *,
    base_inputs: dict[str, float | list[float]],
    params: SaaSParams,
) -> dict[str, object]:
    config = MonteCarloConfig(
        iterations=params.monte_carlo_iterations,
        seed=params.monte_carlo_seed,
        sampler_type=params.monte_carlo_sampler,
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

    base_growth_rates = np.asarray(base_inputs["growth_rates"], dtype=float)
    base_operating_margins = np.asarray(base_inputs["operating_margins"], dtype=float)
    da_rates = np.asarray(base_inputs["da_rates"], dtype=float)
    capex_rates = np.asarray(base_inputs["capex_rates"], dtype=float)
    wc_rates = np.asarray(base_inputs["wc_rates"], dtype=float)
    sbc_rates = np.asarray(base_inputs["sbc_rates"], dtype=float)
    initial_revenue = float(base_inputs["initial_revenue"])
    tax_rate = float(base_inputs["tax_rate"])
    cash = float(base_inputs["cash"])
    total_debt = float(base_inputs["total_debt"])
    preferred_stock = float(base_inputs["preferred_stock"])
    shares_outstanding = float(base_inputs["shares_outstanding"])

    def batch_evaluate(
        sampled_batch: dict[str, np.ndarray], _base_numeric: Mapping[str, float]
    ) -> np.ndarray:
        growth_shock = np.asarray(sampled_batch["growth_shock"], dtype=float)
        margin_shock = np.asarray(sampled_batch["margin_shock"], dtype=float)
        wacc = np.asarray(sampled_batch["wacc"], dtype=float)
        sampled_terminal = np.asarray(sampled_batch["terminal_growth"], dtype=float)
        terminal_growth = np.minimum(sampled_terminal, wacc - 0.001)

        batch_size = growth_shock.shape[0]
        projection_years = base_growth_rates.shape[0]

        growth_rates = np.clip(
            base_growth_rates[np.newaxis, :] + growth_shock[:, np.newaxis],
            -0.80,
            1.50,
        )
        operating_margins = np.clip(
            base_operating_margins[np.newaxis, :] + margin_shock[:, np.newaxis],
            -0.50,
            0.70,
        )

        projected_revenue = np.empty((batch_size, projection_years), dtype=float)
        revenue_level = np.full(batch_size, initial_revenue, dtype=float)
        for year_idx in range(projection_years):
            revenue_level = revenue_level * (1.0 + growth_rates[:, year_idx])
            projected_revenue[:, year_idx] = revenue_level

        ebit = projected_revenue * operating_margins
        nopat = ebit * (1.0 - tax_rate)
        da = projected_revenue * da_rates[np.newaxis, :]
        capex = projected_revenue * capex_rates[np.newaxis, :]
        sbc = projected_revenue * sbc_rates[np.newaxis, :]
        previous_revenue = np.concatenate(
            [
                np.full((batch_size, 1), initial_revenue, dtype=float),
                projected_revenue[:, :-1],
            ],
            axis=1,
        )
        delta_revenue = projected_revenue - previous_revenue
        delta_wc = delta_revenue * wc_rates[np.newaxis, :]
        fcff = nopat + da - capex - delta_wc + sbc

        discount_years = np.arange(1, projection_years + 1, dtype=float)
        discount_curve = np.power(
            1.0 + wacc[:, np.newaxis], discount_years[np.newaxis, :]
        )
        pv_fcff = np.sum(fcff / discount_curve, axis=1)

        final_fcff = fcff[:, -1]
        terminal_value = final_fcff * (1.0 + terminal_growth) / (wacc - terminal_growth)
        pv_terminal = terminal_value / np.power(1.0 + wacc, projection_years)
        enterprise_value = pv_fcff + pv_terminal
        equity_value = enterprise_value + cash - total_debt - preferred_stock
        return equity_value / shares_outstanding

    result = engine.run(
        base_inputs=base_numeric_inputs,
        distributions=distributions,
        batch_evaluator=batch_evaluate,
        correlation_groups=correlation_groups,
    )
    return {
        "metric_type": "intrinsic_value_per_share",
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
