from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from .monte_carlo_contracts import MonteCarloConfig


def build_summary(outcomes: np.ndarray) -> dict[str, float]:
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


def build_convergence_diagnostics(
    outcomes: np.ndarray,
    *,
    config: MonteCarloConfig,
) -> dict[str, float | bool | int]:
    sample_size = len(outcomes)
    configured_window = config.convergence_window
    effective_window = min(
        configured_window,
        max(config.dynamic_window_min, sample_size // 3),
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
            "tolerance": config.convergence_tolerance,
        }

    prev = outcomes[-(effective_window * 2) : -effective_window]
    curr = outcomes[-effective_window:]
    prev_median = float(np.median(prev))
    curr_median = float(np.median(curr))
    denominator = abs(prev_median) if abs(prev_median) > 1e-9 else 1.0
    delta = abs(curr_median - prev_median) / denominator
    return {
        "iterations": sample_size,
        "converged": delta <= config.convergence_tolerance,
        "sufficient_window": True,
        "window": configured_window,
        "effective_window": effective_window,
        "median_delta": float(delta),
        "tolerance": config.convergence_tolerance,
    }


def build_correlation_diagnostics(
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
    pearson_errors = np.abs(_upper_triangle(pearson_realized - target_corr, k=1))

    transformed_matrix = np.column_stack(
        [transformed_samples[var] for var in variables]
    )
    spearman_realized = _spearman_corrcoef(transformed_matrix)
    spearman_target = _gaussian_spearman_from_pearson(target_corr)
    spearman_errors = np.abs(_upper_triangle(spearman_realized - spearman_target, k=1))

    return {
        "corr_pairs_total": pair_count,
        "corr_pearson_mae": float(np.mean(pearson_errors)),
        "corr_pearson_max_abs_error": float(np.max(pearson_errors)),
        "corr_spearman_mae": float(np.mean(spearman_errors)),
        "corr_spearman_max_abs_error": float(np.max(spearman_errors)),
    }


def _upper_triangle(matrix: np.ndarray, *, k: int = 1) -> np.ndarray:
    row_idx, col_idx = np.triu_indices(matrix.shape[0], k=k)
    return matrix[row_idx, col_idx]


def _gaussian_spearman_from_pearson(pearson_corr: np.ndarray) -> np.ndarray:
    clipped = np.clip(pearson_corr / 2.0, -1.0, 1.0)
    spearman = (6.0 / np.pi) * np.arcsin(clipped)
    spearman = (spearman + spearman.T) / 2.0
    np.fill_diagonal(spearman, 1.0)
    return spearman


def _spearman_corrcoef(matrix: np.ndarray) -> np.ndarray:
    ranks = np.apply_along_axis(_rankdata, 0, matrix)
    return np.corrcoef(ranks, rowvar=False)


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
