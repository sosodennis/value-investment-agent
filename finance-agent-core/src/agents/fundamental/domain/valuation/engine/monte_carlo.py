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
    psd_repair_policy: Literal["error", "clip", "higham"] = "clip"
    psd_eigen_floor: float = 1e-8
    psd_tolerance: float = -1e-10
    higham_max_iterations: int = 50
    higham_tolerance: float = 1e-9


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
        if config.psd_eigen_floor <= 0:
            raise ValueError("psd_eigen_floor must be positive")
        if config.higham_max_iterations <= 0:
            raise ValueError("higham_max_iterations must be positive")
        if config.higham_tolerance <= 0:
            raise ValueError("higham_tolerance must be positive")
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
        sampled, sampling_diagnostics = self._sample_variables(
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
        diagnostics.update(sampling_diagnostics)
        return MonteCarloResult(summary=summary, diagnostics=diagnostics)

    def _sample_variables(
        self,
        *,
        rng: np.random.Generator,
        distributions: Mapping[str, DistributionSpec],
        correlation_groups: tuple[CorrelationGroup, ...],
        iterations: int,
    ) -> tuple[dict[str, np.ndarray], dict[str, float | bool | int]]:
        sampled: dict[str, np.ndarray] = {}
        diagnostics: dict[str, float | bool | int] = {
            "psd_repaired": False,
            "psd_repaired_groups": 0,
            "psd_repair_failed_groups": 0,
            "psd_min_eigen_before": 0.0,
            "psd_min_eigen_after": 0.0,
            "psd_repair_clip_used": False,
            "psd_repair_higham_used": False,
        }
        grouped_vars: set[str] = set()

        for group in correlation_groups:
            group_samples, group_diag = self._sample_correlation_group(
                rng=rng,
                group=group,
                distributions=distributions,
                iterations=iterations,
            )
            sampled.update(group_samples)
            grouped_vars.update(group.variables)
            if bool(group_diag["psd_repaired"]):
                diagnostics["psd_repaired"] = True
                diagnostics["psd_repaired_groups"] = (
                    int(diagnostics["psd_repaired_groups"]) + 1
                )
            if bool(group_diag["psd_repair_failed"]):
                diagnostics["psd_repair_failed_groups"] = (
                    int(diagnostics["psd_repair_failed_groups"]) + 1
                )
            diagnostics["psd_repair_clip_used"] = bool(
                diagnostics["psd_repair_clip_used"]
            ) or bool(group_diag["psd_repair_clip_used"])
            diagnostics["psd_repair_higham_used"] = bool(
                diagnostics["psd_repair_higham_used"]
            ) or bool(group_diag["psd_repair_higham_used"])
            diagnostics["psd_min_eigen_before"] = min(
                float(diagnostics["psd_min_eigen_before"]),
                float(group_diag["psd_min_eigen_before"]),
            )
            diagnostics["psd_min_eigen_after"] = min(
                float(diagnostics["psd_min_eigen_after"]),
                float(group_diag["psd_min_eigen_after"]),
            )

        for name, spec in distributions.items():
            if name in grouped_vars:
                continue
            sampled[name] = self._sample_distribution(rng, spec, iterations)

        return sampled, diagnostics

    def _sample_correlation_group(
        self,
        *,
        rng: np.random.Generator,
        group: CorrelationGroup,
        distributions: Mapping[str, DistributionSpec],
        iterations: int,
    ) -> tuple[dict[str, np.ndarray], dict[str, float | bool | int]]:
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

        corr_psd, psd_diag = self._ensure_correlation_psd(corr)

        draws = rng.multivariate_normal(
            np.zeros(size, dtype=float), corr_psd, size=iterations
        )
        output: dict[str, np.ndarray] = {}
        for idx, var in enumerate(group.variables):
            output[var] = self._transform_standard_normal(draws[:, idx], specs[idx])
        return output, psd_diag

    def _ensure_correlation_psd(
        self, corr: np.ndarray
    ) -> tuple[np.ndarray, dict[str, float | bool | int]]:
        sym = self._symmetrize(corr)
        min_before = float(np.min(np.linalg.eigvalsh(sym)))
        diagnostics: dict[str, float | bool | int] = {
            "psd_repaired": False,
            "psd_repair_failed": False,
            "psd_repair_clip_used": False,
            "psd_repair_higham_used": False,
            "psd_min_eigen_before": min_before,
            "psd_min_eigen_after": min_before,
        }
        if min_before >= self._config.psd_tolerance:
            return sym, diagnostics

        policy = self._config.psd_repair_policy
        if policy == "error":
            diagnostics["psd_repair_failed"] = True
            raise ValueError(
                f"covariance matrix is not PSD; minimum eigenvalue={min_before:.6g}"
            )

        diagnostics["psd_repaired"] = True
        if policy == "higham":
            repaired = self._nearest_correlation_higham(sym)
            diagnostics["psd_repair_higham_used"] = True
        else:
            repaired = self._nearest_correlation_clip(sym)
            diagnostics["psd_repair_clip_used"] = True

        min_after = float(np.min(np.linalg.eigvalsh(repaired)))
        diagnostics["psd_min_eigen_after"] = min_after
        if min_after < self._config.psd_tolerance:
            diagnostics["psd_repair_failed"] = True
            raise ValueError(
                "unable to repair covariance matrix to PSD; "
                f"minimum eigenvalue after repair={min_after:.6g}"
            )
        return repaired, diagnostics

    @staticmethod
    def _symmetrize(matrix: np.ndarray) -> np.ndarray:
        return (matrix + matrix.T) / 2.0

    def _project_psd(self, matrix: np.ndarray) -> np.ndarray:
        eigvals, eigvecs = np.linalg.eigh(self._symmetrize(matrix))
        eigvals = np.maximum(eigvals, self._config.psd_eigen_floor)
        projected = (eigvecs * eigvals) @ eigvecs.T
        return self._symmetrize(projected)

    @staticmethod
    def _project_unit_diagonal(matrix: np.ndarray) -> np.ndarray:
        projected = matrix.copy()
        np.fill_diagonal(projected, 1.0)
        return projected

    def _normalize_to_correlation(self, matrix: np.ndarray) -> np.ndarray:
        diag = np.diag(matrix)
        safe_diag = np.where(diag > 0, diag, 1.0)
        scale = np.sqrt(safe_diag)
        normalized = matrix / np.outer(scale, scale)
        normalized = self._symmetrize(normalized)
        return self._project_unit_diagonal(normalized)

    def _nearest_correlation_clip(self, corr: np.ndarray) -> np.ndarray:
        clipped = self._project_psd(corr)
        normalized = self._normalize_to_correlation(clipped)
        # A second PSD projection mitigates tiny numerical negatives after normalize.
        repaired = self._project_psd(normalized)
        return self._normalize_to_correlation(repaired)

    def _nearest_correlation_higham(self, corr: np.ndarray) -> np.ndarray:
        # Higham nearest correlation via alternating projections with Dykstra correction.
        y = self._symmetrize(corr)
        delta_s = np.zeros_like(y)

        for _ in range(self._config.higham_max_iterations):
            y_prev = y
            r = y - delta_s
            x = self._project_psd(r)
            delta_s = x - r
            y = self._project_unit_diagonal(x)
            y = self._symmetrize(y)
            diff = np.linalg.norm(y - y_prev, ord="fro")
            denom = max(np.linalg.norm(y, ord="fro"), 1.0)
            if (diff / denom) <= self._config.higham_tolerance:
                break

        repaired = self._project_psd(y)
        return self._normalize_to_correlation(repaired)

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
            "percentile_25": float(np.percentile(outcomes, 25)),
            "percentile_75": float(np.percentile(outcomes, 75)),
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
