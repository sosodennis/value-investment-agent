from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


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
