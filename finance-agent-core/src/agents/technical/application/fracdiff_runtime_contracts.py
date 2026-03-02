from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict

import pandas as pd

from src.shared.kernel.types import JSONObject


@dataclass(frozen=True)
class FracdiffRuntimeResult:
    latest_price: float | None
    optimal_d: float | None
    z_score_latest: float | None
    window_length: int
    adf_statistic: float | None
    adf_pvalue: float | None
    bollinger: dict[str, float | str | None]
    statistical_strength_val: float | None
    macd: JSONObject
    obv: dict[str, float | str | None]
    chart_data: JSONObject


class StatisticalStrengthInput(TypedDict):
    value: float
    series_value: pd.Series


class BollingerInput(TypedDict):
    upper: float
    middle: float
    lower: float
    state: str
    bandwidth: float
    series_upper: pd.Series
    series_lower: pd.Series


class ObvInput(TypedDict):
    raw_obv_val: float
    fd_obv_z: float
    optimal_d: float
    state: str
    series_z: pd.Series


@dataclass(frozen=True)
class FracdiffBacktestInputs:
    stat_strength_dict: StatisticalStrengthInput
    bollinger_dict: BollingerInput
    obv_dict: ObvInput
