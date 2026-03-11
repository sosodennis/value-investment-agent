from __future__ import annotations

import statistics
import time

import numpy as np

from src.agents.fundamental.subdomains.core_valuation.domain.engine.monte_carlo import (
    CorrelationGroup,
    DistributionSpec,
    MonteCarloConfig,
    MonteCarloEngine,
)


def _run_fixed_monte_carlo_case() -> None:
    config = MonteCarloConfig(
        iterations=3_000,
        seed=123,
        sampler_type="sobol",
        min_iterations=1_500,
        batch_size=300,
        convergence_window=300,
        dynamic_window_min=80,
    )
    engine = MonteCarloEngine(config)

    distributions = {
        "growth": DistributionSpec(kind="normal", mean=0.10, std=0.03),
        "margin": DistributionSpec(kind="normal", mean=0.22, std=0.02),
        "discount": DistributionSpec(
            kind="triangular",
            left=0.07,
            mode=0.09,
            right=0.12,
            min_bound=0.05,
            max_bound=0.16,
        ),
        "terminal": DistributionSpec(kind="uniform", low=0.01, high=0.03),
    }
    correlations = (
        CorrelationGroup(
            variables=("growth", "margin", "discount"),
            matrix=((1.0, 0.25, -0.10), (0.25, 1.0, -0.20), (-0.10, -0.20, 1.0)),
        ),
    )

    def _batch_eval(
        sampled: dict[str, np.ndarray],
        base_inputs: dict[str, float],
    ) -> np.ndarray:
        base = base_inputs["base"]
        growth = sampled["growth"]
        margin = sampled["margin"]
        discount = sampled["discount"]
        terminal = sampled["terminal"]
        return (
            base * (1.0 + growth) * (1.0 + margin)
            + (terminal * 10.0)
            - (discount * 8.0)
        )

    result = engine.run(
        base_inputs={"base": 100.0},
        distributions=distributions,
        batch_evaluator=_batch_eval,
        correlation_groups=correlations,
    )
    assert result.diagnostics["executed_iterations"] >= 1_500


def test_fundamental_monte_carlo_fixed_case_latency_budget() -> None:
    # Warmup avoids one-time initialization overhead in measured runs.
    for _ in range(2):
        _run_fixed_monte_carlo_case()

    timings_ms: list[float] = []
    for _ in range(5):
        start = time.perf_counter()
        _run_fixed_monte_carlo_case()
        timings_ms.append((time.perf_counter() - start) * 1000.0)

    p50_ms = statistics.median(timings_ms)
    assert p50_ms < 900.0
