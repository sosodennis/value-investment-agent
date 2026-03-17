from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from src.agents.debate.interface.contracts import EvidenceFactModel
from src.agents.fundamental.subdomains.financial_statements.interface.contracts import (
    FinancialReportModel,
)
from src.agents.news.interface.contracts import (
    FinancialNewsItemModel,
    NewsSearchResultItemModel,
)


class FinancialReportsArtifactData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    financial_reports: list[FinancialReportModel]
    forward_signals: list[dict[str, object]] | None = None
    diagnostics: dict[str, object] | None = None
    quality_gates: dict[str, object] | None = None
    valuation_diagnostics: dict[str, object] | None = None
    ticker: str | None = None
    model_type: str | None = None
    company_name: str | None = None
    sector: str | None = None
    industry: str | None = None
    reasoning: str | None = None
    status: Literal["done"] | None = None
    replay_schema_version: str | None = None
    replay_source_reports_artifact_id: str | None = None
    replay_market_snapshot: dict[str, object] | None = None
    replay_params_dump: dict[str, object] | None = None
    replay_calculation_metrics: dict[str, object] | None = None
    replay_assumptions: list[str] | None = None
    replay_build_metadata: dict[str, object] | None = None


class PriceSeriesArtifactData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    price_series: dict[str, float | None]
    volume_series: dict[str, float | None]


class TechnicalChartArtifactData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fracdiff_series: dict[str, float | None]
    z_score_series: dict[str, float | None]
    indicators: dict[str, object]


class TechnicalTimeseriesFrameData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timeframe: str
    start: str
    end: str
    open_series: dict[str, float | None]
    high_series: dict[str, float | None]
    low_series: dict[str, float | None]
    close_series: dict[str, float | None]
    price_series: dict[str, float | None]
    volume_series: dict[str, float | None]
    timezone: str | None = None
    metadata: dict[str, object] | None = None


class TechnicalTimeseriesBundleArtifactData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str
    as_of: str
    frames: dict[str, TechnicalTimeseriesFrameData]
    degraded_reasons: list[str] | None = None


class TechnicalIndicatorSeriesFrameData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timeframe: str
    start: str
    end: str
    series: dict[str, dict[str, float | None]]
    timezone: str | None = None
    metadata: dict[str, object] | None = None


class TechnicalIndicatorSeriesArtifactData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str
    as_of: str
    timeframes: dict[str, TechnicalIndicatorSeriesFrameData]
    degraded_reasons: list[str] | None = None


class TechnicalAlertSignalData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    severity: Literal["info", "warning", "critical"]
    timeframe: str
    title: str
    message: str | None = None
    value: float | None = None
    threshold: float | None = None
    direction: str | None = None
    triggered_at: str | None = None
    source: str | None = None
    metadata: dict[str, object] | None = None


class TechnicalAlertsArtifactData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str
    as_of: str
    alerts: list[TechnicalAlertSignalData]
    summary: dict[str, object] | None = None
    degraded_reasons: list[str] | None = None
    source_artifacts: dict[str, str | None] | None = None


class TechnicalFeatureIndicatorData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    value: float | None
    state: str | None = None
    metadata: dict[str, object] | None = None


class TechnicalFeatureFrameData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    classic_indicators: dict[str, TechnicalFeatureIndicatorData]
    quant_features: dict[str, TechnicalFeatureIndicatorData]


class TechnicalFeaturePackArtifactData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str
    as_of: str
    timeframes: dict[str, TechnicalFeatureFrameData]
    feature_summary: dict[str, object] | None = None
    degraded_reasons: list[str] | None = None


class TechnicalPatternLevelData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    price: float
    strength: float | None = None
    touches: int | None = None
    label: str | None = None


class TechnicalPatternFlagData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    confidence: float | None = None
    notes: str | None = None


class TechnicalVolumeProfileSummaryData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    poc: float | None = None
    vah: float | None = None
    val: float | None = None
    profile_method: str | None = None
    profile_fidelity: str | None = None
    bucket_count: int | None = None
    value_area_coverage: float | None = None


