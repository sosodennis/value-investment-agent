from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from statistics import median

from ..policies.forward_signal_calibration_service import (
    DEFAULT_FORWARD_SIGNAL_CALIBRATION_CONFIG,
    ForwardSignalCalibrationConfig,
)
from .contracts import (
    ForwardSignalCalibrationFitReport,
    ForwardSignalCalibrationFitResult,
    ForwardSignalCalibrationObservation,
)

_EPSILON = 1e-9


def fit_forward_signal_calibration_config(
    observations: Iterable[ForwardSignalCalibrationObservation],
    *,
    mapping_version: str,
    min_samples: int = 120,
    fit_source_multipliers: bool = False,
    fit_metric_multipliers: bool = False,
) -> ForwardSignalCalibrationFitResult:
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

    base_bins = DEFAULT_FORWARD_SIGNAL_CALIBRATION_CONFIG.mapping_bins
    mapping_bins, sample_counts = _fit_mapping_bins(usable, base_bins=base_bins)

    source_multiplier = dict(
        DEFAULT_FORWARD_SIGNAL_CALIBRATION_CONFIG.source_multiplier
    )
    metric_multiplier = dict(
        DEFAULT_FORWARD_SIGNAL_CALIBRATION_CONFIG.metric_multiplier
    )
    if fit_source_multipliers:
        source_multiplier = _fit_group_multiplier(
            usable,
            group_key="source_type",
            baseline_keys=source_multiplier,
        )
    if fit_metric_multipliers:
        metric_multiplier = _fit_group_multiplier(
            usable,
            group_key="metric",
            baseline_keys=metric_multiplier,
        )

    config = ForwardSignalCalibrationConfig(
        mapping_version=mapping_version,
        source_multiplier=source_multiplier,
        metric_multiplier=metric_multiplier,
        mapping_bins=mapping_bins,
    )
    report = ForwardSignalCalibrationFitReport(
        input_count=len(input_items),
        usable_count=len(usable),
        dropped_count=dropped_count,
        min_samples_required=min_samples,
        used_fallback=False,
        fallback_reason=None,
        mapping_bins_sample_count=sample_counts,
    )
    return ForwardSignalCalibrationFitResult(config=config, report=report)


def _build_fallback_result(
    *,
    mapping_version: str,
    input_count: int,
    usable_count: int,
    dropped_count: int,
    min_samples: int,
    fallback_reason: str,
) -> ForwardSignalCalibrationFitResult:
    fallback = DEFAULT_FORWARD_SIGNAL_CALIBRATION_CONFIG
    config = ForwardSignalCalibrationConfig(
        mapping_version=mapping_version,
        source_multiplier=dict(fallback.source_multiplier),
        metric_multiplier=dict(fallback.metric_multiplier),
        mapping_bins=tuple(fallback.mapping_bins),
    )
    report = ForwardSignalCalibrationFitReport(
        input_count=input_count,
        usable_count=usable_count,
        dropped_count=dropped_count,
        min_samples_required=min_samples,
        used_fallback=True,
        fallback_reason=fallback_reason,
        mapping_bins_sample_count={},
    )
    return ForwardSignalCalibrationFitResult(config=config, report=report)


def _extract_usable(
    observations: list[ForwardSignalCalibrationObservation],
) -> list[ForwardSignalCalibrationObservation]:
    usable: list[ForwardSignalCalibrationObservation] = []
    for item in observations:
        raw_abs = abs(item.raw_basis_points)
        target_abs = abs(item.target_basis_points)
        if raw_abs <= _EPSILON:
            continue
        if target_abs != target_abs:
            continue
        usable.append(item)
    return usable


def _fit_mapping_bins(
    observations: list[ForwardSignalCalibrationObservation],
    *,
    base_bins: tuple[tuple[float, float], ...],
) -> tuple[tuple[tuple[float, float], ...], dict[float, int]]:
    upper_bounds = tuple(upper for upper, _ in base_bins)
    base_slopes = tuple(slope for _, slope in base_bins)
    ratio_by_observation = {
        index: _bounded_ratio(item) for index, item in enumerate(observations)
    }

    cumulative_ratio_targets: list[float] = []
    sample_count: dict[float, int] = {}
    for upper in upper_bounds:
        candidate_ratios = [
            ratio_by_observation[index]
            for index, item in enumerate(observations)
            if abs(item.raw_basis_points) <= upper
        ]
        sample_count[upper] = len(candidate_ratios)
        if candidate_ratios:
            cumulative_ratio_targets.append(float(median(candidate_ratios)))
            continue
        if cumulative_ratio_targets:
            cumulative_ratio_targets.append(cumulative_ratio_targets[-1])
            continue
        cumulative_ratio_targets.append(base_slopes[0])

    target_cumulative_mapped = [
        ratio * upper
        for ratio, upper in zip(cumulative_ratio_targets, upper_bounds, strict=True)
    ]
    fitted_slopes = _derive_slopes_from_cumulative_targets(
        upper_bounds=upper_bounds,
        cumulative_mapped=tuple(target_cumulative_mapped),
        base_slopes=base_slopes,
    )
    mapping_bins = tuple(
        (upper, slope) for upper, slope in zip(upper_bounds, fitted_slopes, strict=True)
    )
    return mapping_bins, sample_count


def _derive_slopes_from_cumulative_targets(
    *,
    upper_bounds: tuple[float, ...],
    cumulative_mapped: tuple[float, ...],
    base_slopes: tuple[float, ...],
) -> tuple[float, ...]:
    slopes: list[float] = []
    previous_upper = 0.0
    previous_mapped = 0.0
    for index, upper in enumerate(upper_bounds):
        width = upper - previous_upper
        if width <= 0.0:
            raw_slope = base_slopes[index]
        else:
            raw_slope = (cumulative_mapped[index] - previous_mapped) / width
        bounded = min(max(raw_slope, 0.05), 1.2)
        if index > 0 and bounded > slopes[-1]:
            bounded = slopes[-1]
        slopes.append(round(bounded, 6))
        previous_upper = upper
        previous_mapped = cumulative_mapped[index]
    return tuple(slopes)


def _fit_group_multiplier(
    observations: list[ForwardSignalCalibrationObservation],
    *,
    group_key: str,
    baseline_keys: dict[str, float],
) -> dict[str, float]:
    if not observations:
        return dict(baseline_keys)

    ratios = [_bounded_ratio(item) for item in observations]
    global_median_ratio = float(median(ratios))
    if global_median_ratio <= _EPSILON:
        return dict(baseline_keys)

    grouped: dict[str, list[float]] = defaultdict(list)
    for item in observations:
        key = item.source_type if group_key == "source_type" else item.metric
        grouped[key].append(_bounded_ratio(item))

    output = dict(baseline_keys)
    for key, baseline in baseline_keys.items():
        group_ratios = grouped.get(key)
        if not group_ratios or len(group_ratios) < 20:
            output[key] = baseline
            continue
        group_ratio = float(median(group_ratios))
        normalized = group_ratio / global_median_ratio
        output[key] = round(min(max(normalized, 0.5), 1.2), 6)
    return output


def _bounded_ratio(observation: ForwardSignalCalibrationObservation) -> float:
    raw_abs = abs(observation.raw_basis_points)
    if raw_abs <= _EPSILON:
        return 1.0
    ratio = abs(observation.target_basis_points) / raw_abs
    if ratio != ratio:
        return 1.0
    return float(min(max(ratio, 0.05), 1.2))
