export enum RiskLevel {
    LOW = "low",
    MEDIUM = "medium",
    CRITICAL = "critical"
}

export interface TechnicalArtifactRefs {
    chart_data_id?: string;
    timeseries_bundle_id?: string;
    indicator_series_id?: string;
    feature_pack_id?: string;
    pattern_pack_id?: string;
    regime_pack_id?: string;
    alerts_id?: string;
    fusion_report_id?: string;
    direction_scorecard_id?: string;
    verification_report_id?: string;
}

export interface TechnicalDiagnostics {
    is_degraded?: boolean;
    degraded_reasons?: string[];
}

export interface TechnicalConfidenceCalibration {
    mapping_source?: string | null;
    mapping_path?: string | null;
    degraded_reason?: string | null;
    mapping_version?: string | null;
    calibration_applied?: boolean | null;
}

export interface TechnicalMomentumExtremes {
    timeframe?: string | null;
    source?: string | null;
    rsi_value?: number | null;
    rsi_bias?: string | null;
    fd_z_score?: number | null;
    fd_label?: string | null;
    fd_polarity?: string | null;
    fd_risk_hint?: string | null;
}

export interface TechnicalAnalystPerspectiveEvidenceItem {
    label: string;
    value_text?: string | null;
    timeframe?: string | null;
    rationale: string;
}

export interface TechnicalAnalystPerspectiveSignalExplainer {
    signal: string;
    plain_name: string;
    value_text?: string | null;
    timeframe?: string | null;
    what_it_means_now: string;
    why_it_matters_now: string;
}

export interface TechnicalAnalystPerspective {
    stance: string;
    stance_summary: string;
    rationale_summary: string;
    plain_language_summary?: string | null;
    signal_explainers?: TechnicalAnalystPerspectiveSignalExplainer[];
    top_evidence?: TechnicalAnalystPerspectiveEvidenceItem[];
    trigger_condition?: string | null;
    invalidation_condition?: string | null;
    invalidation_level?: number | null;
    validation_note?: string | null;
    confidence_note?: string | null;
    decision_posture?: string | null;
}

export interface TechnicalChartData {
    fracdiff_series: Record<string, number | null>;
    z_score_series: Record<string, number | null>;
    indicators: Record<string, unknown>;
}

export interface TechnicalTimeseriesFrame {
    timeframe: string;
    start: string;
    end: string;
    open_series: Record<string, number | null>;
    high_series: Record<string, number | null>;
    low_series: Record<string, number | null>;
    close_series: Record<string, number | null>;
    price_series: Record<string, number | null>;
    volume_series: Record<string, number | null>;
    timezone?: string | null;
    metadata?: Record<string, unknown> | null;
}

export interface TechnicalTimeseriesBundle {
    ticker: string;
    as_of: string;
    frames: Record<string, TechnicalTimeseriesFrame>;
    degraded_reasons?: string[];
}

export interface TechnicalIndicatorSeriesFrame {
    timeframe: string;
    start: string;
    end: string;
    series: Record<string, Record<string, number | null>>;
    timezone?: string | null;
    metadata?: Record<string, unknown> | null;
}

export interface TechnicalIndicatorSeriesArtifact {
    ticker: string;
    as_of: string;
    timeframes: Record<string, TechnicalIndicatorSeriesFrame>;
    degraded_reasons?: string[];
}

export interface TechnicalFeatureIndicator {
    name: string;
    value: number | null;
    state?: string;
    metadata?: Record<string, unknown>;
}

export interface TechnicalFeatureFrame {
    classic_indicators: Record<string, TechnicalFeatureIndicator>;
    quant_features: Record<string, TechnicalFeatureIndicator>;
}

export interface TechnicalFeaturePack {
    ticker: string;
    as_of: string;
    timeframes: Record<string, TechnicalFeatureFrame>;
    feature_summary?: Record<string, unknown>;
    degraded_reasons?: string[];
}

export interface TechnicalPatternLevel {
    price: number;
    strength?: number | null;
    touches?: number | null;
    label?: string | null;
}

export interface TechnicalPatternFlag {
    name: string;
    confidence?: number | null;
    notes?: string | null;
}

export interface TechnicalPatternFrame {
    support_levels: TechnicalPatternLevel[];
    resistance_levels: TechnicalPatternLevel[];
    volume_profile_levels: TechnicalPatternLevel[];
    volume_profile_summary?: Record<string, unknown>;
    breakouts: TechnicalPatternFlag[];
    trendlines: TechnicalPatternFlag[];
    pattern_flags: TechnicalPatternFlag[];
    confluence_metadata?: Record<string, unknown>;
    confidence_scores: Record<string, number>;
}

