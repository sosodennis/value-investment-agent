from collections.abc import Mapping

import numpy as np

from src.shared.kernel.traceable import TraceableField

from ...engine.graphs.bank_ddm import create_bank_graph
from ...engine.monte_carlo import (
    CorrelationGroup,
    DistributionSpec,
    MonteCarloConfig,
    MonteCarloEngine,
)
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


def _run_bank_monte_carlo(
    *,
    base_inputs: dict[str, float | list[float] | None],
    params: BankParams,
) -> dict[str, object]:
    config = MonteCarloConfig(
        iterations=params.monte_carlo_iterations,
        seed=params.monte_carlo_seed,
        sampler_type=params.monte_carlo_sampler,
    )
    engine = MonteCarloEngine(config=config)

    distributions: dict[str, DistributionSpec] = {
        "provision_rate": DistributionSpec(
            kind="normal",
            mean=params.provision_rate_mean,
            std=params.provision_rate_std,
            min_bound=0.0,
            max_bound=0.30,
        ),
        "income_growth_shock": DistributionSpec(
            kind="normal",
            mean=0.0,
            std=params.income_growth_shock_std,
            min_bound=-0.30,
            max_bound=0.30,
        ),
        "risk_free_rate": DistributionSpec(
            kind="normal",
            mean=params.risk_free_rate,
            std=params.risk_free_rate_std,
            min_bound=0.0,
            max_bound=0.20,
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
            variables=("risk_free_rate", "terminal_growth"),
            matrix=(
                (1.0, params.corr_risk_free_terminal_growth),
                (params.corr_risk_free_terminal_growth, 1.0),
            ),
        ),
    )

    base_numeric_inputs = {
        "provision_rate": params.provision_rate_mean,
        "income_growth_shock": 0.0,
        "risk_free_rate": params.risk_free_rate,
        "terminal_growth": params.terminal_growth,
    }

    base_growth_rates = np.asarray(base_inputs["income_growth_rates"], dtype=float)
    initial_net_income = float(params.initial_net_income)
    rwa_intensity = float(base_inputs["rwa_intensity"])
    tier1_target_ratio = float(base_inputs["tier1_target_ratio"])
    initial_capital = float(base_inputs["initial_capital"])
    beta = float(base_inputs["beta"])
    market_risk_premium = float(base_inputs["market_risk_premium"])
    shares_outstanding = float(base_inputs["shares_outstanding"])
    use_override = (
        params.cost_of_equity_strategy == "override"
        and params.cost_of_equity_override is not None
    )
    override_cost = float(params.cost_of_equity_override or 0.0)

    def batch_evaluate(
        sampled_batch: dict[str, np.ndarray], _base_numeric: Mapping[str, float]
    ) -> np.ndarray:
        provision_rate = np.asarray(sampled_batch["provision_rate"], dtype=float)
        income_growth_shock = np.asarray(
            sampled_batch["income_growth_shock"], dtype=float
        )
        sampled_risk_free = np.asarray(sampled_batch["risk_free_rate"], dtype=float)
        sampled_terminal = np.asarray(sampled_batch["terminal_growth"], dtype=float)

        batch_size = provision_rate.shape[0]
        projection_years = base_growth_rates.shape[0]

        adjusted_initial_income = initial_net_income * (1.0 - provision_rate)
        growth_rates = np.clip(
            base_growth_rates[np.newaxis, :] + income_growth_shock[:, np.newaxis],
            -0.80,
            1.50,
        )
        net_income = np.empty((batch_size, projection_years), dtype=float)
        income_level = adjusted_initial_income.copy()
        for year_idx in range(projection_years):
            income_level = income_level * (1.0 + growth_rates[:, year_idx])
            net_income[:, year_idx] = income_level

        rwa = net_income / rwa_intensity
        required_capital = rwa * tier1_target_ratio
        previous_capital = np.concatenate(
            [
                np.full((batch_size, 1), initial_capital, dtype=float),
                required_capital[:, :-1],
            ],
            axis=1,
        )
        delta_capital = required_capital - previous_capital
        dividends = net_income - delta_capital

        if use_override:
            cost_of_equity = np.full(batch_size, override_cost, dtype=float)
        else:
            cost_of_equity = sampled_risk_free + (beta * market_risk_premium)
        terminal_growth = np.minimum(sampled_terminal, cost_of_equity - 0.001)

        discount_years = np.arange(1, projection_years + 1, dtype=float)
        discount_curve = np.power(
            1.0 + cost_of_equity[:, np.newaxis], discount_years[np.newaxis, :]
        )
        pv_dividends = np.sum(dividends / discount_curve, axis=1)
        last_dividend = dividends[:, -1]
        terminal_value = (
            last_dividend * (1.0 + terminal_growth) / (cost_of_equity - terminal_growth)
        )
        pv_terminal = terminal_value / np.power(1.0 + cost_of_equity, projection_years)
        equity_value = pv_dividends + pv_terminal
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


def _validate_bank_inputs(params: BankParams) -> str | None:
    if params.shares_outstanding <= 0:
        return "shares_outstanding must be positive for per-share valuation"
    if params.initial_capital <= 0:
        return "initial_capital must be positive"
    if params.rwa_intensity <= 0 or params.rwa_intensity > 0.20:
        return "rwa_intensity must be in (0, 0.20]"
    if params.tier1_target_ratio <= 0 or params.tier1_target_ratio > 0.30:
        return "tier1_target_ratio must be in (0, 0.30]"
    return None


def calculate_bank_valuation(
    params: BankParams,
) -> dict[str, float | str | dict[str, object]]:
    """
    Executes the Bank DDM Valuation Graph.
    """
    graph = create_bank_graph()

    validation_error = _validate_bank_inputs(params)
    if validation_error is not None:
        return {"error": validation_error}

    manual_cost = (
        params.cost_of_equity_override
        if params.cost_of_equity_override is not None
        else params.cost_of_equity
    )
    cost_of_equity_override = (
        manual_cost if params.cost_of_equity_strategy == "override" else None
    )
    if params.cost_of_equity_strategy == "override" and cost_of_equity_override is None:
        return {"error": "cost_of_equity_override is required when strategy=override"}

    raw_inputs = {
        "initial_net_income": params.initial_net_income,
        "income_growth_rates": params.income_growth_rates,
        "rwa_intensity": params.rwa_intensity,
        "tier1_target_ratio": params.tier1_target_ratio,
        "initial_capital": params.initial_capital,
        "risk_free_rate": params.risk_free_rate,
        "beta": params.beta,
        "market_risk_premium": params.market_risk_premium,
        "cost_of_equity_override": cost_of_equity_override,
        "terminal_growth": params.terminal_growth,
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
        details: dict[str, object] = {"trace": results}
        if params.monte_carlo_iterations > 0:
            details["distribution_summary"] = _run_bank_monte_carlo(
                # MC evaluator expects numeric/list values (not TraceableField wrappers).
                base_inputs=raw_inputs,
                params=params,
            )
        return {
            "ticker": params.ticker,
            "equity_value": float(_unwrap(results.get("equity_value", 0.0))),
            "intrinsic_value": intrinsic_value,
            "upside_potential": upside,
            "cost_of_equity": float(_unwrap(results.get("cost_of_equity", 0.0))),
            "shares_outstanding_used": params.shares_outstanding,
            "details": details,
            "trace": results,
        }
    except Exception as e:
        return {"error": str(e)}
