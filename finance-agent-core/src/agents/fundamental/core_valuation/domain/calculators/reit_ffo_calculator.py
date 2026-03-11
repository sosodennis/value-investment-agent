from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, Protocol

import numpy as np

from src.agents.fundamental.core_valuation.domain.parameterization.types import (
    TraceInput,
)

from ..engine.graphs.reit_ffo import create_reit_ffo_graph
from ..engine.monte_carlo import (
    CorrelationGroup,
    DistributionSpec,
    MonteCarloConfig,
    MonteCarloEngine,
)
from .calculator_runtime_support import (
    apply_trace_inputs,
    compute_upside,
    unwrap_traceable_value,
)


class ReitFfoCalculatorParams(Protocol):
    ticker: str
    ffo: float
    ffo_multiple: float
    depreciation_and_amortization: float
    maintenance_capex_ratio: float
    cash: float
    total_debt: float
    preferred_stock: float
    shares_outstanding: float
    current_price: float | None
    trace_inputs: dict[str, TraceInput]
    monte_carlo_iterations: int
    monte_carlo_seed: int | None
    monte_carlo_sampler: Literal["pseudo", "sobol", "lhs"]
    occupancy_rate_left: float
    occupancy_rate_mode: float
    occupancy_rate_right: float
    cap_rate_std: float
    corr_occupancy_cap_rate: float


def _run_reit_monte_carlo(
    *,
    base_inputs: dict[str, float],
    params: ReitFfoCalculatorParams,
) -> dict[str, object]:
    config = MonteCarloConfig(
        iterations=params.monte_carlo_iterations,
        seed=params.monte_carlo_seed,
        sampler_type=params.monte_carlo_sampler,
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

    base_ffo = float(base_inputs["ffo"])
    depreciation_and_amortization = float(base_inputs["depreciation_and_amortization"])
    maintenance_capex_ratio = float(base_inputs["maintenance_capex_ratio"])
    cash = float(base_inputs["cash"])
    total_debt = float(base_inputs["total_debt"])
    preferred_stock = float(base_inputs["preferred_stock"])
    shares_outstanding = float(base_inputs["shares_outstanding"])
    occupancy_mode = max(float(params.occupancy_rate_mode), 1e-6)

    def batch_evaluate(
        sampled_batch: dict[str, np.ndarray],
        _base_numeric: Mapping[str, float],
    ) -> np.ndarray:
        occupancy_rate = np.asarray(sampled_batch["occupancy_rate"], dtype=float)
        cap_rate = np.asarray(sampled_batch["cap_rate"], dtype=float)
        cap_rate = np.maximum(cap_rate, 1e-6)
        # Anchor Monte Carlo base case to deterministic valuation at occupancy mode.
        occupancy_multiplier = occupancy_rate / occupancy_mode
        ffo = base_ffo * occupancy_multiplier
        maintenance_capex = depreciation_and_amortization * maintenance_capex_ratio
        affo = ffo - maintenance_capex
        enterprise_value = affo / cap_rate
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


def calculate_reit_ffo_valuation(
    params: ReitFfoCalculatorParams,
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
        traced_inputs = apply_trace_inputs(raw_inputs, params.trace_inputs)
        results = graph.calculate(traced_inputs, trace=True)
        intrinsic_value = float(
            unwrap_traceable_value(results.get("intrinsic_value", 0.0))
        )
        upside = compute_upside(intrinsic_value, params.current_price)

        details: dict[str, object] = {
            "ffo": params.ffo,
            "affo": float(unwrap_traceable_value(results.get("affo", 0.0))),
            "ffo_multiple": params.ffo_multiple,
            "maintenance_capex": float(
                unwrap_traceable_value(results.get("maintenance_capex", 0.0))
            ),
            "maintenance_capex_ratio": params.maintenance_capex_ratio,
        }
        if params.monte_carlo_iterations > 0:
            details["distribution_summary"] = _run_reit_monte_carlo(
                base_inputs=raw_inputs,
                params=params,
            )

        return {
            "ticker": params.ticker,
            "enterprise_value": float(
                unwrap_traceable_value(results.get("enterprise_value", 0.0))
            ),
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
