from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from src.shared.kernel.types import JSONObject

from .contracts import ForwardSignalCalibrationObservation

DEFAULT_FORWARD_SIGNAL_CALIBRATION_GAIN = 0.5
DEFAULT_FORWARD_SIGNAL_ADJUSTMENT_CAP_BASIS_POINTS = 300.0


@dataclass(frozen=True)
class ForwardSignalCalibrationDatasetBuildResult:
    observations: list[ForwardSignalCalibrationObservation]
    row_count: int
    usable_row_count: int
    dropped_row_count: int
    dropped_reasons: dict[str, int]


def build_forward_signal_calibration_observations(
    *,
    replay_results: Sequence[Mapping[str, object]],
    anchor_target_price_by_ticker: Mapping[str, float],
    gain: float = DEFAULT_FORWARD_SIGNAL_CALIBRATION_GAIN,
    adjustment_cap_basis_points: float = (
        DEFAULT_FORWARD_SIGNAL_ADJUSTMENT_CAP_BASIS_POINTS
    ),
) -> ForwardSignalCalibrationDatasetBuildResult:
    observations: list[ForwardSignalCalibrationObservation] = []
    dropped_reasons: dict[str, int] = {}
    usable_rows = 0

    for row in replay_results:
        built = _build_row_observations(
            row=row,
            anchor_target_price_by_ticker=anchor_target_price_by_ticker,
            gain=gain,
            adjustment_cap_basis_points=adjustment_cap_basis_points,
        )
        if built is None:
            reason = _infer_drop_reason(row, anchor_target_price_by_ticker)
            dropped_reasons[reason] = dropped_reasons.get(reason, 0) + 1
            continue
        usable_rows += 1
        observations.extend(built)

    return ForwardSignalCalibrationDatasetBuildResult(
        observations=observations,
        row_count=len(replay_results),
        usable_row_count=usable_rows,
        dropped_row_count=len(replay_results) - usable_rows,
        dropped_reasons=dropped_reasons,
    )


def _build_row_observations(
    *,
    row: Mapping[str, object],
    anchor_target_price_by_ticker: Mapping[str, float],
    gain: float,
    adjustment_cap_basis_points: float,
) -> list[ForwardSignalCalibrationObservation] | None:
    ticker = _coerce_non_empty_string(row.get("ticker"))
    current_price = _coerce_float(row.get("current_price"))
    intrinsic_value = _coerce_float(row.get("intrinsic_value"))
    forward_signal_summary = row.get("forward_signal_summary")
    if ticker is None or current_price is None or intrinsic_value is None:
        return None
    if current_price <= 0.0:
        return None
    if not isinstance(forward_signal_summary, Mapping):
        return None
    anchor_target_price = anchor_target_price_by_ticker.get(ticker)
    if anchor_target_price is None or anchor_target_price <= 0.0:
        return None

    raw_growth_bp = _coerce_float(
        forward_signal_summary.get("raw_growth_adjustment_basis_points")
    )
    raw_margin_bp = _coerce_float(
        forward_signal_summary.get("raw_margin_adjustment_basis_points")
    )
    if raw_growth_bp is None:
        raw_growth_bp = _coerce_float(
            forward_signal_summary.get("growth_adjustment_basis_points")
        )
    if raw_margin_bp is None:
        raw_margin_bp = _coerce_float(
            forward_signal_summary.get("margin_adjustment_basis_points")
        )
    if raw_growth_bp is None or raw_margin_bp is None:
        return None

    source_types = _coerce_source_types(forward_signal_summary.get("source_types"))
    source_type = source_types[0] if source_types else "manual"

    model_upside_bp = ((intrinsic_value / current_price) - 1.0) * 10000.0
    anchor_upside_bp = ((anchor_target_price / current_price) - 1.0) * 10000.0
    error_bp = anchor_upside_bp - model_upside_bp

    raw_total_bp = raw_growth_bp + raw_margin_bp
    calibrated_total_bp = _clip(
        raw_total_bp + (gain * error_bp),
        -adjustment_cap_basis_points,
        adjustment_cap_basis_points,
    )
    delta_bp = calibrated_total_bp - raw_total_bp
    growth_weight, margin_weight = _metric_weights(raw_growth_bp, raw_margin_bp)
    target_growth_bp = _clip(
        raw_growth_bp + (delta_bp * growth_weight),
        -adjustment_cap_basis_points,
        adjustment_cap_basis_points,
    )
    target_margin_bp = _clip(
        raw_margin_bp + (delta_bp * margin_weight),
        -adjustment_cap_basis_points,
        adjustment_cap_basis_points,
    )

    return [
        ForwardSignalCalibrationObservation(
            metric="growth_outlook",
            source_type=source_type,
            raw_basis_points=raw_growth_bp,
            target_basis_points=target_growth_bp,
        ),
        ForwardSignalCalibrationObservation(
            metric="margin_outlook",
            source_type=source_type,
            raw_basis_points=raw_margin_bp,
            target_basis_points=target_margin_bp,
        ),
    ]


def _infer_drop_reason(
    row: Mapping[str, object],
    anchor_target_price_by_ticker: Mapping[str, float],
) -> str:
    ticker = _coerce_non_empty_string(row.get("ticker"))
    if ticker is None:
        return "missing_ticker"
    if ticker not in anchor_target_price_by_ticker:
        return "missing_anchor_target_price"
    current_price = _coerce_float(row.get("current_price"))
    if current_price is None or current_price <= 0.0:
        return "invalid_current_price"
    intrinsic_value = _coerce_float(row.get("intrinsic_value"))
    if intrinsic_value is None:
        return "missing_intrinsic_value"
    summary = row.get("forward_signal_summary")
    if not isinstance(summary, Mapping):
        return "missing_forward_signal_summary"
    return "missing_forward_signal_adjustments"


def _metric_weights(growth_bp: float, margin_bp: float) -> tuple[float, float]:
    growth_abs = abs(growth_bp)
    margin_abs = abs(margin_bp)
    total_abs = growth_abs + margin_abs
    if total_abs <= 1e-9:
        return 0.5, 0.5
    return growth_abs / total_abs, margin_abs / total_abs


def _coerce_source_types(raw: object) -> list[str]:
    if not isinstance(raw, Sequence) or isinstance(raw, str):
        return []
    output: list[str] = []
    for item in raw:
        if isinstance(item, str) and item:
            output.append(item)
    return output


def _clip(value: float, lower: float, upper: float) -> float:
    return min(max(value, lower), upper)


def _coerce_float(raw: object) -> float | None:
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, int | float):
        value = float(raw)
        if value != value:
            return None
        return value
    if isinstance(raw, str):
        normalized = raw.strip()
        if not normalized:
            return None
        try:
            value = float(normalized)
        except ValueError:
            return None
        if value != value:
            return None
        return value
    return None


def _coerce_non_empty_string(raw: object) -> str | None:
    if isinstance(raw, str) and raw:
        return raw
    return None


def serialize_observations(
    observations: Sequence[ForwardSignalCalibrationObservation],
) -> list[JSONObject]:
    output: list[JSONObject] = []
    for item in observations:
        output.append(
            {
                "metric": item.metric,
                "source_type": item.source_type,
                "raw_basis_points": item.raw_basis_points,
                "target_basis_points": item.target_basis_points,
            }
        )
    return output