class TechnicalPatternFrameData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    support_levels: list[TechnicalPatternLevelData]
    resistance_levels: list[TechnicalPatternLevelData]
    volume_profile_levels: list[TechnicalPatternLevelData] = []
    volume_profile_summary: TechnicalVolumeProfileSummaryData | None = None
    breakouts: list[TechnicalPatternFlagData]
    trendlines: list[TechnicalPatternFlagData]
    pattern_flags: list[TechnicalPatternFlagData]
    confluence_metadata: dict[str, object] | None = None
    confidence_scores: dict[str, float] = {}


class TechnicalPatternPackArtifactData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str
    as_of: str
    timeframes: dict[str, TechnicalPatternFrameData]
    pattern_summary: dict[str, object] | None = None
    degraded_reasons: list[str] | None = None


class TechnicalRegimeFrameData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timeframe: str
    regime: str
    confidence: float | None = None
    directional_bias: str
    adx: float | None = None
    atr_value: float | None = None
    atrp_value: float | None = None
    bollinger_bandwidth: float | None = None
    evidence: list[str] = []
    metadata: dict[str, object] | None = None


class TechnicalRegimePackArtifactData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str
    as_of: str
    timeframes: dict[str, TechnicalRegimeFrameData]
    regime_summary: dict[str, object] | None = None
    degraded_reasons: list[str] | None = None


class TechnicalFusionReportArtifactData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    ticker: str
    as_of: str
    direction: str
    risk_level: str
    confidence: float | None = None
    confidence_raw: float | None = None
    confidence_calibrated: float | None = None
    confidence_calibration: dict[str, object] | None = None
    confluence_matrix: dict[str, dict[str, object]] | None = None
    conflict_reasons: list[str] | None = None
    regime_summary: dict[str, object] | None = None
    alignment_report: dict[str, object] | None = None
    source_artifacts: dict[str, str | None] | None = None
    degraded_reasons: list[str] | None = None


class TechnicalScorecardContributionData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    value: float | None
    state: str | None = None
    contribution: float
    weight: float | None = None
    notes: str | None = None


class TechnicalScorecardFrameData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timeframe: str
    base_total_score: float | None = None
    classic_score: float
    quant_score: float
    pattern_score: float
    total_score: float
    classic_label: str
    quant_label: str
    pattern_label: str
    regime: str | None = None
    regime_directional_bias: str | None = None
    regime_weight_multiplier: float | None = None
    regime_notes: list[str] | None = None
    contributions: dict[str, list[TechnicalScorecardContributionData]]


class TechnicalDirectionScorecardArtifactData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    ticker: str
    as_of: str
    direction: str
    risk_level: str
    confidence: float | None = None
    neutral_threshold: float
    overall_score: float
    model_version: str | None = None
    regime_summary: dict[str, object] | None = None
    timeframes: dict[str, TechnicalScorecardFrameData]
    conflict_reasons: list[str] | None = None
    degraded_reasons: list[str] | None = None
    source_artifacts: dict[str, str | None] | None = None


class TechnicalBacktestSummaryData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy_name: str | None = None
    win_rate: float | None = None
    profit_factor: float | None = None
    sharpe_ratio: float | None = None
    max_drawdown: float | None = None
    total_trades: int | None = None


class TechnicalWfaSummaryData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    wfa_sharpe: float | None = None
    wfe_ratio: float | None = None
    wfa_max_drawdown: float | None = None
    period_count: int | None = None


class TechnicalVerificationReportArtifactData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    ticker: str
    as_of: str
    backtest_summary: TechnicalBacktestSummaryData | None = None
    wfa_summary: TechnicalWfaSummaryData | None = None
    robustness_flags: list[str] | None = None
    baseline_gates: dict[str, object] | None = None
    source_artifacts: dict[str, str | None] | None = None
    degraded_reasons: list[str] | None = None


class SearchResultsArtifactData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_results: list[NewsSearchResultItemModel]
    formatted_results: str


class NewsSelectionArtifactData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_indices: list[int]


class NewsArticleArtifactData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_text: str
    title: str | None = None
    url: str | None = None


class NewsItemsListArtifactData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    news_items: list[FinancialNewsItemModel]


class DebateFactsArtifactData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str
    facts: list[EvidenceFactModel]
    facts_hash: str
    generated_at: str
