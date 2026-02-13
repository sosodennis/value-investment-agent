from __future__ import annotations

from dataclasses import dataclass

from src.common.types import JSONObject


@dataclass(frozen=True)
class FracdiffSerializationResult:
    bollinger: JSONObject
    stat_strength: JSONObject
    obv: JSONObject
    fracdiff_series: dict[str, float | None]
    z_score_series: dict[str, float | None]
