from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from math import erf, sqrt
from typing import Literal

import numpy as np


@dataclass(frozen=True)
class DistributionSpec:
    kind: Literal["normal", "uniform", "triangular"]
    mean: float | None = None
    std: float | None = None
    low: float | None = None
    high: float | None = None
    left: float | None = None
    mode: float | None = None
    right: float | None = None
    min_bound: float | None = None
    max_bound: float | None = None


@dataclass(frozen=True)
class CorrelationGroup:
    variables: tuple[str, ...]
    matrix: tuple[tuple[float, ...], ...]


@dataclass(frozen=True)
class MonteCarloConfig:
    iterations: int = 10_000
    seed: int | None = None
    min_iterations: int = 500
    batch_size: int = 500
    convergence_window: int = 250
    dynamic_window_min: int = 50
    convergence_tolerance: float = 0.002


@dataclass(frozen=True)
class MonteCarloResult:
    summary: dict[str, float]
    diagnostics: dict[str, float | bool | int]


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
        self._config = config

    def run(
        self,
        *,
        base_inputs: Mapping[str, float],
        distributions: Mapping[str, DistributionSpec],
        evaluator: Callable[[dict[str, float]], float],
        correlation_groups: tuple[CorrelationGroup, ...] = (),
    ) -> MonteCarloResult:
        max_iterations = self._config.iterations
        min_iterations = min(max_iterations, self._config.min_iterations)
        batch_size = self._config.batch_size

        rng = np.random.default_rng(self._config.seed)
        sampled = self._sample_variables(
            rng=rng,
            distributions=distributions,
            correlation_groups=correlation_groups,
            iterations=max_iterations,
        )

        outcomes = np.zeros(max_iterations, dtype=float)
        executed_iterations = 0
        while executed_iterations < max_iterations:
            batch_end = min(executed_iterations + batch_size, max_iterations)
            for idx in range(executed_iterations, batch_end):
                inputs = dict(base_inputs)
                for name, values in sampled.items():
                    inputs[name] = float(values[idx])
                outcomes[idx] = float(evaluator(inputs))
            executed_iterations = batch_end

            if executed_iterations < min_iterations:
                continue

            interim_diagnostics = self._build_diagnostics(
                outcomes[:executed_iterations]
            )
            converged = bool(interim_diagnostics.get("converged"))
            sufficient_window = bool(interim_diagnostics.get("sufficient_window"))
            if converged and sufficient_window:
                break

        final_outcomes = outcomes[:executed_iterations]

        summary = self._build_summary(final_outcomes)
        diagnostics = self._build_diagnostics(final_outcomes)
        diagnostics["configured_iterations"] = max_iterations
        diagnostics["executed_iterations"] = executed_iterations
        diagnostics["stopped_early"] = executed_iterations < max_iterations
        return MonteCarloResult(summary=summary, diagnostics=diagnostics)

    def _sample_variables(
        self,
        *,
        rng: np.random.Generator,
        distributions: Mapping[str, DistributionSpec],
        correlation_groups: tuple[CorrelationGroup, ...],
        iterations: int,
    ) -> dict[str, np.ndarray]:
        sampled: dict[str, np.ndarray] = {}
        grouped_vars: set[str] = set()

        for group in correlation_groups:
            group_samples = self._sample_correlation_group(
                rng=rng,
                group=group,
                distributions=distributions,
                iterations=iterations,
            )
            sampled.update(group_samples)
            grouped_vars.update(group.variables)

        for name, spec in distributions.items():
            if name in grouped_vars:
                continue
            sampled[name] = self._sample_distribution(rng, spec, iterations)

        return sampled

    def _sample_correlation_group(
        self,
        *,
        rng: np.random.Generator,
        group: CorrelationGroup,
        distributions: Mapping[str, DistributionSpec],
        iterations: int,
    ) -> dict[str, np.ndarray]:
        size = len(group.variables)
        if size == 0:
            raise ValueError("correlation group cannot be empty")
        if len(group.matrix) != size:
            raise ValueError("correlation matrix row count must match variable count")
        for row in group.matrix:
            if len(row) != size:
                raise ValueError(
                    "correlation matrix column count must match variable count"
                )

        specs: list[DistributionSpec] = []
        for var in group.variables:
            spec = distributions.get(var)
            if spec is None:
                raise ValueError(f"missing distribution for correlated variable {var}")
            self._validate_distribution_spec(spec)
            specs.append(spec)

        corr = np.array(group.matrix, dtype=float)
        if not np.allclose(corr, corr.T):
            raise ValueError("correlation matrix must be symmetric")
        if not np.allclose(np.diag(corr), 1.0):
            raise ValueError("correlation matrix diagonal must be 1")

        min_eigen = float(np.min(np.linalg.eigvalsh(corr)))
        if min_eigen < -1e-10:
            raise ValueError(
                f"covariance matrix is not PSD; minimum eigenvalue={min_eigen:.6g}"
            )

        draws = rng.multivariate_normal(
            np.zeros(size, dtype=float), corr, size=iterations
        )
        output: dict[str, np.ndarray] = {}
        for idx, var in enumerate(group.variables):
            output[var] = self._transform_standard_normal(draws[:, idx], specs[idx])
        return output

    @staticmethod
    def _sample_distribution(
        rng: np.random.Generator,
        spec: DistributionSpec,
        iterations: int,
    ) -> np.ndarray:
        MonteCarloEngine._validate_distribution_spec(spec)
        if spec.kind == "normal":
            values = rng.normal(spec.mean, spec.std, size=iterations)
        elif spec.kind == "uniform":
            values = rng.uniform(spec.low, spec.high, size=iterations)
        else:
            values = rng.triangular(spec.left, spec.mode, spec.right, size=iterations)

        return MonteCarloEngine._clip_bounds(values, spec.min_bound, spec.max_bound)

    @staticmethod
    def _clip_bounds(
        values: np.ndarray,
        min_bound: float | None,
        max_bound: float | None,
    ) -> np.ndarray:
        clipped = values
        if min_bound is not None:
            clipped = np.maximum(clipped, min_bound)
        if max_bound is not None:
            clipped = np.minimum(clipped, max_bound)
        return clipped

    @staticmethod
    def _validate_distribution_spec(spec: DistributionSpec) -> None:
        if spec.kind == "normal":
            if spec.mean is None or spec.std is None:
                raise ValueError("normal distribution requires mean and std")
            if spec.std <= 0:
                raise ValueError("normal distribution std must be positive")
            return
        if spec.kind == "uniform":
            if spec.low is None or spec.high is None:
                raise ValueError("uniform distribution requires low/high")
            if spec.low >= spec.high:
                raise ValueError("uniform distribution requires low < high")
            return
        if spec.left is None or spec.mode is None or spec.right is None:
            raise ValueError("triangular distribution requires left/mode/right")
        if not (spec.left <= spec.mode <= spec.right):
            raise ValueError("triangular distribution requires left <= mode <= right")
        if spec.left >= spec.right:
            raise ValueError("triangular distribution requires left < right")

    @classmethod
    def _transform_standard_normal(
        cls,
        z: np.ndarray,
        spec: DistributionSpec,
    ) -> np.ndarray:
        if spec.kind == "normal":
            values = spec.mean + (spec.std * z)
        else:
            u = cls._normal_cdf(z)
            if spec.kind == "uniform":
                values = spec.low + ((spec.high - spec.low) * u)
            else:
                values = cls._inverse_triangular_cdf(
                    u,
                    left=spec.left,
                    mode=spec.mode,
                    right=spec.right,
                )
        return cls._clip_bounds(values, spec.min_bound, spec.max_bound)

    @staticmethod
    def _normal_cdf(z: np.ndarray) -> np.ndarray:
        u = np.array(
            [0.5 * (1.0 + erf(float(value) / sqrt(2.0))) for value in z], dtype=float
        )
        return np.clip(u, 1e-12, 1.0 - 1e-12)

    @staticmethod
    def _inverse_triangular_cdf(
        u: np.ndarray,
        *,
        left: float,
        mode: float,
        right: float,
    ) -> np.ndarray:
        split = (mode - left) / (right - left)
        lower = left + np.sqrt(u * (right - left) * (mode - left))
        upper = right - np.sqrt((1.0 - u) * (right - left) * (right - mode))
        return np.where(u < split, lower, upper)

    @staticmethod
    def _build_summary(outcomes: np.ndarray) -> dict[str, float]:
        return {
            "mean": float(np.mean(outcomes)),
            "median": float(np.median(outcomes)),
            "std": float(np.std(outcomes)),
            "percentile_5": float(np.percentile(outcomes, 5)),
            "percentile_95": float(np.percentile(outcomes, 95)),
            "min": float(np.min(outcomes)),
            "max": float(np.max(outcomes)),
        }

    def _build_diagnostics(self, outcomes: np.ndarray) -> dict[str, float | bool | int]:
        sample_size = len(outcomes)
        configured_window = self._config.convergence_window
        effective_window = min(
            configured_window,
            max(self._config.dynamic_window_min, sample_size // 3),
        )
        if sample_size < effective_window * 2:
            return {
                "iterations": sample_size,
                "converged": False,
                "sufficient_window": False,
                "window": configured_window,
                "effective_window": effective_window,
                # Keep JSON-safe finite numeric values for frontend contracts.
                "median_delta": 0.0,
                "tolerance": self._config.convergence_tolerance,
            }

        prev = outcomes[-(effective_window * 2) : -effective_window]
        curr = outcomes[-effective_window:]
        prev_median = float(np.median(prev))
        curr_median = float(np.median(curr))
        denominator = abs(prev_median) if abs(prev_median) > 1e-9 else 1.0
        delta = abs(curr_median - prev_median) / denominator
        return {
            "iterations": sample_size,
            "converged": delta <= self._config.convergence_tolerance,
            "sufficient_window": True,
            "window": configured_window,
            "effective_window": effective_window,
            "median_delta": float(delta),
            "tolerance": self._config.convergence_tolerance,
        }
