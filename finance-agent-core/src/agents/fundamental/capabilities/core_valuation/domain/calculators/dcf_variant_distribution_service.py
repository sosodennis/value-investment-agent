from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from ..engine.monte_carlo import (
    CorrelationGroup,
    DistributionSpec,
    MonteCarloConfig,
    MonteCarloEngine,
)
from .dcf_variant_contracts import DcfMonteCarloPolicy, DcfVariantParams


def run_dcf_variant_monte_carlo(
    *,
    params: DcfVariantParams,
    converged_inputs: Mapping[str, list[float]],
    static_inputs: Mapping[str, float],
    policy: DcfMonteCarloPolicy,
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
            std=max(
                params.growth_shock_std * policy.growth_std_scale, policy.growth_std_min
            ),
            min_bound=policy.growth_clip_min,
            max_bound=policy.growth_clip_max,
        ),
        "margin_shock": DistributionSpec(
            kind="normal",
            mean=0.0,
            std=max(
                params.margin_shock_std * policy.margin_std_scale, policy.margin_std_min
            ),
            min_bound=policy.margin_clip_min,
            max_bound=policy.margin_clip_max,
        ),
        "wacc": DistributionSpec(
            kind="normal",
            mean=params.wacc,
            std=params.wacc_std,
            min_bound=policy.wacc_min,
            max_bound=policy.wacc_max,
        ),
        "terminal_growth": DistributionSpec(
            kind="normal",
            mean=params.terminal_growth,
            std=params.terminal_growth_std,
            min_bound=policy.terminal_min,
            max_bound=policy.terminal_max,
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

    initial_revenue = static_inputs["initial_revenue"]
    tax_rate = static_inputs["tax_rate"]
    cash = static_inputs["cash"]
    total_debt = static_inputs["total_debt"]
    preferred_stock = static_inputs["preferred_stock"]
    shares_outstanding = static_inputs["shares_outstanding"]
    years = base_growth.shape[0]
    discount_years = np.arange(1, years + 1, dtype=float)

    def batch_evaluate(
        sampled_batch: dict[str, np.ndarray],
        _base: Mapping[str, float],
    ) -> np.ndarray:
        growth_shock = np.asarray(sampled_batch["growth_shock"], dtype=float)
        margin_shock = np.asarray(sampled_batch["margin_shock"], dtype=float)
        wacc = np.asarray(sampled_batch["wacc"], dtype=float)
        sampled_terminal = np.asarray(sampled_batch["terminal_growth"], dtype=float)
        terminal_growth = np.minimum(sampled_terminal, wacc - 0.005)

        batch_size = growth_shock.shape[0]

        growth_base = base_growth[np.newaxis, :]
        margin_base = base_margin[np.newaxis, :]
        growth_lower = growth_base + policy.growth_clip_min
        growth_upper = growth_base + policy.growth_clip_max
        margin_lower = margin_base + policy.margin_clip_min
        margin_upper = margin_base + policy.margin_clip_max

        growth_rates = np.clip(
            growth_base + growth_shock[:, np.newaxis],
            growth_lower,
            growth_upper,
        )
        margins = np.clip(
            margin_base + margin_shock[:, np.newaxis],
            margin_lower,
            margin_upper,
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
        previous_revenue = np.empty_like(projected_revenue)
        previous_revenue[:, 0] = initial_revenue
        previous_revenue[:, 1:] = projected_revenue[:, :-1]
        delta_wc = (projected_revenue - previous_revenue) * wc_rates[np.newaxis, :]
        fcff = nopat + da - capex - delta_wc

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

    base_case_inputs = {
        key: np.asarray([value], dtype=float)
        for key, value in base_numeric_inputs.items()
    }
    base_case_intrinsic = float(
        batch_evaluate(base_case_inputs, base_numeric_inputs)[0]
    )

    result = engine.run(
        base_inputs=base_numeric_inputs,
        distributions=distributions,
        batch_evaluator=batch_evaluate,
        correlation_groups=correlation_groups,
    )
    diagnostics = dict(result.diagnostics)
    diagnostics["base_case_intrinsic_value"] = base_case_intrinsic
    return {
        "metric_type": "intrinsic_value_per_share",
        "summary": result.summary,
        "diagnostics": diagnostics,
    }
