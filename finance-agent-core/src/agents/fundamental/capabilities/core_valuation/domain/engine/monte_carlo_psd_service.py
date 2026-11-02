from __future__ import annotations

import numpy as np

from .monte_carlo_contracts import MonteCarloConfig


def ensure_correlation_psd(
    corr: np.ndarray,
    *,
    config: MonteCarloConfig,
) -> tuple[np.ndarray, dict[str, float | bool | int]]:
    sym = _symmetrize(corr)
    min_before = float(np.min(np.linalg.eigvalsh(sym)))
    diagnostics: dict[str, float | bool | int] = {
        "psd_repaired": False,
        "psd_repair_failed": False,
        "psd_repair_clip_used": False,
        "psd_repair_higham_used": False,
        "psd_min_eigen_before": min_before,
        "psd_min_eigen_after": min_before,
    }
    if min_before >= config.psd_tolerance:
        return sym, diagnostics

    if config.psd_repair_policy == "error":
        diagnostics["psd_repair_failed"] = True
        raise ValueError(
            f"covariance matrix is not PSD; minimum eigenvalue={min_before:.6g}"
        )

    diagnostics["psd_repaired"] = True
    if config.psd_repair_policy == "higham":
        repaired = _nearest_correlation_higham(sym, config=config)
        diagnostics["psd_repair_higham_used"] = True
    else:
        repaired = _nearest_correlation_clip(sym, config=config)
        diagnostics["psd_repair_clip_used"] = True

    min_after = float(np.min(np.linalg.eigvalsh(repaired)))
    diagnostics["psd_min_eigen_after"] = min_after
    if min_after < config.psd_tolerance:
        diagnostics["psd_repair_failed"] = True
        raise ValueError(
            "unable to repair covariance matrix to PSD; "
            f"minimum eigenvalue after repair={min_after:.6g}"
        )
    return repaired, diagnostics


def _symmetrize(matrix: np.ndarray) -> np.ndarray:
    return (matrix + matrix.T) / 2.0


def _project_psd(matrix: np.ndarray, *, config: MonteCarloConfig) -> np.ndarray:
    eigvals, eigvecs = np.linalg.eigh(_symmetrize(matrix))
    eigvals = np.maximum(eigvals, config.psd_eigen_floor)
    projected = (eigvecs * eigvals) @ eigvecs.T
    return _symmetrize(projected)


def _project_unit_diagonal(matrix: np.ndarray) -> np.ndarray:
    projected = matrix.copy()
    np.fill_diagonal(projected, 1.0)
    return projected


def _normalize_to_correlation(matrix: np.ndarray) -> np.ndarray:
    diag = np.diag(matrix)
    safe_diag = np.where(diag > 0, diag, 1.0)
    scale = np.sqrt(safe_diag)
    normalized = matrix / np.outer(scale, scale)
    normalized = _symmetrize(normalized)
    return _project_unit_diagonal(normalized)


def _nearest_correlation_clip(
    corr: np.ndarray, *, config: MonteCarloConfig
) -> np.ndarray:
    clipped = _project_psd(corr, config=config)
    normalized = _normalize_to_correlation(clipped)
    # A second PSD projection mitigates tiny numerical negatives after normalize.
    repaired = _project_psd(normalized, config=config)
    return _normalize_to_correlation(repaired)


def _nearest_correlation_higham(
    corr: np.ndarray,
    *,
    config: MonteCarloConfig,
) -> np.ndarray:
    # Higham nearest correlation via alternating projections with Dykstra correction.
    y = _symmetrize(corr)
    delta_s = np.zeros_like(y)

    for _ in range(config.higham_max_iterations):
        y_prev = y
        r = y - delta_s
        x = _project_psd(r, config=config)
        delta_s = x - r
        y = _project_unit_diagonal(x)
        y = _symmetrize(y)
        diff = np.linalg.norm(y - y_prev, ord="fro")
        denom = max(np.linalg.norm(y, ord="fro"), 1.0)
        if (diff / denom) <= config.higham_tolerance:
            break

    repaired = _project_psd(y, config=config)
    return _normalize_to_correlation(repaired)
