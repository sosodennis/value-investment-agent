from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from src.shared.kernel.traceable import TraceableField

from ...engine.graphs.dcf_standard import create_dcf_standard_graph
from ...engine.monte_carlo import (
    CorrelationGroup,
    DistributionSpec,
    MonteCarloConfig,
    MonteCarloEngine,
)
from .schemas import DCFStandardParams


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


def _validate_projection_lengths(params: DCFStandardParams) -> str | None:
    years = len(params.growth_rates)
    if years == 0:
        return "growth_rates cannot be empty"
    series_lengths = {
        "operating_margins": len(params.operating_margins),
        "da_rates": len(params.da_rates),
        "capex_rates": len(params.capex_rates),
        "wc_rates": len(params.wc_rates),
        "sbc_rates": len(params.sbc_rates),
    }
    for name, length in series_lengths.items():
        if length != years:
            return f"{name} length must equal growth_rates length ({years})"
    if params.shares_outstanding <= 0:
        return "shares_outstanding must be positive"
    if params.wacc <= 0:
        return "wacc must be positive"
    if params.terminal_growth >= params.wacc:
        return "terminal_growth must be lower than wacc"
    return None


def _run_dcf_standard_monte_carlo(
    *,
    params: DCFStandardParams,
    converged_inputs: dict[str, list[float]],
    static_inputs: dict[str, float],
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
            std=max(params.growth_shock_std * 0.8, 0.005),
            min_bound=-0.25,
            max_bound=0.25,
        ),
        "margin_shock": DistributionSpec(
            kind="normal",
            mean=0.0,
            std=max(params.margin_shock_std * 0.8, 0.005),
            min_bound=-0.12,
            max_bound=0.12,
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
            min_bound=-0.01,
            max_bound=0.05,
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
        "wacc": params.wacc,
        "terminal_growth": params.terminal_growth,
    }

    base_growth = np.asarray(converged_inputs["growth_rates_converged"], dtype=float)
    base_margin = np.asarray(
        converged_inputs["operating_margins_converged"], dtype=float
    )
    da_rates = np.asarray(converged_inputs["da_rates_converged"], dtype=float)
    capex_rates = np.asarray(converged_inputs["capex_rates_converged"], dtype=float)
    wc_rates = np.asarray(converged_inputs["wc_rates_converged"], dtype=float)
    sbc_rates = np.asarray(converged_inputs["sbc_rates_converged"], dtype=float)

    initial_revenue = static_inputs["initial_revenue"]
    tax_rate = static_inputs["tax_rate"]
    cash = static_inputs["cash"]
    total_debt = static_inputs["total_debt"]
    preferred_stock = static_inputs["preferred_stock"]
    shares_outstanding = static_inputs["shares_outstanding"]
    years = base_growth.shape[0]
    discount_years = np.arange(1, years + 1, dtype=float)

    def batch_evaluate(
        sampled_batch: dict[str, np.ndarray], _base: Mapping[str, float]
    ) -> np.ndarray:
        growth_shock = np.asarray(sampled_batch["growth_shock"], dtype=float)
        margin_shock = np.asarray(sampled_batch["margin_shock"], dtype=float)
        wacc = np.asarray(sampled_batch["wacc"], dtype=float)
        sampled_terminal = np.asarray(sampled_batch["terminal_growth"], dtype=float)
        terminal_growth = np.minimum(sampled_terminal, wacc - 0.002)

        batch_size = growth_shock.shape[0]

        growth_rates = np.clip(
            base_growth[np.newaxis, :] + growth_shock[:, np.newaxis],
            -0.60,
            0.90,
        )
        margins = np.clip(
            base_margin[np.newaxis, :] + margin_shock[:, np.newaxis],
            -0.30,
            0.55,
        )

        projected_revenue = np.empty((batch_size, years), dtype=float)
        revenue_level = np.full(batch_size, initial_revenue, dtype=float)
        for index in range(years):
            revenue_level *= 1.0 + growth_rates[:, index]
            projected_revenue[:, index] = revenue_level

        ebit = projected_revenue * margins
        nopat = ebit * (1.0 - tax_rate)
        da = projected_revenue * da_rates[np.newaxis, :]
        capex = projected_revenue * capex_rates[np.newaxis, :]
        sbc = projected_revenue * sbc_rates[np.newaxis, :]
        previous_revenue = np.empty_like(projected_revenue)
        previous_revenue[:, 0] = initial_revenue
        previous_revenue[:, 1:] = projected_revenue[:, :-1]
        delta_wc = (projected_revenue - previous_revenue) * wc_rates[np.newaxis, :]
        fcff = nopat + da - capex - delta_wc + sbc

        discount_curve = np.power(
            1.0 + wacc[:, np.newaxis], discount_years[np.newaxis, :]
        )
        pv_fcff = np.sum(fcff / discount_curve, axis=1)
        final_fcff = fcff[:, -1]
        terminal_value = final_fcff * (1.0 + terminal_growth) / (wacc - terminal_growth)
        pv_terminal = terminal_value / np.power(1.0 + wacc, years)

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


