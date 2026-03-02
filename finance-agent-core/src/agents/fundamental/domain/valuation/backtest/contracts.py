from __future__ import annotations

from dataclasses import dataclass

from src.shared.kernel.types import JSONObject


@dataclass(frozen=True)
class BacktestConfig:
    abs_tol: float = 1e-6
    rel_tol: float = 1e-4


@dataclass(frozen=True)
class BacktestCase:
    case_id: str
    model: str
    params: JSONObject
    required_metrics: tuple[str, ...]


@dataclass(frozen=True)
class MetricDrift:
    case_id: str
    metric_path: str
    baseline: float
    current: float
    abs_diff: float
    rel_diff: float


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    model: str
    status: str
    metrics: JSONObject | None = None
    error: str | None = None


@dataclass(frozen=True)
class BaselineCase:
    model: str
    metrics: JSONObject
