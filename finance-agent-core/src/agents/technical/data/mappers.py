from __future__ import annotations

import pandas as pd

from src.agents.technical.domain.models import (
    BollingerSnapshot,
    FracdiffSerializationResult,
    ObvSnapshot,
    StatisticalStrengthSnapshot,
)
from src.agents.technical.domain.services import safe_float
from src.shared.kernel.types import JSONObject


def _series_to_json(series: pd.Series) -> dict[str, float | None]:
    return {
        (
            key.strftime("%Y-%m-%d") if isinstance(key, pd.Timestamp) else str(key)
        ): safe_float(raw_value)
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
        upper=safe_float(bollinger_data.get("upper")),
        middle=safe_float(bollinger_data.get("middle")),
        lower=safe_float(bollinger_data.get("lower")),
        state=str(bollinger_data.get("state") or "INSIDE"),
        bandwidth=safe_float(bollinger_data.get("bandwidth")),
    )

    stat_strength = StatisticalStrengthSnapshot(
        value=safe_float(stat_strength_data.get("value"))
    )

    obv = ObvSnapshot(
        raw_obv_val=safe_float(obv_data.get("raw_obv_val")),
        fd_obv_z=safe_float(obv_data.get("fd_obv_z")),
        optimal_d=safe_float(obv_data.get("optimal_d")),
        state=str(obv_data.get("state") or "NEUTRAL"),
    )

    return FracdiffSerializationResult(
        bollinger=bollinger,
        stat_strength=stat_strength,
        obv=obv,
        fracdiff_series=_series_to_json(fd_series),
        z_score_series=_series_to_json(z_score_series),
    )
