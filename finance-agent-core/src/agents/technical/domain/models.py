from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FracdiffSerializationResult:
    bollinger: dict[str, object]
    stat_strength: dict[str, object]
    obv: dict[str, object]
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
