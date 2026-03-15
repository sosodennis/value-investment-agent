from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from src.interface.artifacts.artifact_model_shared import validate_and_dump
from src.shared.kernel.types import JSONObject

from .types import (
    OptionalConfidenceScore,
    OptionalTechnicalText,
    RiskLevel,
    SchemaVersion,
    SignalDirection,
    TechnicalStringList,
    TechnicalText,
)


class ArtifactRefsModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    chart_data_id: OptionalTechnicalText = None
    timeseries_bundle_id: OptionalTechnicalText = None
    indicator_series_id: OptionalTechnicalText = None
    alerts_id: OptionalTechnicalText = None
    feature_pack_id: OptionalTechnicalText = None
    pattern_pack_id: OptionalTechnicalText = None
    fusion_report_id: OptionalTechnicalText = None
    verification_report_id: OptionalTechnicalText = None


class DiagnosticsModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    is_degraded: bool | None = None
    degraded_reasons: list[str] | None = None


class TechnicalArtifactModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_version: SchemaVersion
    ticker: TechnicalText
    as_of: TechnicalText
    direction: SignalDirection
    risk_level: RiskLevel
    confidence: OptionalConfidenceScore = None
    llm_interpretation: OptionalTechnicalText = None
    artifact_refs: ArtifactRefsModel
    summary_tags: TechnicalStringList
    diagnostics: DiagnosticsModel | None = None


def parse_technical_artifact_model(value: object) -> JSONObject:
    return validate_and_dump(
        TechnicalArtifactModel,
        value,
        "technical artifact",
        exclude_none=True,
    )
