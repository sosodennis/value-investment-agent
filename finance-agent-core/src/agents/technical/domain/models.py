from __future__ import annotations

from dataclasses import dataclass


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


@dataclass(frozen=True)
class SemanticConfluenceInput:
    bollinger_state: str
    statistical_strength: float
    macd_momentum: str
    obv_state: str
    obv_z: float


@dataclass(frozen=True)
class SemanticTagPolicyInput:
    z_score: float
    optimal_d: float
    confluence: SemanticConfluenceInput


@dataclass(frozen=True)
class SemanticConfluenceResult:
    bollinger_state: str
    statistical_strength: float
    macd_momentum: str
    obv_state: str


@dataclass(frozen=True)
class SemanticTagPolicyResult:
    tags: list[str]
    direction: str
    risk_level: str
    memory_strength: str
    statistical_state: str
    z_score: float
    confluence: SemanticConfluenceResult
    evidence_list: list[str]
