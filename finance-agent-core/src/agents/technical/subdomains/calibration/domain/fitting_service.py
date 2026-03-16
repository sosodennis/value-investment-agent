from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from statistics import mean

from .contracts import (
    TechnicalDirectionCalibrationFitReport,
    TechnicalDirectionCalibrationFitResult,
    TechnicalDirectionCalibrationObservation,
)
from .policies.technical_direction_calibration_service import (
    DEFAULT_TECHNICAL_DIRECTION_CALIBRATION_CONFIG,
    TechnicalDirectionCalibrationConfig,
)

_EPSILON = 1e-9


def fit_technical_direction_calibration_config(
    observations: Iterable[TechnicalDirectionCalibrationObservation],
    *,
    mapping_version: str,
    min_samples: int = 120,
    fit_timeframe_multipliers: bool = False,
    fit_direction_multipliers: bool = False,
) -> TechnicalDirectionCalibrationFitResult:
    input_items = list(observations)
    usable = _extract_usable(input_items)
    dropped_count = len(input_items) - len(usable)
    if len(usable) < max(min_samples, 1):
        return _build_fallback_result(
            mapping_version=mapping_version,
            input_count=len(input_items),
            usable_count=len(usable),
            dropped_count=dropped_count,
            min_samples=min_samples,
            fallback_reason="insufficient_samples",
        )

    base_bins = DEFAULT_TECHNICAL_DIRECTION_CALIBRATION_CONFIG.mapping_bins
    mapping_bins, sample_counts = _fit_mapping_bins(usable, base_bins=base_bins)

    timeframe_multiplier = dict(
        DEFAULT_TECHNICAL_DIRECTION_CALIBRATION_CONFIG.timeframe_multiplier
    )
    direction_multiplier = dict(
        DEFAULT_TECHNICAL_DIRECTION_CALIBRATION_CONFIG.direction_multiplier
    )

    if fit_timeframe_multipliers:
        timeframe_multiplier = _fit_group_multiplier(
            usable,
            group_key="timeframe",
            baseline_keys=timeframe_multiplier,
        )
    if fit_direction_multipliers:
        direction_multiplier = _fit_group_multiplier(
            usable,
            group_key="direction",
            baseline_keys=direction_multiplier,
        )

    config = TechnicalDirectionCalibrationConfig(
        mapping_version=mapping_version,
        timeframe_multiplier=timeframe_multiplier,
        direction_multiplier=direction_multiplier,
        mapping_bins=mapping_bins,
    )
    report = TechnicalDirectionCalibrationFitReport(
        input_count=len(input_items),
        usable_count=len(usable),
        dropped_count=dropped_count,
        min_samples_required=min_samples,
        used_fallback=False,
        fallback_reason=None,
        mapping_bins_sample_count=sample_counts,
    )
    return TechnicalDirectionCalibrationFitResult(config=config, report=report)


def _build_fallback_result(
    *,
    mapping_version: str,
    input_count: int,
    usable_count: int,
    dropped_count: int,
    min_samples: int,
    fallback_reason: str,
) -> TechnicalDirectionCalibrationFitResult:
    fallback = DEFAULT_TECHNICAL_DIRECTION_CALIBRATION_CONFIG
    config = TechnicalDirectionCalibrationConfig(
        mapping_version=mapping_version,
        timeframe_multiplier=dict(fallback.timeframe_multiplier),
        direction_multiplier=dict(fallback.direction_multiplier),
        mapping_bins=tuple(fallback.mapping_bins),
    )
    report = TechnicalDirectionCalibrationFitReport(
        input_count=input_count,
        usable_count=usable_count,
        dropped_count=dropped_count,
        min_samples_required=min_samples,
        used_fallback=True,
        fallback_reason=fallback_reason,
        mapping_bins_sample_count={},
    )
    return TechnicalDirectionCalibrationFitResult(config=config, report=report)


def _extract_usable(
    observations: list[TechnicalDirectionCalibrationObservation],
) -> list[TechnicalDirectionCalibrationObservation]:
    usable: list[TechnicalDirectionCalibrationObservation] = []
    for item in observations:
        if _direction_sign(item.direction) == 0:
            continue
        if _outcome_sign(item.target_outcome) == 0:
            continue
        if abs(item.raw_score) <= _EPSILON:
            continue
        if item.raw_score != item.raw_score:
            continue
        usable.append(item)
    return usable


def _fit_mapping_bins(
    observations: list[TechnicalDirectionCalibrationObservation],
    *,
    base_bins: tuple[tuple[float, float], ...],
) -> tuple[tuple[tuple[float, float], ...], dict[float, int]]:
    upper_bounds = tuple(upper for upper, _ in base_bins)
    base_confidence = tuple(conf for _, conf in base_bins)
    hit_lookup = {index: _hit_value(item) for index, item in enumerate(observations)}

    cumulative_confidence: list[float] = []
    sample_count: dict[float, int] = {}
    for idx, upper in enumerate(upper_bounds):
        candidate_hits = [
            hit_lookup[index]
            for index, item in enumerate(observations)
            if abs(item.raw_score) <= upper
        ]
        sample_count[upper] = len(candidate_hits)
        if candidate_hits:
            cumulative_confidence.append(_bounded_confidence(mean(candidate_hits)))
            continue
        if cumulative_confidence:
            cumulative_confidence.append(cumulative_confidence[-1])
            continue
        cumulative_confidence.append(base_confidence[idx])

    fitted = _monotonic_confidence(cumulative_confidence)
    mapping_bins = tuple(
        (upper, conf) for upper, conf in zip(upper_bounds, fitted, strict=True)
    )
    return mapping_bins, sample_count


def _monotonic_confidence(values: list[float]) -> tuple[float, ...]:
    output: list[float] = []
    last = 0.0
    for value in values:
        bounded = _bounded_confidence(value)
        if bounded < last:
            bounded = last
        output.append(round(bounded, 6))
        last = bounded
    return tuple(output)


def _fit_group_multiplier(
    observations: list[TechnicalDirectionCalibrationObservation],
    *,
    group_key: str,
    baseline_keys: dict[str, float],
) -> dict[str, float]:
    if not observations:
        return dict(baseline_keys)

    global_rate = mean(_hit_value(item) for item in observations)
    if global_rate <= _EPSILON:
        return dict(baseline_keys)

    grouped: dict[str, list[int]] = defaultdict(list)
    for item in observations:
        key = item.timeframe if group_key == "timeframe" else item.direction
        grouped[key].append(_hit_value(item))

    output = dict(baseline_keys)
    for key, baseline in baseline_keys.items():
        group_hits = grouped.get(key)
        if not group_hits or len(group_hits) < 20:
            output[key] = baseline
            continue
        group_rate = mean(group_hits)
        ratio = group_rate / global_rate if global_rate > _EPSILON else 1.0
        output[key] = round(min(max(ratio, 0.7), 1.3), 6)
    return output


def _hit_value(item: TechnicalDirectionCalibrationObservation) -> int:
    predicted = _direction_sign(item.direction)
    actual = _outcome_sign(item.target_outcome)
    return int(predicted == actual)


def _direction_sign(direction: str) -> int:
    if not isinstance(direction, str):
        return 0
    normalized = direction.strip().lower()
    if normalized == "bullish":
        return 1
    if normalized == "bearish":
        return -1
    return 0


def _outcome_sign(outcome: float) -> int:
    if outcome > 0:
        return 1
    if outcome < 0:
        return -1
    return 0


def _bounded_confidence(value: float) -> float:
    if value != value:
        return 0.5
    return float(min(max(value, 0.5), 0.95))
