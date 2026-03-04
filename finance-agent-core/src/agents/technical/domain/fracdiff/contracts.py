from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias, TypedDict

import pandas as pd


@dataclass(frozen=True)
class BollingerSnapshot:
    upper: float | None
    middle: float | None
    lower: float | None
    state: str
    bandwidth: float | None

    def to_dict(self) -> dict[str, float | str | None]:
        return {
            "upper": self.upper,
            "middle": self.middle,
            "lower": self.lower,
            "state": self.state,
            "bandwidth": self.bandwidth,
        }


@dataclass(frozen=True)
class StatisticalStrengthSnapshot:
    value: float | None

    def to_dict(self) -> dict[str, float | None]:
        return {"value": self.value}


@dataclass(frozen=True)
class ObvSnapshot:
    raw_obv_val: float | None
    fd_obv_z: float | None
    optimal_d: float | None
    state: str

    def to_dict(self) -> dict[str, float | str | None]:
        return {
            "raw_obv_val": self.raw_obv_val,
            "fd_obv_z": self.fd_obv_z,
            "optimal_d": self.optimal_d,
            "state": self.state,
        }


@dataclass(frozen=True)
class FracdiffSerializationResult:
    bollinger: BollingerSnapshot
    stat_strength: StatisticalStrengthSnapshot
    obv: ObvSnapshot
    fracdiff_series: dict[str, float | None]
    z_score_series: dict[str, float | None]


class StatisticalStrengthSeries(TypedDict):
    value: float
    series_value: pd.Series


class BollingerIndicator(TypedDict):
    upper: float
    middle: float
    lower: float
    state: str
    bandwidth: float
    series_upper: pd.Series
    series_lower: pd.Series


class ObvIndicator(TypedDict):
    raw_obv_val: float
    fd_obv_z: float
    optimal_d: float
    state: str
    series_z: pd.Series


class MacdIndicator(TypedDict):
    macd: float
    signal: float
    hist: float
    momentum_state: str


RollingFracdiffOutput: TypeAlias = tuple[pd.Series, float, int, float, float]
