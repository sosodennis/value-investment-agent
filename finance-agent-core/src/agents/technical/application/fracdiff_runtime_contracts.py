from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from src.agents.technical.subdomains.features.domain import (
    BollingerIndicator,
    MacdIndicator,
    ObvIndicator,
    StatisticalStrengthSeries,
)
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
    macd: MacdIndicator
    obv: dict[str, float | str | None]
    chart_data: JSONObject


StatisticalStrengthInput: TypeAlias = StatisticalStrengthSeries
BollingerInput: TypeAlias = BollingerIndicator
ObvInput: TypeAlias = ObvIndicator


@dataclass(frozen=True)
class FracdiffBacktestInputs:
    stat_strength_dict: StatisticalStrengthInput
    bollinger_dict: BollingerInput
    obv_dict: ObvInput
