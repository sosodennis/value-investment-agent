from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from math import ceil, erf, log2, sqrt
from typing import Literal

import numpy as np

try:
    from scipy.stats import qmc as scipy_qmc
except Exception:  # pragma: no cover - optional runtime dependency guard
    scipy_qmc = None


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
    sampler_type: Literal["pseudo", "sobol", "lhs"] = "sobol"
    sobol_scramble: bool = True
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
    diagnostics: dict[str, float | bool | int | str]


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
        diagnostics["batch_evaluator_used"] = True
        diagnostics.update(sampling_diagnostics)
        return MonteCarloResult(summary=summary, diagnostics=diagnostics)

    def _sample_variables(
        self,
        *,
        rng: np.random.Generator,
        distributions: Mapping[str, DistributionSpec],
        correlation_groups: tuple[CorrelationGroup, ...],
        iterations: int,
    ) -> tuple[dict[str, np.ndarray], dict[str, float | bool | int | str]]:
        self._validate_correlation_group_variables(correlation_groups)
        sampled: dict[str, np.ndarray] = {}
        sampler_requested = self._config.sampler_type
        sampler_effective, sampler_fallback_reason = self._resolve_sampler_type(
            sampler_requested
        )
        diagnostics: dict[str, float | bool | int | str] = {
            "sampler_requested": sampler_requested,
            "sampler_type": sampler_effective,
            "sampler_fallback_used": sampler_effective != sampler_requested,
            "psd_repaired": False,
            "psd_repaired_groups": 0,
            "psd_repair_failed_groups": 0,
            "psd_min_eigen_before": 0.0,
            "psd_min_eigen_after": 0.0,
            "psd_repair_clip_used": False,
            "psd_repair_higham_used": False,
            "corr_diagnostics_available": False,
            "corr_pairs_total": 0,
            "corr_pearson_mae": 0.0,
            "corr_pearson_max_abs_error": 0.0,
            "corr_spearman_mae": 0.0,
            "corr_spearman_max_abs_error": 0.0,
        }
        if sampler_fallback_reason is not None:
            diagnostics["sampler_fallback_reason"] = sampler_fallback_reason
        grouped_vars: set[str] = set()

        for group in correlation_groups:
            group_samples, group_diag = self._sample_correlation_group(
                rng=rng,
                group=group,
                distributions=distributions,
                sampler_type=sampler_effective,
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
            pair_count = int(group_diag["corr_pairs_total"])
            if pair_count > 0:
                total_pairs = int(diagnostics["corr_pairs_total"])
                new_total = total_pairs + pair_count
                old_pearson_mae = float(diagnostics["corr_pearson_mae"])
                old_spearman_mae = float(diagnostics["corr_spearman_mae"])
                diagnostics["corr_pearson_mae"] = (
                    (old_pearson_mae * total_pairs)
                    + (float(group_diag["corr_pearson_mae"]) * pair_count)
                ) / new_total
                diagnostics["corr_spearman_mae"] = (
                    (old_spearman_mae * total_pairs)
                    + (float(group_diag["corr_spearman_mae"]) * pair_count)
                ) / new_total
                diagnostics["corr_pairs_total"] = new_total
                diagnostics["corr_diagnostics_available"] = True
                diagnostics["corr_pearson_max_abs_error"] = max(
                    float(diagnostics["corr_pearson_max_abs_error"]),
                    float(group_diag["corr_pearson_max_abs_error"]),
                )
                diagnostics["corr_spearman_max_abs_error"] = max(
                    float(diagnostics["corr_spearman_max_abs_error"]),
                    float(group_diag["corr_spearman_max_abs_error"]),
                )

        ungrouped_items = [
            (name, spec)
            for name, spec in distributions.items()
            if name not in grouped_vars
        ]
        if ungrouped_items:
            unit_cube = self._sample_unit_cube(
                rng=rng,
                iterations=iterations,
                dimensions=len(ungrouped_items),
                sampler_type=sampler_effective,
            )
            for idx, (name, spec) in enumerate(ungrouped_items):
                sampled[name] = self._transform_unit_samples(unit_cube[:, idx], spec)

        return sampled, diagnostics

    def _sample_correlation_group(
        self,
        *,
        rng: np.random.Generator,
        group: CorrelationGroup,
        distributions: Mapping[str, DistributionSpec],
        sampler_type: Literal["pseudo", "sobol", "lhs"],
        iterations: int,
    ) -> tuple[dict[str, np.ndarray], dict[str, float | bool | int | str]]:
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

        unit_cube = self._sample_unit_cube(
            rng=rng,
            iterations=iterations,
            dimensions=size,
            sampler_type=sampler_type,
        )
        independent_normals = self._normal_ppf(unit_cube)
        chol = np.linalg.cholesky(corr_psd)
        draws = independent_normals @ chol.T
        output: dict[str, np.ndarray] = {}
        for idx, var in enumerate(group.variables):
            output[var] = self._transform_standard_normal(draws[:, idx], specs[idx])
        corr_diag = self._build_correlation_diagnostics(
            variables=group.variables,
            target_corr=corr_psd,
            latent_draws=draws,
            transformed_samples=output,
        )
        return output, {**psd_diag, **corr_diag}

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
    def _validate_correlation_group_variables(
        correlation_groups: tuple[CorrelationGroup, ...],
    ) -> None:
        seen: dict[str, int] = {}
        repeated_across_groups: set[str] = set()
        for group_index, group in enumerate(correlation_groups):
            local_seen: set[str] = set()
            for var in group.variables:
                if var in local_seen:
                    raise ValueError(
                        "correlation group variables must be unique "
                        f"(group_index={group_index}, variable={var})"
                    )
                local_seen.add(var)
                if var in seen:
                    repeated_across_groups.add(var)
                else:
                    seen[var] = group_index

        if repeated_across_groups:
            repeated_list = ", ".join(sorted(repeated_across_groups))
            raise ValueError(
                "correlated variables cannot appear in multiple groups: "
                f"{repeated_list}"
            )

    def _build_correlation_diagnostics(
        self,
        *,
        variables: tuple[str, ...],
        target_corr: np.ndarray,
        latent_draws: np.ndarray,
        transformed_samples: Mapping[str, np.ndarray],
    ) -> dict[str, float | int]:
        pair_count = len(variables) * (len(variables) - 1) // 2
        if pair_count <= 0:
            return {
                "corr_pairs_total": 0,
                "corr_pearson_mae": 0.0,
                "corr_pearson_max_abs_error": 0.0,
                "corr_spearman_mae": 0.0,
                "corr_spearman_max_abs_error": 0.0,
            }

        pearson_realized = np.corrcoef(latent_draws, rowvar=False)
        pearson_errors = np.abs(
            self._upper_triangle(pearson_realized - target_corr, k=1)
        )

        transformed_matrix = np.column_stack(
            [transformed_samples[var] for var in variables]
        )
        spearman_realized = self._spearman_corrcoef(transformed_matrix)
        spearman_target = self._gaussian_spearman_from_pearson(target_corr)
        spearman_errors = np.abs(
            self._upper_triangle(spearman_realized - spearman_target, k=1)
        )

        return {
            "corr_pairs_total": pair_count,
            "corr_pearson_mae": float(np.mean(pearson_errors)),
            "corr_pearson_max_abs_error": float(np.max(pearson_errors)),
            "corr_spearman_mae": float(np.mean(spearman_errors)),
            "corr_spearman_max_abs_error": float(np.max(spearman_errors)),
        }

    @staticmethod
    def _upper_triangle(matrix: np.ndarray, k: int = 1) -> np.ndarray:
        row_idx, col_idx = np.triu_indices(matrix.shape[0], k=k)
        return matrix[row_idx, col_idx]

    @staticmethod
    def _gaussian_spearman_from_pearson(pearson_corr: np.ndarray) -> np.ndarray:
        clipped = np.clip(pearson_corr / 2.0, -1.0, 1.0)
        spearman = (6.0 / np.pi) * np.arcsin(clipped)
        spearman = (spearman + spearman.T) / 2.0
        np.fill_diagonal(spearman, 1.0)
        return spearman

    @classmethod
    def _spearman_corrcoef(cls, matrix: np.ndarray) -> np.ndarray:
        ranks = np.apply_along_axis(cls._rankdata, 0, matrix)
        return np.corrcoef(ranks, rowvar=False)

    @staticmethod
    def _rankdata(values: np.ndarray) -> np.ndarray:
        n = len(values)
        order = np.argsort(values, kind="mergesort")
        sorted_values = values[order]
        ranks = np.empty(n, dtype=float)
        i = 0
        while i < n:
            j = i
            while j + 1 < n and sorted_values[j + 1] == sorted_values[i]:
                j += 1
            average_rank = (i + j + 2) / 2.0
            ranks[order[i : j + 1]] = average_rank
            i = j + 1
        return ranks

    def _resolve_sampler_type(
        self, requested: Literal["pseudo", "sobol", "lhs"]
    ) -> tuple[Literal["pseudo", "sobol", "lhs"], str | None]:
        if requested == "sobol" and scipy_qmc is None:
            return "pseudo", "sobol sampler unavailable (scipy missing)"
        return requested, None

    def _sample_unit_cube(
        self,
        *,
        rng: np.random.Generator,
        iterations: int,
        dimensions: int,
        sampler_type: Literal["pseudo", "sobol", "lhs"],
    ) -> np.ndarray:
        if dimensions <= 0:
            raise ValueError("dimensions must be positive")
        if iterations <= 0:
            raise ValueError("iterations must be positive")

        if sampler_type == "pseudo":
            return rng.random((iterations, dimensions))
        if sampler_type == "lhs":
            return self._sample_lhs(
                rng=rng, iterations=iterations, dimensions=dimensions
            )
        return self._sample_sobol(rng=rng, iterations=iterations, dimensions=dimensions)

    @staticmethod
    def _sample_lhs(
        *,
        rng: np.random.Generator,
        iterations: int,
        dimensions: int,
    ) -> np.ndarray:
        # Classic random LHS: stratify each marginal into N bins and permute per dim.
        lower = np.arange(iterations, dtype=float) / float(iterations)
        upper = (np.arange(iterations, dtype=float) + 1.0) / float(iterations)
        points = rng.random((iterations, dimensions))
        points = lower[:, None] + ((upper - lower)[:, None] * points)
        for dim in range(dimensions):
            permutation = rng.permutation(iterations)
            points[:, dim] = points[permutation, dim]
        return points

    def _sample_sobol(
        self,
        *,
        rng: np.random.Generator,
        iterations: int,
        dimensions: int,
    ) -> np.ndarray:
        if scipy_qmc is None:
            # Guarded by _resolve_sampler_type, but keep safe fallback.
            return rng.random((iterations, dimensions))

        seed_value = int(rng.integers(0, np.iinfo(np.uint32).max))
        sobol_engine = scipy_qmc.Sobol(
            d=dimensions,
            scramble=self._config.sobol_scramble,
            seed=seed_value,
        )
        m = int(ceil(log2(max(1, iterations))))
        sampled = sobol_engine.random_base2(m)
        if sampled.shape[0] < iterations:
            extra = sobol_engine.random(iterations - sampled.shape[0])
            sampled = np.vstack([sampled, extra])
        return sampled[:iterations]

    @classmethod
    def _transform_unit_samples(
        cls, u: np.ndarray, spec: DistributionSpec
    ) -> np.ndarray:
        cls._validate_distribution_spec(spec)
        clipped_u = np.clip(u, 1e-12, 1.0 - 1e-12)
        if spec.kind == "normal":
            z = cls._normal_ppf(clipped_u)
            values = spec.mean + (spec.std * z)
        elif spec.kind == "uniform":
            values = spec.low + ((spec.high - spec.low) * clipped_u)
        else:
            values = cls._inverse_triangular_cdf(
                clipped_u,
                left=spec.left,
                mode=spec.mode,
                right=spec.right,
            )
        return cls._clip_bounds(values, spec.min_bound, spec.max_bound)

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
    def _normal_ppf(u: np.ndarray) -> np.ndarray:
        # Acklam inverse-normal approximation (sufficient precision for MC sampling).
        p = np.clip(u, 1e-12, 1.0 - 1e-12)
        x = np.empty_like(p, dtype=float)

        a = np.array(
            [
                -39.6968302866538,
                220.946098424521,
                -275.928510446969,
                138.357751867269,
                -30.6647980661472,
                2.50662827745924,
            ],
            dtype=float,
        )
        b = np.array(
            [
                -54.4760987982241,
                161.585836858041,
                -155.698979859887,
                66.8013118877197,
                -13.2806815528857,
            ],
            dtype=float,
        )
        c = np.array(
            [
                -0.00778489400243029,
                -0.322396458041136,
                -2.40075827716184,
                -2.54973253934373,
                4.37466414146497,
                2.93816398269878,
            ],
            dtype=float,
        )
        d = np.array(
            [
                0.00778469570904146,
                0.32246712907004,
                2.445134137143,
                3.75440866190742,
            ],
            dtype=float,
        )

        p_low = 0.02425
        p_high = 1.0 - p_low
        mask_low = p < p_low
        mask_high = p > p_high
        mask_mid = ~(mask_low | mask_high)

        if np.any(mask_low):
            q = np.sqrt(-2.0 * np.log(p[mask_low]))
            x[mask_low] = (
                ((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]
            ) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)

        if np.any(mask_high):
            q = np.sqrt(-2.0 * np.log(1.0 - p[mask_high]))
            x[mask_high] = -(
                (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
                / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
            )

        if np.any(mask_mid):
            q = p[mask_mid] - 0.5
            r = q * q
            x[mask_mid] = (
                (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
                * q
            ) / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)

        return x

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
