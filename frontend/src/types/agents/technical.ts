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

export interface TechnicalConfidenceEligibility {
    eligible?: boolean | null;
    normalized_direction?: string | null;
    reason_codes?: string[];
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

export interface TechnicalEvidenceBreakoutSignal {
    name: string;
    confidence?: number | null;
    notes?: string | null;
}

export interface TechnicalVolumeProfileLevel {
    price: number;
    strength?: number | null;
    touches?: number | null;
    label?: string | null;
}

export interface TechnicalVolumeProfileSummary {
    timeframe?: string | null;
    level_count?: number | null;
    dominant_level?: TechnicalVolumeProfileLevel;
    levels?: TechnicalVolumeProfileLevel[];
    poc?: number | null;
    vah?: number | null;
    val?: number | null;
    profile_method?: string | null;
    profile_fidelity?: string | null;
    bucket_count?: number | null;
    value_area_coverage?: number | null;
}

export interface TechnicalEvidenceScorecardSummary {
    timeframe?: string | null;
    overall_score?: number | null;
    total_score?: number | null;
    classic_label?: string | null;
    quant_label?: string | null;
    pattern_label?: string | null;
}

export interface TechnicalQuantContextSummary {
    timeframe?: string | null;
    volatility_regime?: string | null;
    liquidity_regime?: string | null;
    stretch_state?: string | null;
    alignment_state?: string | null;
    higher_confirmation_state?: string | null;
    lower_confirmation_state?: string | null;
    volatility_percentile?: number | null;
    liquidity_percentile?: number | null;
    price_vs_sma20_z?: number | null;
    price_distance_atr?: number | null;
    alignment_ratio?: number | null;
}

export interface TechnicalEvidenceBundle {
    primary_timeframe?: string | null;
    support_levels?: number[];
    resistance_levels?: number[];
    breakout_signals?: TechnicalEvidenceBreakoutSignal[];
    scorecard_summary?: TechnicalEvidenceScorecardSummary;
    quant_context_summary?: TechnicalQuantContextSummary;
    regime_summary?: TechnicalRegimeSummary;
    volume_profile_summary?: TechnicalVolumeProfileSummary;
    structure_confluence_summary?: TechnicalStructureConfluenceSummary;
    conflict_reasons?: string[];
}

export interface TechnicalSignalStrengthSummary {
    raw_value?: number | null;
    effective_value?: number | null;
    display_percent?: number | null;
    strength_level?: string | null;
    calibration_status?: string | null;
    source?: string | null;
    probability_eligible?: boolean | null;
}

export interface TechnicalSetupReliabilitySummary {
    level?: string | null;
    calibration_status?: string | null;
    coverage_status?: string | null;
    conflict_level?: string | null;
    reasons?: string[];
    recommended_reliance?: string | null;
}

export interface TechnicalQualitySummary {
    is_degraded?: boolean | null;
    degraded_reasons?: string[];
    overall_quality?: string | null;
    ready_timeframes?: string[];
    degraded_timeframes?: string[];
    regime_inputs_ready_timeframes?: string[];
    unavailable_indicator_count?: number | null;
    alert_quality_gate_counts?: Record<string, number>;
    primary_timeframe?: string | null;
}

export interface TechnicalAlertReadoutItem {
    code: string;
    title: string;
    severity: string;
    timeframe: string;
    policy_code?: string | null;
    lifecycle_state?: string | null;
}

export interface TechnicalAlertReadout {
    total_alerts?: number | null;
    policy_count?: number | null;
    highest_severity?: string | null;
    active_alert_count?: number | null;
    monitoring_alert_count?: number | null;
    suppressed_alert_count?: number | null;
    quality_gate_counts?: Record<string, number>;
    top_alerts?: TechnicalAlertReadoutItem[];
}

export interface TechnicalObservabilitySummary {
    primary_timeframe?: string | null;
    observed_timeframes?: string[];
    loaded_artifacts?: string[];
    missing_artifacts?: string[];
    degraded_artifacts?: string[];
    loaded_artifact_count?: number | null;
    missing_artifact_count?: number | null;
    degraded_reason_count?: number | null;
}

export interface TechnicalChartData {
    fracdiff_series: Record<string, number | null>;
    z_score_series: Record<string, number | null>;
    indicators: Record<string, unknown>;
}

export interface TechnicalTimeseriesFrameMetadata {
    row_count: number;
    source?: string;
    source_timeframe?: string;
    price_basis?: string;
    timezone_normalized?: boolean;
    cache_hit?: boolean | null;
    cache_age_seconds?: number | null;
    cache_bucket?: string | null;
    quality_flags?: string[];
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
    metadata?: TechnicalTimeseriesFrameMetadata | null;
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
    metadata?: {
        source_points: number;
        max_points: number;
        downsample_step: number;
        source_timeframe?: string;
        source_price_basis?: string;
        effective_sample_count?: number;
        minimum_sample_count?: number;
        sample_readiness?: string;
        fidelity?: string;
        quality_flags?: string[];
    } | null;
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
    provenance?: {
        method?: string;
        input_basis?: string;
        source_timeframe?: string;
        calculation_version?: string;
    };
    quality?: {
        effective_sample_count?: number;
        minimum_samples?: number;
        warmup_status?: string;
        fidelity?: string;
        quality_flags?: string[];
    };
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
    feature_summary?: {
        classic_count: number;
        quant_count: number;
        timeframe_count: number;
        ready_timeframes?: string[];
        degraded_timeframes?: string[];
        regime_inputs_ready_timeframes?: string[];
        unavailable_indicator_count?: number;
        overall_quality?: string;
    };
    degraded_reasons?: string[];
}

export interface TechnicalRegimeSummary {
    timeframe_count?: number;
    dominant_regime?: string | null;
    average_confidence?: number | null;
}

export interface TechnicalStructureConfluenceSummary {
    timeframe?: string | null;
    confluence_score?: number | null;
    confluence_state?: string | null;
    volume_node_count?: number | null;
    near_volume_node?: boolean | null;
    near_support?: boolean | null;
    near_resistance?: boolean | null;
    nearest_volume_node?: number | null;
    nearest_support?: number | null;
    nearest_resistance?: number | null;
    poc?: number | null;
    vah?: number | null;
    val?: number | null;
    profile_method?: string | null;
    profile_fidelity?: string | null;
    breakout_bias?: string | null;
    trend_bias?: string | null;
    reasons?: string[];
}

export interface TechnicalPatternSummary {
    timeframe_count: number;
    support_level_count: number;
    resistance_level_count: number;
    volume_profile_level_count: number;
    breakout_count: number;
    trendline_count: number;
    strong_confluence_count: number;
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
    volume_profile_summary?: TechnicalVolumeProfileSummary;
    breakouts: TechnicalPatternFlag[];
    trendlines: TechnicalPatternFlag[];
    pattern_flags: TechnicalPatternFlag[];
    confluence_metadata?: TechnicalStructureConfluenceSummary;
    confidence_scores: Record<string, number>;
}

export interface TechnicalPatternPack {
    ticker: string;
    as_of: string;
    timeframes: Record<string, TechnicalPatternFrame>;
    pattern_summary?: TechnicalPatternSummary;
    degraded_reasons?: string[];
}

export type AlertSeverity = 'info' | 'warning' | 'critical';

export interface TechnicalAlertEvidenceRef {
    artifact_kind: string;
    artifact_id?: string | null;
    timeframe?: string | null;
    signal_key?: string | null;
}

export interface TechnicalAlertPolicyMetadata {
    policy_code: string;
    policy_version: string;
    lifecycle_state: string;
    evidence_refs?: TechnicalAlertEvidenceRef[];
    quality_gate?: string | null;
    trigger_reason?: string | null;
    suppression_reason?: string | null;
}

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
    policy?: TechnicalAlertPolicyMetadata;
}

