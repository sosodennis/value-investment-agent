from __future__ import annotations

from dataclasses import dataclass

from .policies.technical_direction_calibration_service import (
    TechnicalDirectionCalibrationConfig,
)


@dataclass(frozen=True)
class TechnicalDirectionCalibrationObservation:
    timeframe: str
    horizon: str
    raw_score: float
    direction: str
    target_outcome: float


@dataclass(frozen=True)
class TechnicalDirectionCalibrationFitReport:
    input_count: int
    usable_count: int
    dropped_count: int
    min_samples_required: int
    used_fallback: bool
    fallback_reason: str | None
    mapping_bins_sample_count: dict[float, int]


@dataclass(frozen=True)
class TechnicalDirectionCalibrationFitResult:
    config: TechnicalDirectionCalibrationConfig
    report: TechnicalDirectionCalibrationFitReport
