from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from src.agents.technical.interface.contracts import (
    AnalystPerspectiveModel,
    EvidenceBreakoutSignalModel,
    EvidenceScorecardSummaryModel,
    QuantContextSummaryModel,
    RegimeSummaryModel,
    StructureConfluenceSummaryModel,
    VolumeProfileSummaryModel,
)
from src.agents.technical.subdomains.signal_fusion import SemanticTagPolicyResult
from src.interface.artifacts.artifact_data_models import (
    TechnicalAlertsArtifactData,
    TechnicalDirectionScorecardArtifactData,
    TechnicalFeaturePackArtifactData,
    TechnicalFusionReportArtifactData,
    TechnicalPatternPackArtifactData,
    TechnicalRegimePackArtifactData,
    TechnicalVerificationReportArtifactData,
)
from src.shared.kernel.types import JSONObject


class PriceSeriesDataLike(Protocol):
    price_series: dict[str, float]
    volume_series: dict[str, float]


class TechnicalChartDataLike(Protocol):
    fracdiff_series: dict[str, float]
    z_score_series: dict[str, float]


@dataclass(frozen=True)
class BacktestContextResult:
    backtest_context: str
    wfa_context: str
    price_data: PriceSeriesDataLike | None
    chart_data: TechnicalChartDataLike | None
    verification_report: TechnicalVerificationReportArtifactData | None = None
    is_degraded: bool = False
    failure_code: str | None = None


@dataclass(frozen=True)
class SemanticFinalizeResult:
    direction: str
    opt_d: float
    raw_data: JSONObject
    full_report_data_raw: JSONObject
    ta_update: JSONObject


@dataclass(frozen=True)
class SemanticPipelineResult:
    tags_result: SemanticTagPolicyResult
    analyst_perspective: AnalystPerspectiveModel
    backtest_context_result: BacktestContextResult
    semantic_finalize_result: SemanticFinalizeResult
    llm_is_fallback: bool = False
    llm_failure_code: str | None = None
    is_degraded: bool = False
    degraded_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class TechnicalEvidenceBundle:
    primary_timeframe: str | None = None
    support_levels: tuple[float, ...] = ()
    resistance_levels: tuple[float, ...] = ()
    breakout_signals: tuple[EvidenceBreakoutSignalModel, ...] = ()
    scorecard_summary: EvidenceScorecardSummaryModel | None = None
    quant_context_summary: QuantContextSummaryModel | None = None
    regime_summary: RegimeSummaryModel | None = None
    volume_profile_summary: VolumeProfileSummaryModel | None = None
    structure_confluence_summary: StructureConfluenceSummaryModel | None = None
    conflict_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class TechnicalProjectionArtifacts:
    feature_pack: TechnicalFeaturePackArtifactData | None = None
    pattern_pack: TechnicalPatternPackArtifactData | None = None
    regime_pack: TechnicalRegimePackArtifactData | None = None
    fusion_report: TechnicalFusionReportArtifactData | None = None
    alerts: TechnicalAlertsArtifactData | None = None
    direction_scorecard: TechnicalDirectionScorecardArtifactData | None = None
    evidence_bundle: TechnicalEvidenceBundle | None = None


class TechnicalPortLike(Protocol):
    async def load_price_and_chart_data(
        self,
        price_artifact_id: str | None,
        chart_artifact_id: str | None,
    ) -> tuple[PriceSeriesDataLike | None, TechnicalChartDataLike | None]: ...

    async def load_verification_report(
        self,
        artifact_id: str | None,
    ) -> TechnicalVerificationReportArtifactData | None: ...

    async def load_pattern_pack(
        self,
        artifact_id: str | None,
    ) -> TechnicalPatternPackArtifactData | None: ...

    async def load_feature_pack(
        self,
        artifact_id: str | None,
    ) -> TechnicalFeaturePackArtifactData | None: ...

    async def load_regime_pack(
        self,
        artifact_id: str | None,
    ) -> TechnicalRegimePackArtifactData | None: ...

    async def load_fusion_report(
        self,
        artifact_id: str | None,
    ) -> TechnicalFusionReportArtifactData | None: ...

    async def load_alerts(
        self,
        artifact_id: str | None,
    ) -> TechnicalAlertsArtifactData | None: ...

    async def load_direction_scorecard(
        self,
        artifact_id: str | None,
    ) -> TechnicalDirectionScorecardArtifactData | None: ...