def calculate_dcf_standard_valuation(
    params: DCFStandardParams,
) -> dict[str, float | str | dict[str, object]]:
    graph = create_dcf_standard_graph()

    validation_error = _validate_projection_lengths(params)
    if validation_error is not None:
        return {"error": validation_error}

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

        intrinsic_value = float(_unwrap(results.get("intrinsic_value", 0.0)))
        current_price = params.current_price or 0.0
        upside = 0.0
        if current_price > 0:
            upside = (intrinsic_value - current_price) / current_price

        details: dict[str, object] = {
            "fcff": _unwrap(results.get("fcff", [])),
            "projected_revenue": _unwrap(results.get("projected_revenue", [])),
            "reinvestment_rates": _unwrap(results.get("reinvestment_rates", [])),
            "growth_rates_converged": _unwrap(
                results.get("growth_rates_converged", [])
            ),
            "operating_margins_converged": _unwrap(
                results.get("operating_margins_converged", [])
            ),
            "da_rates_converged": _unwrap(results.get("da_rates_converged", [])),
            "capex_rates_converged": _unwrap(results.get("capex_rates_converged", [])),
            "wc_rates_converged": _unwrap(results.get("wc_rates_converged", [])),
            "sbc_rates_converged": _unwrap(results.get("sbc_rates_converged", [])),
            "terminal_growth_effective": float(
                _unwrap(results.get("terminal_growth_effective", 0.0))
            ),
            "pv_fcff": float(_unwrap(results.get("pv_fcff", 0.0))),
            "terminal_value": float(_unwrap(results.get("terminal_value", 0.0))),
            "pv_terminal": float(_unwrap(results.get("pv_terminal", 0.0))),
            "enterprise_value": float(_unwrap(results.get("enterprise_value", 0.0))),
        }

        if params.monte_carlo_iterations > 0:
            details["distribution_summary"] = _run_dcf_standard_monte_carlo(
                params=params,
                converged_inputs={
                    "growth_rates_converged": details["growth_rates_converged"],
                    "operating_margins_converged": details[
                        "operating_margins_converged"
                    ],
                    "da_rates_converged": details["da_rates_converged"],
                    "capex_rates_converged": details["capex_rates_converged"],
                    "wc_rates_converged": details["wc_rates_converged"],
                    "sbc_rates_converged": details["sbc_rates_converged"],
                },
                static_inputs={
                    "initial_revenue": float(params.initial_revenue),
                    "tax_rate": float(params.tax_rate),
                    "cash": float(params.cash),
                    "total_debt": float(params.total_debt),
                    "preferred_stock": float(params.preferred_stock),
                    "shares_outstanding": float(params.shares_outstanding),
                },
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
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
