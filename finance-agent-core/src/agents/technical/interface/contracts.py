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
    regime_pack_id: OptionalTechnicalText = None
    fusion_report_id: OptionalTechnicalText = None
    direction_scorecard_id: OptionalTechnicalText = None
    verification_report_id: OptionalTechnicalText = None


class DiagnosticsModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    is_degraded: bool | None = None
    degraded_reasons: list[str] | None = None


class ConfidenceCalibrationModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mapping_source: OptionalTechnicalText = None
    mapping_path: OptionalTechnicalText = None
    degraded_reason: OptionalTechnicalText = None
    mapping_version: OptionalTechnicalText = None
    calibration_applied: bool | None = None


class RegimeSummaryModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    timeframe_count: int | None = None
    dominant_regime: OptionalTechnicalText = None
    average_confidence: OptionalConfidenceScore = None


class StructureConfluenceSummaryModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    timeframe: OptionalTechnicalText = None
    confluence_score: OptionalConfidenceScore = None
    confluence_state: OptionalTechnicalText = None
    volume_node_count: int | None = None
    near_volume_node: bool | None = None
    near_support: bool | None = None
    near_resistance: bool | None = None
    nearest_volume_node: OptionalConfidenceScore = None
    nearest_support: OptionalConfidenceScore = None
    nearest_resistance: OptionalConfidenceScore = None
    poc: OptionalConfidenceScore = None
    vah: OptionalConfidenceScore = None
    val: OptionalConfidenceScore = None
    profile_method: OptionalTechnicalText = None
    profile_fidelity: OptionalTechnicalText = None
    breakout_bias: OptionalTechnicalText = None
    trend_bias: OptionalTechnicalText = None
    reasons: list[str] | None = None


class EvidenceScorecardSummaryModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    timeframe: OptionalTechnicalText = None
    overall_score: OptionalConfidenceScore = None
    total_score: OptionalConfidenceScore = None
    classic_label: OptionalTechnicalText = None
    quant_label: OptionalTechnicalText = None
    pattern_label: OptionalTechnicalText = None


class EvidenceBreakoutSignalModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: TechnicalText
    confidence: OptionalConfidenceScore = None
    notes: OptionalTechnicalText = None


class TechnicalEvidenceBundleModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    primary_timeframe: OptionalTechnicalText = None
    support_levels: list[float] | None = None
    resistance_levels: list[float] | None = None
    breakout_signals: list[EvidenceBreakoutSignalModel] | None = None
    scorecard_summary: EvidenceScorecardSummaryModel | None = None
    regime_summary: RegimeSummaryModel | None = None
    volume_profile_summary: dict[str, object] | None = None
    structure_confluence_summary: StructureConfluenceSummaryModel | None = None
    conflict_reasons: list[str] | None = None


class QualitySummaryModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    is_degraded: bool | None = None
    degraded_reasons: list[str] | None = None
    overall_quality: OptionalTechnicalText = None
    ready_timeframes: list[str] | None = None
    degraded_timeframes: list[str] | None = None
    regime_inputs_ready_timeframes: list[str] | None = None
    unavailable_indicator_count: int | None = None
    alert_quality_gate_counts: dict[str, int] | None = None
    primary_timeframe: OptionalTechnicalText = None


class AlertReadoutItemModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: TechnicalText
    title: TechnicalText
    severity: TechnicalText
    timeframe: TechnicalText
    policy_code: OptionalTechnicalText = None
    lifecycle_state: OptionalTechnicalText = None


class AlertReadoutModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    total_alerts: int | None = None
    policy_count: int | None = None
    highest_severity: OptionalTechnicalText = None
    active_alert_count: int | None = None
    monitoring_alert_count: int | None = None
    suppressed_alert_count: int | None = None
    quality_gate_counts: dict[str, int] | None = None
    top_alerts: list[AlertReadoutItemModel] | None = None


class ObservabilitySummaryModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    primary_timeframe: OptionalTechnicalText = None
    observed_timeframes: list[str] | None = None
    loaded_artifacts: list[str] | None = None
    missing_artifacts: list[str] | None = None
    degraded_artifacts: list[str] | None = None
    loaded_artifact_count: int | None = None
    missing_artifact_count: int | None = None
    degraded_reason_count: int | None = None


class MomentumExtremesModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    timeframe: OptionalTechnicalText = None
    source: OptionalTechnicalText = None
    rsi_value: OptionalConfidenceScore = None
    rsi_bias: OptionalTechnicalText = None
    fd_z_score: OptionalConfidenceScore = None
    fd_label: OptionalTechnicalText = None
    fd_polarity: OptionalTechnicalText = None
    fd_risk_hint: OptionalTechnicalText = None


class AnalystPerspectiveEvidenceItemModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    label: TechnicalText
    value_text: OptionalTechnicalText = None
    timeframe: OptionalTechnicalText = None
    rationale: TechnicalText


class AnalystPerspectiveSignalExplainerModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    signal: TechnicalText
    plain_name: TechnicalText
    value_text: OptionalTechnicalText = None
    timeframe: OptionalTechnicalText = None
    what_it_means_now: TechnicalText
    why_it_matters_now: TechnicalText


class AnalystPerspectiveModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    stance: TechnicalText
    stance_summary: TechnicalText
    rationale_summary: TechnicalText
    plain_language_summary: OptionalTechnicalText = None
    signal_explainers: list[AnalystPerspectiveSignalExplainerModel] | None = None
    top_evidence: list[AnalystPerspectiveEvidenceItemModel] | None = None
    trigger_condition: OptionalTechnicalText = None
    invalidation_condition: OptionalTechnicalText = None
    invalidation_level: OptionalConfidenceScore = None
    validation_note: OptionalTechnicalText = None
    confidence_note: OptionalTechnicalText = None
    decision_posture: OptionalTechnicalText = None


class TechnicalArtifactModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_version: SchemaVersion
    ticker: TechnicalText
    as_of: TechnicalText
    direction: SignalDirection
    risk_level: RiskLevel
    confidence: OptionalConfidenceScore = None
    confidence_raw: OptionalConfidenceScore = None
    confidence_calibrated: OptionalConfidenceScore = None
    confidence_calibration: ConfidenceCalibrationModel | None = None
    momentum_extremes: MomentumExtremesModel | None = None
    regime_summary: RegimeSummaryModel | None = None
    volume_profile_summary: dict[str, object] | None = None
    structure_confluence_summary: StructureConfluenceSummaryModel | None = None
    evidence_bundle: TechnicalEvidenceBundleModel | None = None
    quality_summary: QualitySummaryModel | None = None
    alert_readout: AlertReadoutModel | None = None
    observability_summary: ObservabilitySummaryModel | None = None
    analyst_perspective: AnalystPerspectiveModel | None = None
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
