from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from src.common.types import JSONObject

from .shared import (
    normalize_series_map,
    symbol,
    to_number,
    to_optional_string,
    to_string,
    validate_and_dump,
)

MEMORY_STRENGTH_MAP: dict[str, str] = {
    "structurally_stable": "structurally_stable",
    "balanced": "balanced",
    "fragile": "fragile",
}

STATISTICAL_STATE_MAP: dict[str, str] = {
    "equilibrium": "equilibrium",
    "deviating": "deviating",
    "anomaly": "anomaly",
    "statistical_anomaly": "anomaly",
}

RISK_LEVEL_MAP: dict[str, str] = {
    "low": "low",
    "medium": "medium",
    "critical": "critical",
    "high": "critical",
}


class FracDiffMetricsModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    optimal_d: float
    window_length: int
    adf_statistic: float
    adf_pvalue: float
    memory_strength: Literal["structurally_stable", "balanced", "fragile"]

    @field_validator("optimal_d", "adf_statistic", "adf_pvalue", mode="before")
    @classmethod
    def _numeric(cls, value: object) -> float:
        return to_number(value, "frac_diff numeric")

    @field_validator("window_length", mode="before")
    @classmethod
    def _window(cls, value: object) -> int:
        return int(to_number(value, "frac_diff.window_length"))

    @field_validator("memory_strength", mode="before")
    @classmethod
    def _memory_strength(cls, value: object) -> str:
        return symbol(value, "frac_diff.memory_strength", MEMORY_STRENGTH_MAP)


class ConfluenceEvidenceModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    bollinger_state: str
    macd_momentum: str
    obv_state: str
    statistical_strength: float

    @field_validator("bollinger_state", "macd_momentum", "obv_state", mode="before")
    @classmethod
    def _strings(cls, value: object) -> str:
        return to_string(value, "confluence string")

    @field_validator("statistical_strength", mode="before")
    @classmethod
    def _strength(cls, value: object) -> float:
        return to_number(value, "confluence.statistical_strength")


class SignalStateModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    z_score: float
    statistical_state: Literal["equilibrium", "deviating", "anomaly"]
    direction: str
    risk_level: Literal["low", "medium", "critical"]
    confluence: ConfluenceEvidenceModel

    @field_validator("z_score", mode="before")
    @classmethod
    def _z_score(cls, value: object) -> float:
        return to_number(value, "signal_state.z_score")

    @field_validator("statistical_state", mode="before")
    @classmethod
    def _statistical_state(cls, value: object) -> str:
        return symbol(value, "signal_state.statistical_state", STATISTICAL_STATE_MAP)

    @field_validator("direction", mode="before")
    @classmethod
    def _direction(cls, value: object) -> str:
        return to_string(value, "signal_state.direction")

    @field_validator("risk_level", mode="before")
    @classmethod
    def _risk_level(cls, value: object) -> str:
        return symbol(value, "signal_state.risk_level", RISK_LEVEL_MAP)


class RawDataModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    price_series: dict[str, float] | None = None
    fracdiff_series: dict[str, float] | None = None
    z_score_series: dict[str, float] | None = None

    @field_validator("price_series", "fracdiff_series", "z_score_series", mode="before")
    @classmethod
    def _series(cls, value: object) -> dict[str, float] | None:
        if value is None:
            return None
        return normalize_series_map(value, "raw_data.series")


class TechnicalArtifactModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ticker: str
    timestamp: str
    frac_diff_metrics: FracDiffMetricsModel
    signal_state: SignalStateModel
    semantic_tags: list[str]
    llm_interpretation: str | None = None
    raw_data: RawDataModel | None = None

    @field_validator("ticker", "timestamp", "llm_interpretation", mode="before")
    @classmethod
    def _text_fields(cls, value: object) -> str | None:
        return to_optional_string(value, "technical text")

    @field_validator("semantic_tags", mode="before")
    @classmethod
    def _semantic_tags(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            raise TypeError("technical.semantic_tags must be a list")
        return [to_string(item, "technical.semantic_tags[]") for item in value]


def parse_technical_artifact_model(value: object) -> JSONObject:
    return validate_and_dump(
        TechnicalArtifactModel,
        value,
        "technical artifact",
        exclude_none=True,
    )