export interface TechnicalPatternPack {
    ticker: string;
    as_of: string;
    timeframes: Record<string, TechnicalPatternFrame>;
    pattern_summary?: Record<string, unknown>;
    degraded_reasons?: string[];
}

export type AlertSeverity = 'info' | 'warning' | 'critical';

export interface TechnicalAlertSignal {
    code: string;
    severity: AlertSeverity;
    timeframe: string;
    title: string;
    message?: string | null;
    value?: number | null;
    threshold?: number | null;
    direction?: string | null;
    triggered_at?: string | null;
    source?: string | null;
    metadata?: Record<string, unknown> | null;
}

export interface TechnicalAlertSummary {
    total?: number | null;
    severity_counts?: Record<string, number>;
    generated_at?: string | null;
}

export interface TechnicalAlertsArtifact {
    ticker: string;
    as_of: string;
    alerts: TechnicalAlertSignal[];
    summary?: TechnicalAlertSummary;
    degraded_reasons?: string[];
    source_artifacts?: Record<string, string | null>;
}

export interface TechnicalFusionReport {
    schema_version: string;
    ticker: string;
    as_of: string;
    direction: string;
    risk_level: RiskLevel;
    confidence?: number | null;
    confidence_raw?: number | null;
    confidence_calibrated?: number | null;
    confidence_calibration?: TechnicalConfidenceCalibration;
    confluence_matrix?: Record<string, Record<string, unknown>>;
    conflict_reasons?: string[];
    alignment_report?: Record<string, unknown>;
    source_artifacts?: Record<string, string | null>;
    degraded_reasons?: string[];
}

export interface TechnicalScorecardContribution {
    name: string;
    value: number | null;
    state?: string | null;
    contribution: number;
    weight?: number | null;
    notes?: string | null;
}

export interface TechnicalScorecardFrame {
    timeframe: string;
    classic_score: number;
    quant_score: number;
    pattern_score: number;
    total_score: number;
    classic_label: string;
    quant_label: string;
    pattern_label: string;
    contributions: Record<string, TechnicalScorecardContribution[]>;
}

export interface TechnicalDirectionScorecard {
    schema_version: string;
    ticker: string;
    as_of: string;
    direction: string;
    risk_level: RiskLevel;
    confidence?: number | null;
    neutral_threshold: number;
    overall_score: number;
    model_version?: string | null;
    timeframes: Record<string, TechnicalScorecardFrame>;
    conflict_reasons?: string[];
    degraded_reasons?: string[];
    source_artifacts?: Record<string, string | null>;
}

export interface TechnicalBacktestSummary {
    strategy_name?: string | null;
    win_rate?: number | null;
    profit_factor?: number | null;
    sharpe_ratio?: number | null;
    max_drawdown?: number | null;
    total_trades?: number | null;
}

export interface TechnicalWfaSummary {
    wfa_sharpe?: number | null;
    wfe_ratio?: number | null;
    wfa_max_drawdown?: number | null;
    period_count?: number | null;
}

export interface TechnicalVerificationReport {
    schema_version: string;
    ticker: string;
    as_of: string;
    backtest_summary?: TechnicalBacktestSummary;
    wfa_summary?: TechnicalWfaSummary;
    robustness_flags?: string[];
    baseline_gates?: Record<string, unknown>;
    source_artifacts?: Record<string, string | null>;
    degraded_reasons?: string[];
}

export interface TechnicalAnalysisReport {
    schema_version: string;
    ticker: string;
    as_of: string;
    direction: string;
    risk_level: RiskLevel;
    confidence?: number;
    confidence_raw?: number | null;
    confidence_calibrated?: number | null;
    confidence_calibration?: TechnicalConfidenceCalibration;
    momentum_extremes?: TechnicalMomentumExtremes;
    regime_summary?: Record<string, unknown>;
    volume_profile_summary?: Record<string, unknown>;
    structure_confluence_summary?: Record<string, unknown>;
    analyst_perspective?: TechnicalAnalystPerspective;
    artifact_refs: TechnicalArtifactRefs;
    summary_tags: string[];
    diagnostics?: TechnicalDiagnostics;
}

export type TechnicalAnalysisSuccess = TechnicalAnalysisReport;

export interface TechnicalAnalysisError {
    message: string;
}

export type TechnicalAnalysisResult = TechnicalAnalysisSuccess | TechnicalAnalysisError;