export interface TechnicalAlertSummary {
    total?: number | null;
    severity_counts?: Record<string, number>;
    generated_at?: string | null;
    policy_count?: number | null;
    lifecycle_counts?: Record<string, number>;
    quality_gate_counts?: Record<string, number>;
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
    signal_strength_raw?: number | null;
    signal_strength_effective?: number | null;
    confidence_calibration?: TechnicalConfidenceCalibration;
    confidence_eligibility?: TechnicalConfidenceEligibility;
    regime_summary?: TechnicalRegimeSummary;
    confluence_matrix?: Record<string, Record<string, unknown>>;
    conflict_reasons?: string[];
    alignment_report?: {
        schema_version: string;
        anchor_timeframe: string;
        input_timeframes: string[];
        alignment_window_start: string;
        alignment_window_end: string;
        rows_before: number;
        rows_after: number;
        dropped_rows: number;
        gap_count: number;
        gap_samples?: string[];
        look_ahead_detected?: boolean | null;
        notes?: string[];
    };
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
    signal_strength_raw?: number | null;
    signal_strength_effective?: number | null;
    confidence_calibration?: TechnicalConfidenceCalibration;
    confidence_eligibility?: TechnicalConfidenceEligibility;
    momentum_extremes?: TechnicalMomentumExtremes;
    regime_summary?: TechnicalRegimeSummary;
    volume_profile_summary?: TechnicalVolumeProfileSummary;
    structure_confluence_summary?: TechnicalStructureConfluenceSummary;
    evidence_bundle?: TechnicalEvidenceBundle;
    signal_strength_summary?: TechnicalSignalStrengthSummary;
    setup_reliability_summary?: TechnicalSetupReliabilitySummary;
    quality_summary?: TechnicalQualitySummary;
    alert_readout?: TechnicalAlertReadout;
    observability_summary?: TechnicalObservabilitySummary;
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
