from __future__ import annotations

from src.shared.kernel.traceable import TraceableField

from ...engine.graphs.reit_ffo import create_reit_ffo_graph
from ...engine.monte_carlo import (
    CorrelationGroup,
    DistributionSpec,
    MonteCarloConfig,
    MonteCarloEngine,
)
from .schemas import ReitFfoParams


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


def _run_reit_monte_carlo(
    *,
    graph,
    base_inputs: dict[str, float],
    params: ReitFfoParams,
) -> dict[str, object]:
    config = MonteCarloConfig(
        iterations=params.monte_carlo_iterations,
        seed=params.monte_carlo_seed,
    )
    engine = MonteCarloEngine(config=config)

    base_cap_rate = 1.0 / params.ffo_multiple
    distributions: dict[str, DistributionSpec] = {
        "occupancy_rate": DistributionSpec(
            kind="triangular",
            left=params.occupancy_rate_left,
            mode=params.occupancy_rate_mode,
            right=params.occupancy_rate_right,
            min_bound=0.50,
            max_bound=1.00,
        ),
        "cap_rate": DistributionSpec(
            kind="normal",
            mean=base_cap_rate,
            std=params.cap_rate_std,
            min_bound=0.02,
            max_bound=0.25,
        ),
    }
    correlation_groups = (
        CorrelationGroup(
            variables=("occupancy_rate", "cap_rate"),
            matrix=(
                (1.0, params.corr_occupancy_cap_rate),
                (params.corr_occupancy_cap_rate, 1.0),
            ),
        ),
    )

    base_numeric_inputs = {
        "occupancy_rate": params.occupancy_rate_mode,
        "cap_rate": base_cap_rate,
    }

    def evaluate(sampled: dict[str, float]) -> float:
        iter_inputs = dict(base_inputs)
        occupancy_rate = sampled["occupancy_rate"]
        cap_rate = sampled["cap_rate"]
        iter_inputs["ffo"] = params.ffo * occupancy_rate
        iter_inputs["ffo_multiple"] = 1.0 / cap_rate
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


def calculate_reit_ffo_valuation(
    params: ReitFfoParams,
) -> dict[str, float | str | dict[str, object]]:
    graph = create_reit_ffo_graph()

    raw_inputs = {
        "ffo": params.ffo,
        "ffo_multiple": params.ffo_multiple,
        "depreciation_and_amortization": params.depreciation_and_amortization,
        "maintenance_capex_ratio": params.maintenance_capex_ratio,
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

        details = {
            "ffo": params.ffo,
            "affo": float(_unwrap(results.get("affo", 0.0))),
            "ffo_multiple": params.ffo_multiple,
            "maintenance_capex": float(_unwrap(results.get("maintenance_capex", 0.0))),
            "maintenance_capex_ratio": params.maintenance_capex_ratio,
        }
        if params.monte_carlo_iterations > 0:
            details["distribution_summary"] = _run_reit_monte_carlo(
                graph=graph,
                # Keep Monte Carlo sampling on raw numeric inputs.
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
