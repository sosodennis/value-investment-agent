from __future__ import annotations

from collections.abc import Callable, Mapping

import numpy as np

from .monte_carlo_contracts import (
    CorrelationGroup,
    DistributionSpec,
    MonteCarloConfig,
    MonteCarloResult,
)
from .monte_carlo_diagnostics_service import (
    build_convergence_diagnostics,
    build_summary,
)
from .monte_carlo_sampling_service import sample_variables


class MonteCarloEngine:
    def __init__(self, config: MonteCarloConfig) -> None:
        if config.iterations <= 0:
            raise ValueError("iterations must be positive")
        if config.min_iterations <= 0:
            raise ValueError("min_iterations must be positive")
        if config.batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if config.convergence_window <= 1:
            raise ValueError("convergence_window must be > 1")
        if config.dynamic_window_min <= 1:
            raise ValueError("dynamic_window_min must be > 1")
        if config.convergence_tolerance <= 0:
            raise ValueError("convergence_tolerance must be positive")
        if config.psd_eigen_floor <= 0:
            raise ValueError("psd_eigen_floor must be positive")
        if config.higham_max_iterations <= 0:
            raise ValueError("higham_max_iterations must be positive")
        if config.higham_tolerance <= 0:
            raise ValueError("higham_tolerance must be positive")
        if config.sampler_type not in {"pseudo", "sobol", "lhs"}:
            raise ValueError("sampler_type must be one of: pseudo, sobol, lhs")
        self._config = config

    def run(
        self,
        *,
        base_inputs: Mapping[str, float],
        distributions: Mapping[str, DistributionSpec],
        batch_evaluator: Callable[
            [dict[str, np.ndarray], Mapping[str, float]], np.ndarray
        ],
        correlation_groups: tuple[CorrelationGroup, ...] = (),
    ) -> MonteCarloResult:
        max_iterations = self._config.iterations
        min_iterations = min(max_iterations, self._config.min_iterations)
        batch_size = self._config.batch_size

        rng = np.random.default_rng(self._config.seed)
        sampled, sampling_diagnostics = sample_variables(
            rng=rng,
            distributions=distributions,
            correlation_groups=correlation_groups,
            iterations=max_iterations,
            config=self._config,
        )

        outcomes = np.zeros(max_iterations, dtype=float)
        executed_iterations = 0
        while executed_iterations < max_iterations:
            batch_end = min(executed_iterations + batch_size, max_iterations)
            batch_length = batch_end - executed_iterations
            sampled_batch = {
                name: values[executed_iterations:batch_end]
                for name, values in sampled.items()
            }
            batch_outcomes = np.asarray(
                batch_evaluator(sampled_batch, base_inputs), dtype=float
            )
            if batch_outcomes.shape != (batch_length,):
                raise ValueError(
                    "batch_evaluator must return one outcome per sampled row "
                    f"(expected={(batch_length,)}, actual={batch_outcomes.shape})"
                )
            outcomes[executed_iterations:batch_end] = batch_outcomes
            executed_iterations = batch_end

            if executed_iterations < min_iterations:
                continue

            interim_diagnostics = build_convergence_diagnostics(
                outcomes[:executed_iterations],
                config=self._config,
            )
            converged = bool(interim_diagnostics.get("converged"))
            sufficient_window = bool(interim_diagnostics.get("sufficient_window"))
            if converged and sufficient_window:
                break

        final_outcomes = outcomes[:executed_iterations]

        summary = build_summary(final_outcomes)
        diagnostics: dict[str, float | bool | int | str] = {
            **build_convergence_diagnostics(final_outcomes, config=self._config),
            "configured_iterations": max_iterations,
            "executed_iterations": executed_iterations,
            "stopped_early": executed_iterations < max_iterations,
            "batch_evaluator_used": True,
            **sampling_diagnostics,
        }
        return MonteCarloResult(summary=summary, diagnostics=diagnostics)


__all__ = [
    "CorrelationGroup",
    "DistributionSpec",
    "MonteCarloConfig",
    "MonteCarloEngine",
    "MonteCarloResult",
]
