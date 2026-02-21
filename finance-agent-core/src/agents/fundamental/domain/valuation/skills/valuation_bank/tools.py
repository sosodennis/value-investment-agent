from typing import cast

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


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _run_bank_monte_carlo(
    *,
    graph,
    base_inputs: dict[str, float | list[float] | None],
    params: BankParams,
) -> dict[str, object]:
    config = MonteCarloConfig(
        iterations=params.monte_carlo_iterations,
        seed=params.monte_carlo_seed,
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

    def evaluate(sampled: dict[str, float]) -> float:
        iter_inputs = dict(base_inputs)

        provision_rate = sampled["provision_rate"]
        income_growth_shock = sampled["income_growth_shock"]
        iter_inputs["initial_net_income"] = params.initial_net_income * (
            1.0 - provision_rate
        )
        iter_inputs["income_growth_rates"] = [
            _clamp(rate + income_growth_shock, -0.80, 1.50)
            for rate in cast(list[float], base_inputs["income_growth_rates"])
        ]

        sampled_risk_free = sampled["risk_free_rate"]
        sampled_terminal = sampled["terminal_growth"]
        projected_coe = (
            params.cost_of_equity_override
            if params.cost_of_equity_strategy == "override"
            and params.cost_of_equity_override is not None
            else sampled_risk_free + (params.beta * params.market_risk_premium)
        )
        if sampled_terminal >= projected_coe:
            sampled_terminal = projected_coe - 0.001

        iter_inputs["risk_free_rate"] = sampled_risk_free
        iter_inputs["terminal_growth"] = sampled_terminal

        raw_result = graph.calculate(iter_inputs)
        return float(_unwrap(raw_result.get("intrinsic_value", 0.0)))

    result = engine.run(
        base_inputs=base_numeric_inputs,
        distributions=distributions,
        evaluator=evaluate,
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
                graph=graph,
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
