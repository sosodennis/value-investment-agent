from __future__ import annotations

from dataclasses import dataclass

from ..policies.forward_signal_calibration_service import ForwardSignalCalibrationConfig


@dataclass(frozen=True)
class ForwardSignalCalibrationObservation:
    metric: str
    source_type: str
    raw_basis_points: float
    target_basis_points: float


@dataclass(frozen=True)
class ForwardSignalCalibrationFitReport:
    input_count: int
    usable_count: int
    dropped_count: int
    min_samples_required: int
    used_fallback: bool
    fallback_reason: str | None
    mapping_bins_sample_count: dict[float, int]


@dataclass(frozen=True)
class ForwardSignalCalibrationFitResult:
    config: ForwardSignalCalibrationConfig
    report: ForwardSignalCalibrationFitReport
