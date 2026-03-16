from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

DEFAULT_TECHNICAL_DIRECTION_CALIBRATION_MAPPING_VERSION = (
    "technical_direction_calibration_v1_2026_03_16"
)
TECHNICAL_DIRECTION_CALIBRATION_METHOD = "piecewise_v1"

_SUPPORTED_DIRECTIONS = {"bullish", "bearish"}

_DEFAULT_TIMEFRAME_MULTIPLIER: dict[str, float] = {
    "1d": 1.0,
    "1wk": 0.92,
    "1h": 0.85,
}

_DEFAULT_DIRECTION_MULTIPLIER: dict[str, float] = {
    "bullish": 1.0,
    "bearish": 1.0,
}

_DEFAULT_MAPPING_BINS: tuple[tuple[float, float], ...] = (
    (0.5, 0.55),
    (1.0, 0.60),
    (1.5, 0.65),
    (2.0, 0.70),
    (3.0, 0.78),
)


@dataclass(frozen=True)
class TechnicalDirectionCalibrationConfig:
    mapping_version: str
    timeframe_multiplier: dict[str, float]
    direction_multiplier: dict[str, float]
    mapping_bins: tuple[tuple[float, float], ...]


DEFAULT_TECHNICAL_DIRECTION_CALIBRATION_CONFIG = TechnicalDirectionCalibrationConfig(
    mapping_version=DEFAULT_TECHNICAL_DIRECTION_CALIBRATION_MAPPING_VERSION,
    timeframe_multiplier=dict(_DEFAULT_TIMEFRAME_MULTIPLIER),
    direction_multiplier=dict(_DEFAULT_DIRECTION_MULTIPLIER),
    mapping_bins=_DEFAULT_MAPPING_BINS,
)


def calibrate_direction_confidence(
    *,
    raw_score: float,
    timeframe: str,
    direction: str,
    calibration_config: TechnicalDirectionCalibrationConfig | None = None,
) -> tuple[float, bool, str]:
    config = calibration_config or DEFAULT_TECHNICAL_DIRECTION_CALIBRATION_CONFIG
    normalized_direction = _normalize_direction(direction)
    if normalized_direction is None:
        return 0.5, False, config.mapping_version

    raw_abs = abs(raw_score)
    if raw_abs <= 1e-9:
        return 0.5, True, config.mapping_version

    base_confidence = _piecewise_map_abs(
        raw_abs,
        mapping_bins=config.mapping_bins,
    )
    timeframe_multiplier = config.timeframe_multiplier.get(timeframe, 1.0)
    direction_multiplier = config.direction_multiplier.get(normalized_direction, 1.0)

    calibrated = base_confidence * timeframe_multiplier * direction_multiplier
    calibrated = min(max(calibrated, 0.5), 0.95)
    return calibrated, True, config.mapping_version


def parse_technical_direction_calibration_config(
    payload: Mapping[str, object],
) -> TechnicalDirectionCalibrationConfig:
    version_raw = payload.get("mapping_version")
    if not isinstance(version_raw, str) or not version_raw:
        raise ValueError("mapping_version must be a non-empty string")

    timeframe_multiplier = _coerce_multiplier_mapping(
        payload.get("timeframe_multiplier"),
        context="timeframe_multiplier",
    )
    direction_multiplier = _coerce_multiplier_mapping(
        payload.get("direction_multiplier"),
        context="direction_multiplier",
    )
    mapping_bins = _coerce_mapping_bins(payload.get("mapping_bins"))

    return TechnicalDirectionCalibrationConfig(
        mapping_version=version_raw,
        timeframe_multiplier=timeframe_multiplier,
        direction_multiplier=direction_multiplier,
        mapping_bins=mapping_bins,
    )


def _normalize_direction(direction: str) -> str | None:
    if not isinstance(direction, str):
        return None
    normalized = direction.strip().lower()
    if normalized in _SUPPORTED_DIRECTIONS:
        return normalized
    return None


def _piecewise_map_abs(
    raw_abs: float,
    *,
    mapping_bins: tuple[tuple[float, float], ...],
) -> float:
    previous_upper = 0.0
    previous_value = mapping_bins[0][1]
    for upper, confidence in mapping_bins:
        if raw_abs <= upper:
            if upper <= previous_upper:
                return confidence
            ratio = (raw_abs - previous_upper) / (upper - previous_upper)
            return previous_value + ratio * (confidence - previous_value)
        previous_upper = upper
        previous_value = confidence
    return mapping_bins[-1][1]


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
    last_confidence = 0.0
    for index, item in enumerate(raw):
        if not isinstance(item, list | tuple) or len(item) != 2:
            raise ValueError(f"mapping_bins[{index}] must be [upper, confidence]")
        upper_raw, conf_raw = item
        if not isinstance(upper_raw, int | float) or isinstance(upper_raw, bool):
            raise ValueError(f"mapping_bins[{index}][0] must be numeric")
        if not isinstance(conf_raw, int | float) or isinstance(conf_raw, bool):
            raise ValueError(f"mapping_bins[{index}][1] must be numeric")
        upper = float(upper_raw)
        confidence = float(conf_raw)
        if upper <= last_upper:
            raise ValueError("mapping_bins upper bounds must be strictly increasing")
        if not 0.0 < confidence <= 1.0:
            raise ValueError("mapping_bins confidence must be within (0, 1]")
        if confidence < last_confidence:
            raise ValueError("mapping_bins confidence must be non-decreasing")
        bins.append((upper, confidence))
        last_upper = upper
        last_confidence = confidence
    if not bins:
        raise ValueError("mapping_bins must not be empty")
    return tuple(bins)
