from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from .contracts import TechnicalDirectionCalibrationObservation


@dataclass(frozen=True)
class TechnicalDirectionCalibrationObservationLoadResult:
    observations: list[TechnicalDirectionCalibrationObservation]
    dropped_rows: int


def load_technical_direction_calibration_observations(
    path: Path,
) -> TechnicalDirectionCalibrationObservationLoadResult:
    raw = path.read_text(encoding="utf-8")
    stripped = raw.strip()
    if not stripped:
        return TechnicalDirectionCalibrationObservationLoadResult(
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

    observations: list[TechnicalDirectionCalibrationObservation] = []
    dropped = 0
    for row in rows:
        item = _coerce_observation(row)
        if item is None:
            dropped += 1
            continue
        observations.append(item)
    return TechnicalDirectionCalibrationObservationLoadResult(
        observations=observations,
        dropped_rows=dropped,
    )


def write_technical_direction_calibration_artifact(
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
) -> TechnicalDirectionCalibrationObservation | None:
    timeframe_raw = row.get("timeframe")
    horizon_raw = row.get("horizon")
    direction_raw = row.get("direction")
    raw_score = _coerce_float(row.get("raw_score"))
    target_outcome = _coerce_float(row.get("target_outcome"))

    if not isinstance(timeframe_raw, str) or not timeframe_raw:
        return None
    if not isinstance(horizon_raw, str) or not horizon_raw:
        return None
    if not isinstance(direction_raw, str) or not direction_raw:
        return None
    if raw_score is None or target_outcome is None:
        return None

    return TechnicalDirectionCalibrationObservation(
        timeframe=timeframe_raw,
        horizon=horizon_raw,
        raw_score=raw_score,
        direction=direction_raw,
        target_outcome=target_outcome,
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
