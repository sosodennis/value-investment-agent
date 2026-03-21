from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from math import isnan

from src.agents.technical.subdomains.calibration.domain.contracts import (
    TechnicalDirectionCalibrationObservation,
)
from src.agents.technical.subdomains.calibration.domain.policies.technical_direction_calibration_service import (
    resolve_direction_family,
)

from .contracts import TechnicalMonitoringReadModelRow


@dataclass(frozen=True)
class TechnicalCalibrationObservationBuildResult:
    observations: tuple[TechnicalDirectionCalibrationObservation, ...]
    row_count: int
    usable_row_count: int
    dropped_row_count: int
    dropped_reasons: dict[str, int]


def build_technical_direction_calibration_observations(
    rows: Iterable[TechnicalMonitoringReadModelRow],
) -> TechnicalCalibrationObservationBuildResult:
    observations: list[TechnicalDirectionCalibrationObservation] = []
    dropped_reasons: dict[str, int] = defaultdict(int)
    row_count = 0

    for row in rows:
        row_count += 1

        if row.outcome_path_id is None:
            dropped_reasons["missing_outcome_path"] += 1
            continue

        direction_family = _normalize_direction_family(row.direction)
        if direction_family is None:
            dropped_reasons["unsupported_direction_family"] += 1
            continue

        raw_score = _coerce_numeric(row.raw_score)
        if raw_score is None:
            dropped_reasons["missing_raw_score"] += 1
            continue

        target_outcome = _coerce_numeric(row.forward_return)
        if target_outcome is None:
            dropped_reasons["missing_forward_return"] += 1
            continue

        observations.append(
            TechnicalDirectionCalibrationObservation(
                timeframe=row.timeframe,
                horizon=row.horizon,
                raw_score=raw_score,
                direction=direction_family,
                target_outcome=target_outcome,
            )
        )

    return TechnicalCalibrationObservationBuildResult(
        observations=tuple(observations),
        row_count=row_count,
        usable_row_count=len(observations),
        dropped_row_count=row_count - len(observations),
        dropped_reasons=dict(dropped_reasons),
    )


def _normalize_direction_family(direction: str) -> str | None:
    family = resolve_direction_family(direction)
    if family in {"bullish", "bearish"}:
        return family

    normalized = direction.strip().lower()
    if normalized.startswith("bullish_"):
        return "bullish"
    if normalized.startswith("bearish_"):
        return "bearish"
    return None


def _coerce_numeric(value: float | None) -> float | None:
    if value is None or isnan(value):
        return None
    return float(value)
