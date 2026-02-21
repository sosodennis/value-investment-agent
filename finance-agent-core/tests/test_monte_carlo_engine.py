from __future__ import annotations

import pytest

from src.agents.fundamental.domain.valuation.engine.monte_carlo import (
    CorrelationGroup,
    DistributionSpec,
    MonteCarloConfig,
    MonteCarloEngine,
)


def test_monte_carlo_engine_reproducible_with_seed() -> None:
    engine = MonteCarloEngine(MonteCarloConfig(iterations=2000, seed=7))
    distributions = {
        "x": DistributionSpec(kind="normal", mean=10.0, std=2.0),
    }

    result_a = engine.run(
        base_inputs={},
        distributions=distributions,
        evaluator=lambda sampled: sampled["x"] * 2.0,
    )
    result_b = engine.run(
        base_inputs={},
        distributions=distributions,
        evaluator=lambda sampled: sampled["x"] * 2.0,
    )

    assert result_a.summary["median"] == pytest.approx(result_b.summary["median"])
    assert result_a.summary["percentile_5"] == pytest.approx(
        result_b.summary["percentile_5"]
    )
    assert result_a.summary["percentile_95"] == pytest.approx(
        result_b.summary["percentile_95"]
    )


def test_monte_carlo_engine_applies_bounds() -> None:
    engine = MonteCarloEngine(MonteCarloConfig(iterations=1000, seed=11))
    distributions = {
        "x": DistributionSpec(
            kind="normal",
            mean=0.0,
            std=10.0,
            min_bound=-1.0,
            max_bound=1.0,
        ),
    }
    result = engine.run(
        base_inputs={},
        distributions=distributions,
        evaluator=lambda sampled: sampled["x"],
    )

    assert result.summary["min"] >= -1.0
    assert result.summary["max"] <= 1.0


def test_monte_carlo_engine_rejects_non_psd_covariance() -> None:
    engine = MonteCarloEngine(MonteCarloConfig(iterations=100, seed=1))
    distributions = {
        "a": DistributionSpec(kind="normal", mean=0.0, std=1.0),
        "b": DistributionSpec(kind="normal", mean=0.0, std=1.0),
    }
    correlation_groups = (
        CorrelationGroup(
            variables=("a", "b"),
            matrix=((1.0, 1.2), (1.2, 1.0)),
        ),
    )

    with pytest.raises(ValueError, match="PSD"):
        engine.run(
            base_inputs={},
            distributions=distributions,
            evaluator=lambda sampled: sampled["a"] + sampled["b"],
            correlation_groups=correlation_groups,
        )


def test_monte_carlo_engine_supports_correlated_non_normal_distributions() -> None:
    engine = MonteCarloEngine(MonteCarloConfig(iterations=2000, seed=9))
    distributions = {
        "occ": DistributionSpec(kind="triangular", left=0.7, mode=0.9, right=0.98),
        "cap": DistributionSpec(kind="uniform", low=0.04, high=0.10),
    }
    correlation_groups = (
        CorrelationGroup(
            variables=("occ", "cap"),
            matrix=((1.0, -0.5), (-0.5, 1.0)),
        ),
    )
    result = engine.run(
        base_inputs={},
        distributions=distributions,
        evaluator=lambda sampled: sampled["occ"] - sampled["cap"],
        correlation_groups=correlation_groups,
    )

    assert "median" in result.summary
    assert "percentile_25" in result.summary
    assert "percentile_75" in result.summary
    assert result.summary["min"] <= result.summary["median"] <= result.summary["max"]


def test_monte_carlo_engine_diagnostics_are_json_safe_for_small_samples() -> None:
    engine = MonteCarloEngine(
        MonteCarloConfig(
            iterations=100,
            seed=5,
            convergence_window=80,
            dynamic_window_min=80,
        )
    )
    distributions = {
        "x": DistributionSpec(kind="normal", mean=1.0, std=0.2),
    }
    result = engine.run(
        base_inputs={},
        distributions=distributions,
        evaluator=lambda sampled: sampled["x"],
    )

    diagnostics = result.diagnostics
    assert diagnostics["converged"] is False
    assert diagnostics["sufficient_window"] is False
    assert diagnostics["effective_window"] == 80
    assert diagnostics["median_delta"] == 0.0


def test_monte_carlo_engine_stops_early_when_converged() -> None:
    engine = MonteCarloEngine(
        MonteCarloConfig(
            iterations=2000,
            min_iterations=300,
            batch_size=100,
            convergence_window=120,
            dynamic_window_min=50,
            seed=17,
        )
    )
    distributions = {
        "x": DistributionSpec(kind="normal", mean=1.0, std=0.01),
    }
    result = engine.run(
        base_inputs={},
        distributions=distributions,
        evaluator=lambda _sampled: 1.0,
    )

    diagnostics = result.diagnostics
    assert diagnostics["converged"] is True
    assert diagnostics["sufficient_window"] is True
    assert diagnostics["stopped_early"] is True
    assert diagnostics["executed_iterations"] == 300
