from __future__ import annotations

import math

import pandas as pd

from src.shared.kernel.types import JSONObject

from .contracts import (
    BollingerSnapshot,
    FracdiffSerializationResult,
    ObvSnapshot,
    StatisticalStrengthSnapshot,
)


def _series_to_json(series: pd.Series) -> dict[str, float | None]:
    return {
        (
            key.strftime("%Y-%m-%d") if isinstance(key, pd.Timestamp) else str(key)
        ): _finite_float(raw_value)
        for key, raw_value in series.to_dict().items()
    }


def serialize_fracdiff_outputs(
    *,
    fd_series: pd.Series,
    z_score_series: pd.Series,
    bollinger_data: JSONObject,
    stat_strength_data: JSONObject,
    obv_data: JSONObject,
) -> FracdiffSerializationResult:
    bollinger = BollingerSnapshot(
        upper=_finite_float(bollinger_data.get("upper")),
        middle=_finite_float(bollinger_data.get("middle")),
        lower=_finite_float(bollinger_data.get("lower")),
        state=str(bollinger_data.get("state") or "INSIDE"),
        bandwidth=_finite_float(bollinger_data.get("bandwidth")),
    )

    stat_strength = StatisticalStrengthSnapshot(
        value=_finite_float(stat_strength_data.get("value"))
    )

    obv = ObvSnapshot(
        raw_obv_val=_finite_float(obv_data.get("raw_obv_val")),
        fd_obv_z=_finite_float(obv_data.get("fd_obv_z")),
        optimal_d=_finite_float(obv_data.get("optimal_d")),
        state=str(obv_data.get("state") or "NEUTRAL"),
    )

    return FracdiffSerializationResult(
        bollinger=bollinger,
        stat_strength=stat_strength,
        obv=obv,
        fracdiff_series=_series_to_json(fd_series),
        z_score_series=_series_to_json(z_score_series),
    )


def _finite_float(value: object) -> float | None:
    try:
        numeric_value = float(value)
    except (ValueError, TypeError):
        return None

    if math.isnan(numeric_value) or math.isinf(numeric_value):
        return None
    return numeric_value
