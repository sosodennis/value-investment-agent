from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from .contracts import ForwardSignalCalibrationObservation


@dataclass(frozen=True)
class ForwardSignalCalibrationObservationLoadResult:
    observations: list[ForwardSignalCalibrationObservation]
    dropped_rows: int


def load_forward_signal_calibration_observations(
    path: Path,
) -> ForwardSignalCalibrationObservationLoadResult:
    raw = path.read_text(encoding="utf-8")
    stripped = raw.strip()
    if not stripped:
        return ForwardSignalCalibrationObservationLoadResult(
            observations=[],
            dropped_rows=0,
        )

    rows: list[dict[str, object]] = []
    if stripped.startswith("["):
        parsed = json.loads(stripped)
        if isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict):
                    rows.append(cast(dict[str, object], item))
    else:
        for line in stripped.splitlines():
            line_item = line.strip()
            if not line_item:
                continue
            parsed = json.loads(line_item)
            if isinstance(parsed, dict):
                rows.append(cast(dict[str, object], parsed))

    observations: list[ForwardSignalCalibrationObservation] = []
    dropped = 0
    for row in rows:
        item = _coerce_observation(row)
        if item is None:
            dropped += 1
            continue
        observations.append(item)
    return ForwardSignalCalibrationObservationLoadResult(
        observations=observations,
        dropped_rows=dropped,
    )


def write_forward_signal_calibration_artifact(
    *,
    output_path: Path,
    payload: dict[str, object],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _coerce_observation(
    row: dict[str, object],
) -> ForwardSignalCalibrationObservation | None:
    metric_raw = row.get("metric")
    source_type_raw = row.get("source_type")
    raw_basis_points = _coerce_float(row.get("raw_basis_points"))
    target_basis_points = _coerce_float(row.get("target_basis_points"))
    if not isinstance(metric_raw, str) or not metric_raw:
        return None
    if not isinstance(source_type_raw, str) or not source_type_raw:
        return None
    if raw_basis_points is None or target_basis_points is None:
        return None
    return ForwardSignalCalibrationObservation(
        metric=metric_raw,
        source_type=source_type_raw,
        raw_basis_points=raw_basis_points,
        target_basis_points=target_basis_points,
    )


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
