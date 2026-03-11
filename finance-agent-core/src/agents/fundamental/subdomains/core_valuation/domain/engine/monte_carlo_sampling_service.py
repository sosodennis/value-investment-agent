from __future__ import annotations

from collections.abc import Mapping
from math import ceil, erf, log2, sqrt
from typing import Literal

import numpy as np

from .monte_carlo_contracts import CorrelationGroup, DistributionSpec, MonteCarloConfig
from .monte_carlo_diagnostics_service import build_correlation_diagnostics
from .monte_carlo_psd_service import ensure_correlation_psd

try:
    from scipy.stats import qmc as scipy_qmc
except Exception:  # pragma: no cover - optional runtime dependency guard
    scipy_qmc = None


def sample_variables(
    *,
    rng: np.random.Generator,
    distributions: Mapping[str, DistributionSpec],
    correlation_groups: tuple[CorrelationGroup, ...],
    iterations: int,
    config: MonteCarloConfig,
) -> tuple[dict[str, np.ndarray], dict[str, float | bool | int | str]]:
    _validate_correlation_group_variables(correlation_groups)
    sampled: dict[str, np.ndarray] = {}
    sampler_requested = config.sampler_type
    sampler_effective, sampler_fallback_reason = _resolve_sampler_type(
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
        group_samples, group_diag = _sample_correlation_group(
            rng=rng,
            group=group,
            distributions=distributions,
            sampler_type=sampler_effective,
            iterations=iterations,
            config=config,
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
        (name, spec) for name, spec in distributions.items() if name not in grouped_vars
    ]
    if ungrouped_items:
        unit_cube = _sample_unit_cube(
            rng=rng,
            iterations=iterations,
            dimensions=len(ungrouped_items),
            sampler_type=sampler_effective,
            config=config,
        )
        for idx, (name, spec) in enumerate(ungrouped_items):
            sampled[name] = _transform_unit_samples(unit_cube[:, idx], spec)

    return sampled, diagnostics


def _sample_correlation_group(
    *,
    rng: np.random.Generator,
    group: CorrelationGroup,
    distributions: Mapping[str, DistributionSpec],
    sampler_type: Literal["pseudo", "sobol", "lhs"],
    iterations: int,
    config: MonteCarloConfig,
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
        _validate_distribution_spec(spec)
        specs.append(spec)

    corr = np.array(group.matrix, dtype=float)
    if not np.allclose(corr, corr.T):
        raise ValueError("correlation matrix must be symmetric")
    if not np.allclose(np.diag(corr), 1.0):
        raise ValueError("correlation matrix diagonal must be 1")

    corr_psd, psd_diag = ensure_correlation_psd(corr, config=config)

    unit_cube = _sample_unit_cube(
        rng=rng,
        iterations=iterations,
        dimensions=size,
        sampler_type=sampler_type,
        config=config,
    )
    independent_normals = _normal_ppf(unit_cube)
    chol = np.linalg.cholesky(corr_psd)
    draws = independent_normals @ chol.T
    output: dict[str, np.ndarray] = {}
    for idx, var in enumerate(group.variables):
        output[var] = _transform_standard_normal(draws[:, idx], specs[idx])
    corr_diag = build_correlation_diagnostics(
        variables=group.variables,
        target_corr=corr_psd,
        latent_draws=draws,
        transformed_samples=output,
    )
    return output, {**psd_diag, **corr_diag}


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
            "correlated variables cannot appear in multiple groups: " f"{repeated_list}"
        )


def _resolve_sampler_type(
    requested: Literal["pseudo", "sobol", "lhs"],
) -> tuple[Literal["pseudo", "sobol", "lhs"], str | None]:
    if requested == "sobol" and scipy_qmc is None:
        return "pseudo", "sobol sampler unavailable (scipy missing)"
    return requested, None


def _sample_unit_cube(
    *,
    rng: np.random.Generator,
    iterations: int,
    dimensions: int,
    sampler_type: Literal["pseudo", "sobol", "lhs"],
    config: MonteCarloConfig,
) -> np.ndarray:
    if dimensions <= 0:
        raise ValueError("dimensions must be positive")
    if iterations <= 0:
        raise ValueError("iterations must be positive")

    if sampler_type == "pseudo":
        return rng.random((iterations, dimensions))
    if sampler_type == "lhs":
        return _sample_lhs(rng=rng, iterations=iterations, dimensions=dimensions)
    return _sample_sobol(
        rng=rng,
        iterations=iterations,
        dimensions=dimensions,
        config=config,
    )


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
    *,
    rng: np.random.Generator,
    iterations: int,
    dimensions: int,
    config: MonteCarloConfig,
) -> np.ndarray:
    if scipy_qmc is None:
        # Guarded by _resolve_sampler_type, but keep safe fallback.
        return rng.random((iterations, dimensions))

    seed_value = int(rng.integers(0, np.iinfo(np.uint32).max))
    sobol_engine = scipy_qmc.Sobol(
        d=dimensions,
        scramble=config.sobol_scramble,
        seed=seed_value,
    )
    m = int(ceil(log2(max(1, iterations))))
    sampled = sobol_engine.random_base2(m)
    if sampled.shape[0] < iterations:
        extra = sobol_engine.random(iterations - sampled.shape[0])
        sampled = np.vstack([sampled, extra])
    return sampled[:iterations]


def _transform_unit_samples(u: np.ndarray, spec: DistributionSpec) -> np.ndarray:
    _validate_distribution_spec(spec)
    clipped_u = np.clip(u, 1e-12, 1.0 - 1e-12)
    if spec.kind == "normal":
        z = _normal_ppf(clipped_u)
        values = spec.mean + (spec.std * z)
    elif spec.kind == "uniform":
        values = spec.low + ((spec.high - spec.low) * clipped_u)
    else:
        values = _inverse_triangular_cdf(
            clipped_u,
            left=spec.left,
            mode=spec.mode,
            right=spec.right,
        )
    return _clip_bounds(values, spec.min_bound, spec.max_bound)


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


def _transform_standard_normal(
    z: np.ndarray,
    spec: DistributionSpec,
) -> np.ndarray:
    if spec.kind == "normal":
        values = spec.mean + (spec.std * z)
    else:
        u = _normal_cdf(z)
        if spec.kind == "uniform":
            values = spec.low + ((spec.high - spec.low) * u)
        else:
            values = _inverse_triangular_cdf(
                u,
                left=spec.left,
                mode=spec.mode,
                right=spec.right,
            )
    return _clip_bounds(values, spec.min_bound, spec.max_bound)


def _normal_cdf(z: np.ndarray) -> np.ndarray:
    u = np.array(
        [0.5 * (1.0 + erf(float(value) / sqrt(2.0))) for value in z], dtype=float
    )
    return np.clip(u, 1e-12, 1.0 - 1e-12)


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
            (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q
        ) / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)

    return x


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
