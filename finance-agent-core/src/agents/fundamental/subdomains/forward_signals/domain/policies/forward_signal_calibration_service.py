from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .forward_signal_contracts import ForwardSignal

DEFAULT_FORWARD_SIGNAL_CALIBRATION_MAPPING_VERSION = (
    "forward_signal_calibration_v1_2026_03_04"
)

_SUPPORTED_METRICS = {"growth_outlook", "margin_outlook"}

_DEFAULT_SOURCE_MULTIPLIER: dict[str, float] = {
    "mda": 1.0,
    "xbrl_auto": 0.85,
    "earnings_call": 0.95,
    "press_release": 0.9,
    "news": 0.85,
    "debate": 0.8,
    "manual": 1.0,
}

_DEFAULT_METRIC_MULTIPLIER: dict[str, float] = {
    "growth_outlook": 1.0,
    "margin_outlook": 0.9,
}

_DEFAULT_MAPPING_BINS: tuple[tuple[float, float], ...] = (
    (50.0, 1.0),
    (120.0, 0.80),
    (220.0, 0.55),
    (300.0, 0.40),
)


@dataclass(frozen=True)
class ForwardSignalCalibrationConfig:
    mapping_version: str
    source_multiplier: dict[str, float]
    metric_multiplier: dict[str, float]
    mapping_bins: tuple[tuple[float, float], ...]


DEFAULT_FORWARD_SIGNAL_CALIBRATION_CONFIG = ForwardSignalCalibrationConfig(
    mapping_version=DEFAULT_FORWARD_SIGNAL_CALIBRATION_MAPPING_VERSION,
    source_multiplier=dict(_DEFAULT_SOURCE_MULTIPLIER),
    metric_multiplier=dict(_DEFAULT_METRIC_MULTIPLIER),
    mapping_bins=_DEFAULT_MAPPING_BINS,
)


def calibrate_signal_basis_points(
    signal: ForwardSignal,
    *,
    raw_basis_points: float,
    calibration_config: ForwardSignalCalibrationConfig | None = None,
) -> tuple[float, bool, str]:
    config = calibration_config or DEFAULT_FORWARD_SIGNAL_CALIBRATION_CONFIG
    if signal.metric not in _SUPPORTED_METRICS:
        return raw_basis_points, False, config.mapping_version
    if abs(raw_basis_points) <= 1e-9:
        return raw_basis_points, True, config.mapping_version

    mapped_abs = _piecewise_map_abs(
        abs(raw_basis_points),
        mapping_bins=config.mapping_bins,
    )
    source_multiplier = config.source_multiplier.get(signal.source_type, 1.0)
    metric_multiplier = config.metric_multiplier.get(signal.metric, 1.0)
    calibrated_abs = mapped_abs * source_multiplier * metric_multiplier

    sign = -1.0 if raw_basis_points < 0 else 1.0
    return (
        sign * calibrated_abs,
        True,
        config.mapping_version,
    )


def _piecewise_map_abs(
    raw_abs: float,
    *,
    mapping_bins: tuple[tuple[float, float], ...],
) -> float:
    remaining = max(raw_abs, 0.0)
    mapped = 0.0
    previous_upper = 0.0
    for upper, slope in mapping_bins:
        if remaining <= 0.0:
            break
        segment_width = upper - previous_upper
        if segment_width <= 0.0:
            previous_upper = upper
            continue
        consumed = min(remaining, segment_width)
        mapped += consumed * slope
        remaining -= consumed
        previous_upper = upper
    if remaining > 0.0:
        mapped += remaining * mapping_bins[-1][1]
    return mapped


def parse_forward_signal_calibration_config(
    payload: Mapping[str, object],
) -> ForwardSignalCalibrationConfig:
    version_raw = payload.get("mapping_version")
    if not isinstance(version_raw, str) or not version_raw:
        raise ValueError("mapping_version must be a non-empty string")

    source_multiplier = _coerce_multiplier_mapping(
        payload.get("source_multiplier"),
        context="source_multiplier",
    )
    metric_multiplier = _coerce_multiplier_mapping(
        payload.get("metric_multiplier"),
        context="metric_multiplier",
    )
    mapping_bins = _coerce_mapping_bins(payload.get("mapping_bins"))

    return ForwardSignalCalibrationConfig(
        mapping_version=version_raw,
        source_multiplier=source_multiplier,
        metric_multiplier=metric_multiplier,
        mapping_bins=mapping_bins,
    )


def _coerce_multiplier_mapping(
    raw: object,
    *,
    context: str,
) -> dict[str, float]:
    if not isinstance(raw, Mapping):
        raise ValueError(f"{context} must be an object")
    output: dict[str, float] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not key:
            raise ValueError(f"{context} keys must be non-empty strings")
        if not isinstance(value, int | float) or isinstance(value, bool):
            raise ValueError(f"{context}.{key} must be numeric")
        output[key] = float(value)
    if not output:
        raise ValueError(f"{context} must not be empty")
    return output


def _coerce_mapping_bins(raw: object) -> tuple[tuple[float, float], ...]:
    if not isinstance(raw, list | tuple):
        raise ValueError("mapping_bins must be an array")
    bins: list[tuple[float, float]] = []
    last_upper = 0.0
    for index, item in enumerate(raw):
        if not isinstance(item, list | tuple) or len(item) != 2:
            raise ValueError(f"mapping_bins[{index}] must be [upper, slope]")
        upper_raw, slope_raw = item
        if not isinstance(upper_raw, int | float) or isinstance(upper_raw, bool):
            raise ValueError(f"mapping_bins[{index}][0] must be numeric")
        if not isinstance(slope_raw, int | float) or isinstance(slope_raw, bool):
            raise ValueError(f"mapping_bins[{index}][1] must be numeric")
        upper = float(upper_raw)
        slope = float(slope_raw)
        if upper <= last_upper:
            raise ValueError("mapping_bins upper bounds must be strictly increasing")
        if slope <= 0:
            raise ValueError("mapping_bins slope must be positive")
        bins.append((upper, slope))
        last_upper = upper
    if not bins:
        raise ValueError("mapping_bins must not be empty")
    return tuple(bins)
