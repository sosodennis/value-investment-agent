from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from src.interface.artifacts.artifact_model_shared import validate_and_dump
from src.shared.kernel.types import JSONObject

from .types import (
    ConfluenceText,
    FracDiffNumber,
    MemoryStrength,
    NormalizedSeriesMap,
    OptionalTechnicalText,
    RiskLevel,
    SignalDirection,
    StatisticalState,
    StatisticalStrength,
    TechnicalStringList,
    TechnicalText,
    WindowLength,
    ZScore,
)


class FracDiffMetricsModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    optimal_d: FracDiffNumber
    window_length: WindowLength
    adf_statistic: FracDiffNumber
    adf_pvalue: FracDiffNumber
    memory_strength: MemoryStrength


class ConfluenceEvidenceModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    bollinger_state: ConfluenceText
    macd_momentum: ConfluenceText
    obv_state: ConfluenceText
    statistical_strength: StatisticalStrength


class SignalStateModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    z_score: ZScore
    statistical_state: StatisticalState
    direction: SignalDirection
    risk_level: RiskLevel
    confluence: ConfluenceEvidenceModel


class RawDataModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    price_series: NormalizedSeriesMap = None
    fracdiff_series: NormalizedSeriesMap = None
    z_score_series: NormalizedSeriesMap = None


class TechnicalArtifactModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ticker: TechnicalText
    timestamp: TechnicalText
    frac_diff_metrics: FracDiffMetricsModel
    signal_state: SignalStateModel
    semantic_tags: TechnicalStringList
    llm_interpretation: OptionalTechnicalText = None
    raw_data: RawDataModel | None = None


def parse_technical_artifact_model(value: object) -> JSONObject:
    return validate_and_dump(
        TechnicalArtifactModel,
        value,
        "technical artifact",
        exclude_none=True,
    )
