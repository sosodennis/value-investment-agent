import {
    DebateHistoryMessage,
    DebateSuccess,
    Direction,
    EvidenceFact,
    PriceImplication,
    RiskProfileType,
    Scenario,
} from './debate';
import {
    AIAnalysis,
    FinancialEntity,
    FinancialNewsItem,
    ImpactLevel,
    KeyFact,
    NewsResearchOutput,
    SearchCategory,
    SentimentLabel,
    SourceInfo,
} from './news';
import {
    ForwardSignal,
    ForwardSignalEvidence,
    FundamentalAnalysisSuccess,
} from './fundamental';
import { parseFinancialPreview } from './fundamental-preview-parser';
import {
    AlertSeverity,
    RiskLevel,
    TechnicalAlertSignal,
    TechnicalAlertSummary,
    TechnicalAnalystPerspective,
    TechnicalAnalystPerspectiveEvidenceItem,
    TechnicalAnalystPerspectiveSignalExplainer,
    TechnicalAlertsArtifact,
    TechnicalAnalysisReport,
    TechnicalAnalysisSuccess,
    TechnicalArtifactRefs,
    TechnicalAlertReadout,
    TechnicalAlertReadoutItem,
    TechnicalChartData,
    TechnicalConfidenceCalibration,
    TechnicalConfidenceEligibility,
    TechnicalDiagnostics,
    TechnicalEvidenceBundle,
    TechnicalFeatureFrame,
    TechnicalFeatureIndicator,
    TechnicalFeaturePack,
    TechnicalFusionReport,
    TechnicalDirectionScorecard,
    TechnicalScorecardContribution,
    TechnicalScorecardFrame,
    TechnicalVerificationReport,
    TechnicalPatternFlag,
    TechnicalPatternFrame,
    TechnicalPatternLevel,
    TechnicalPatternPack,
    TechnicalPatternSummary,
    TechnicalObservabilitySummary,
    TechnicalQualitySummary,
    TechnicalIndicatorSeriesArtifact,
    TechnicalIndicatorSeriesFrame,
    TechnicalQuantContextSummary,
    TechnicalRegimeSummary,
    TechnicalSetupReliabilitySummary,
    TechnicalSignalStrengthSummary,
    TechnicalVolumeProfileLevel,
    TechnicalVolumeProfileSummary,
    TechnicalStructureConfluenceSummary,
    TechnicalTimeseriesBundle,
    TechnicalTimeseriesFrame,
    TechnicalMomentumExtremes,
} from './technical';
import { isRecord } from '../preview';

const toRecord = (value: unknown, context: string): Record<string, unknown> => {
    if (!isRecord(value) || Array.isArray(value)) {
        throw new TypeError(`${context} must be an object.`);
    }
    return value;
};

const toRecordArray = (value: unknown, context: string): Record<string, unknown>[] => {
    if (!Array.isArray(value)) {
        throw new TypeError(`${context} must be an array.`);
    }
    return value.map((entry, index) => toRecord(entry, `${context}.${index}`));
};

const parseString = (value: unknown, context: string): string => {
    if (typeof value !== 'string') {
        throw new TypeError(`${context} must be a string.`);
    }
    return value;
};

const parseNumber = (value: unknown, context: string): number => {
    if (typeof value !== 'number') {
        throw new TypeError(`${context} must be a number.`);
    }
    return value;
};

const parseBoolean = (value: unknown, context: string): boolean => {
    if (typeof value !== 'boolean') {
        throw new TypeError(`${context} must be a boolean.`);
    }
    return value;
};

const parseNullableOptionalNumber = (
    value: unknown,
    context: string
): number | undefined => {
    if (value === undefined || value === null) return undefined;
    return parseNumber(value, context);
};

const parseNullableOptionalBoolean = (
    value: unknown,
    context: string
): boolean | undefined => {
    if (value === undefined || value === null) return undefined;
    return parseBoolean(value, context);
};

const parseNullableOptionalString = (
    value: unknown,
    context: string
): string | null | undefined => {
    if (value === undefined || value === null) return value;
    return parseString(value, context);
};

const parseConfidenceCalibration = (
    value: unknown,
    context: string
): TechnicalConfidenceCalibration | undefined => {
    if (value === undefined || value === null) return undefined;
    const record = toRecord(value, context);
    const mappingSource = parseNullableOptionalString(
        record.mapping_source,
        `${context}.mapping_source`
    );
    const mappingPath = parseNullableOptionalString(
        record.mapping_path,
        `${context}.mapping_path`
    );
    const degradedReason = parseNullableOptionalString(
        record.degraded_reason,
        `${context}.degraded_reason`
    );
    const mappingVersion = parseNullableOptionalString(
        record.mapping_version,
        `${context}.mapping_version`
    );
    const calibrationApplied = parseNullableOptionalBoolean(
        record.calibration_applied,
        `${context}.calibration_applied`
    );

    const calibration: TechnicalConfidenceCalibration = {};
    if (typeof mappingSource === 'string') {
        calibration.mapping_source = mappingSource;
    }
    if (mappingPath !== undefined) {
        calibration.mapping_path = mappingPath ?? null;
    }
    if (degradedReason !== undefined) {
        calibration.degraded_reason = degradedReason ?? null;
    }
    if (mappingVersion !== undefined) {
        calibration.mapping_version = mappingVersion ?? null;
    }
    if (calibrationApplied !== undefined) {
        calibration.calibration_applied = calibrationApplied;
    }
    if (Object.keys(calibration).length === 0) {
        return undefined;
    }
    return calibration;
};

const parseConfidenceEligibility = (
    value: unknown,
    context: string
): TechnicalConfidenceEligibility | undefined => {
    if (value === undefined || value === null) return undefined;
    const record = toRecord(value, context);
    const eligible = parseNullableOptionalBoolean(
        record.eligible,
        `${context}.eligible`
    );
    const normalizedDirection = parseNullableOptionalString(
        record.normalized_direction,
        `${context}.normalized_direction`
    );
    const reasonCodes =
        record.reason_codes === undefined || record.reason_codes === null
            ? undefined
            : parseStringArray(record.reason_codes, `${context}.reason_codes`);

    const eligibility: TechnicalConfidenceEligibility = {};
    if (eligible !== undefined) {
        eligibility.eligible = eligible;
    }
    if (normalizedDirection !== undefined) {
        eligibility.normalized_direction = normalizedDirection ?? null;
    }
    if (reasonCodes !== undefined) {
        eligibility.reason_codes = reasonCodes;
    }
    if (Object.keys(eligibility).length === 0) {
        return undefined;
    }
    return eligibility;
};

const parseRegimeSummary = (
    value: unknown,
    context: string
): TechnicalRegimeSummary | undefined => {
    if (value === undefined || value === null) return undefined;
    const record = toRecord(value, context);
    const timeframeCount = parseNullableOptionalNumber(
        record.timeframe_count,
        `${context}.timeframe_count`
    );
    const dominantRegime = parseNullableOptionalString(
        record.dominant_regime,
        `${context}.dominant_regime`
    );
    const averageConfidence = parseNullableOptionalNumber(
        record.average_confidence,
        `${context}.average_confidence`
    );
    const summary: TechnicalRegimeSummary = {};
    if (timeframeCount !== undefined) summary.timeframe_count = timeframeCount;
    if (dominantRegime !== undefined) {
        summary.dominant_regime = dominantRegime ?? null;
    }
    if (averageConfidence !== undefined) {
        summary.average_confidence = averageConfidence;
    }
    return Object.keys(summary).length > 0 ? summary : undefined;
};

const parseStructureConfluenceSummary = (
    value: unknown,
    context: string
): TechnicalStructureConfluenceSummary | undefined => {
    if (value === undefined || value === null) return undefined;
    const record = toRecord(value, context);
    const summary: TechnicalStructureConfluenceSummary = {};
    const stringFields = [
        'timeframe',
        'confluence_state',
        'profile_method',
        'profile_fidelity',
        'breakout_bias',
        'trend_bias',
    ] as const;
    const numericFields = [
        'confluence_score',
        'volume_node_count',
        'nearest_volume_node',
        'nearest_support',
        'nearest_resistance',
        'poc',
        'vah',
        'val',
    ] as const;
    const booleanFields = [
        'near_volume_node',
        'near_support',
        'near_resistance',
    ] as const;

    for (const field of stringFields) {
        const parsed = parseNullableOptionalString(record[field], `${context}.${field}`);
        if (parsed !== undefined) {
            summary[field] = parsed ?? null;
        }
    }
    for (const field of numericFields) {
        const parsed = parseNullableOptionalNumber(record[field], `${context}.${field}`);
        if (parsed !== undefined) {
            summary[field] = parsed;
        }
    }
    for (const field of booleanFields) {
        const parsed = parseNullableOptionalBoolean(record[field], `${context}.${field}`);
        if (parsed !== undefined) {
            summary[field] = parsed;
        }
    }

    const reasons =
        record.reasons === undefined || record.reasons === null
            ? undefined
            : parseStringArray(record.reasons, `${context}.reasons`);
    if (reasons !== undefined) {
        summary.reasons = reasons;
    }

    return Object.keys(summary).length > 0 ? summary : undefined;
};

const parseEvidenceBreakoutSignal = (
    value: unknown,
    context: string
): NonNullable<TechnicalEvidenceBundle['breakout_signals']>[number] => {
    const record = toRecord(value, context);
    const signal: NonNullable<TechnicalEvidenceBundle['breakout_signals']>[number] = {
        name: parseString(record.name, `${context}.name`),
    };
    const confidence = parseNullableOptionalNumber(
        record.confidence,
        `${context}.confidence`
    );
    const notes = parseNullableOptionalString(record.notes, `${context}.notes`);
    if (confidence !== undefined) {
        signal.confidence = confidence;
    }
    if (notes !== undefined) {
        signal.notes = notes ?? null;
    }
    return signal;
};

const parseVolumeProfileLevel = (
    value: unknown,
    context: string
): TechnicalVolumeProfileLevel => {
    const record = toRecord(value, context);
    const level: TechnicalVolumeProfileLevel = {
        price: parseNumber(record.price, `${context}.price`),
    };
    const strength = parseNullableOptionalNumber(record.strength, `${context}.strength`);
    const touches = parseNullableOptionalNumber(record.touches, `${context}.touches`);
    const label = parseNullableOptionalString(record.label, `${context}.label`);
    if (strength !== undefined) level.strength = strength;
    if (touches !== undefined) level.touches = touches;
    if (label !== undefined) level.label = label ?? null;
    return level;
};

const parseVolumeProfileSummary = (
    value: unknown,
    context: string
): TechnicalVolumeProfileSummary | undefined => {
    if (value === undefined || value === null) return undefined;
    const record = toRecord(value, context);
    const summary: TechnicalVolumeProfileSummary = {};
    const timeframe = parseNullableOptionalString(record.timeframe, `${context}.timeframe`);
    const levelCount = parseNullableOptionalNumber(
        record.level_count,
        `${context}.level_count`
    );
    const dominantLevel =
        record.dominant_level === undefined || record.dominant_level === null
            ? undefined
            : parseVolumeProfileLevel(record.dominant_level, `${context}.dominant_level`);
    const levels =
        record.levels === undefined || record.levels === null
            ? undefined
            : toRecordArray(record.levels, `${context}.levels`).map((entry, index) =>
                  parseVolumeProfileLevel(entry, `${context}.levels.${index}`)
              );
    const poc = parseNullableOptionalNumber(record.poc, `${context}.poc`);
    const vah = parseNullableOptionalNumber(record.vah, `${context}.vah`);
    const val = parseNullableOptionalNumber(record.val, `${context}.val`);
    const profileMethod = parseNullableOptionalString(
        record.profile_method,
        `${context}.profile_method`
    );
    const profileFidelity = parseNullableOptionalString(
        record.profile_fidelity,
        `${context}.profile_fidelity`
    );
    const bucketCount = parseNullableOptionalNumber(
        record.bucket_count,
        `${context}.bucket_count`
    );
    const valueAreaCoverage = parseNullableOptionalNumber(
        record.value_area_coverage,
        `${context}.value_area_coverage`
    );
    if (timeframe !== undefined) summary.timeframe = timeframe ?? null;
    if (levelCount !== undefined) summary.level_count = levelCount;
    if (dominantLevel !== undefined) summary.dominant_level = dominantLevel;
    if (levels !== undefined) summary.levels = levels;
    if (poc !== undefined) summary.poc = poc;
    if (vah !== undefined) summary.vah = vah;
    if (val !== undefined) summary.val = val;
    if (profileMethod !== undefined) summary.profile_method = profileMethod ?? null;
    if (profileFidelity !== undefined) {
        summary.profile_fidelity = profileFidelity ?? null;
    }
    if (bucketCount !== undefined) summary.bucket_count = bucketCount;
    if (valueAreaCoverage !== undefined) {
        summary.value_area_coverage = valueAreaCoverage;
    }
    return Object.keys(summary).length > 0 ? summary : undefined;
};

const parseEvidenceScorecardSummary = (
    value: unknown,
    context: string
): TechnicalEvidenceBundle['scorecard_summary'] | undefined => {
    if (value === undefined || value === null) return undefined;
    const record = toRecord(value, context);
    const summary: NonNullable<TechnicalEvidenceBundle['scorecard_summary']> = {};
    const timeframe = parseNullableOptionalString(
        record.timeframe,
        `${context}.timeframe`
    );
    const overallScore = parseNullableOptionalNumber(
        record.overall_score,
        `${context}.overall_score`
    );
    const totalScore = parseNullableOptionalNumber(
        record.total_score,
        `${context}.total_score`
    );
    const classicLabel = parseNullableOptionalString(
        record.classic_label,
        `${context}.classic_label`
    );
    const quantLabel = parseNullableOptionalString(
        record.quant_label,
        `${context}.quant_label`
    );
    const patternLabel = parseNullableOptionalString(
        record.pattern_label,
        `${context}.pattern_label`
    );
    if (timeframe !== undefined) summary.timeframe = timeframe ?? null;
    if (overallScore !== undefined) summary.overall_score = overallScore;
    if (totalScore !== undefined) summary.total_score = totalScore;
    if (classicLabel !== undefined) summary.classic_label = classicLabel ?? null;
    if (quantLabel !== undefined) summary.quant_label = quantLabel ?? null;
    if (patternLabel !== undefined) summary.pattern_label = patternLabel ?? null;
    return Object.keys(summary).length > 0 ? summary : undefined;
};

const parseQuantContextSummary = (
    value: unknown,
    context: string
): TechnicalQuantContextSummary | undefined => {
    if (value === undefined || value === null) return undefined;
    const record = toRecord(value, context);
    const summary: TechnicalQuantContextSummary = {};
    const timeframe = parseNullableOptionalString(record.timeframe, `${context}.timeframe`);
    const volatilityRegime = parseNullableOptionalString(
        record.volatility_regime,
        `${context}.volatility_regime`
    );
    const liquidityRegime = parseNullableOptionalString(
        record.liquidity_regime,
        `${context}.liquidity_regime`
    );
    const stretchState = parseNullableOptionalString(
        record.stretch_state,
        `${context}.stretch_state`
    );
    const alignmentState = parseNullableOptionalString(
        record.alignment_state,
        `${context}.alignment_state`
    );
    const higherConfirmationState = parseNullableOptionalString(
        record.higher_confirmation_state,
        `${context}.higher_confirmation_state`
    );
    const lowerConfirmationState = parseNullableOptionalString(
        record.lower_confirmation_state,
        `${context}.lower_confirmation_state`
    );
    const volatilityPercentile = parseNullableOptionalNumber(
        record.volatility_percentile,
        `${context}.volatility_percentile`
    );
    const liquidityPercentile = parseNullableOptionalNumber(
        record.liquidity_percentile,
        `${context}.liquidity_percentile`
    );
    const priceVsSma20Z = parseNullableOptionalNumber(
        record.price_vs_sma20_z,
        `${context}.price_vs_sma20_z`
    );
    const priceDistanceAtr = parseNullableOptionalNumber(
        record.price_distance_atr,
        `${context}.price_distance_atr`
    );
    const alignmentRatio = parseNullableOptionalNumber(
        record.alignment_ratio,
        `${context}.alignment_ratio`
    );
    if (timeframe !== undefined) summary.timeframe = timeframe ?? null;
    if (volatilityRegime !== undefined) {
        summary.volatility_regime = volatilityRegime ?? null;
    }
    if (liquidityRegime !== undefined) {
        summary.liquidity_regime = liquidityRegime ?? null;
    }
    if (stretchState !== undefined) summary.stretch_state = stretchState ?? null;
    if (alignmentState !== undefined) summary.alignment_state = alignmentState ?? null;
    if (higherConfirmationState !== undefined) {
        summary.higher_confirmation_state = higherConfirmationState ?? null;
    }
    if (lowerConfirmationState !== undefined) {
        summary.lower_confirmation_state = lowerConfirmationState ?? null;
    }
    if (volatilityPercentile !== undefined) {
        summary.volatility_percentile = volatilityPercentile;
    }
    if (liquidityPercentile !== undefined) {
        summary.liquidity_percentile = liquidityPercentile;
    }
    if (priceVsSma20Z !== undefined) summary.price_vs_sma20_z = priceVsSma20Z;
    if (priceDistanceAtr !== undefined) summary.price_distance_atr = priceDistanceAtr;
    if (alignmentRatio !== undefined) summary.alignment_ratio = alignmentRatio;
    return Object.keys(summary).length > 0 ? summary : undefined;
};

const parseEvidenceBundle = (
    value: unknown,
    context: string
): TechnicalEvidenceBundle | undefined => {
    if (value === undefined || value === null) return undefined;
    const record = toRecord(value, context);
    const bundle: TechnicalEvidenceBundle = {};

    const primaryTimeframe = parseNullableOptionalString(
        record.primary_timeframe,
        `${context}.primary_timeframe`
    );
    if (primaryTimeframe !== undefined) {
        bundle.primary_timeframe = primaryTimeframe ?? null;
    }
    if (record.support_levels !== undefined && record.support_levels !== null) {
        bundle.support_levels = parseNumberArray(
            record.support_levels,
            `${context}.support_levels`
        );
    }
    if (record.resistance_levels !== undefined && record.resistance_levels !== null) {
        bundle.resistance_levels = parseNumberArray(
            record.resistance_levels,
            `${context}.resistance_levels`
        );
    }
    if (record.breakout_signals !== undefined && record.breakout_signals !== null) {
        const signals = record.breakout_signals;
        if (!Array.isArray(signals)) {
            throw new TypeError(`${context}.breakout_signals must be an array.`);
        }
        bundle.breakout_signals = signals.map((item, index) =>
            parseEvidenceBreakoutSignal(
                item,
                `${context}.breakout_signals[${index}]`
            )
        );
    }
    const scorecardSummary = parseEvidenceScorecardSummary(
        record.scorecard_summary,
        `${context}.scorecard_summary`
    );
    if (scorecardSummary) {
        bundle.scorecard_summary = scorecardSummary;
    }
    const quantContextSummary = parseQuantContextSummary(
        record.quant_context_summary,
        `${context}.quant_context_summary`
    );
    if (quantContextSummary) {
        bundle.quant_context_summary = quantContextSummary;
    }
    const regimeSummary = parseRegimeSummary(
        record.regime_summary,
        `${context}.regime_summary`
    );
    if (regimeSummary) {
        bundle.regime_summary = regimeSummary;
    }
    const volumeProfileSummary = parseVolumeProfileSummary(
        record.volume_profile_summary,
        `${context}.volume_profile_summary`
    );
    if (volumeProfileSummary) {
        bundle.volume_profile_summary = volumeProfileSummary;
    }
    const structureConfluenceSummary = parseStructureConfluenceSummary(
        record.structure_confluence_summary,
        `${context}.structure_confluence_summary`
    );
    if (structureConfluenceSummary) {
        bundle.structure_confluence_summary = structureConfluenceSummary;
    }
    const conflictReasons =
        record.conflict_reasons === undefined || record.conflict_reasons === null
            ? undefined
            : parseStringArray(record.conflict_reasons, `${context}.conflict_reasons`);
    if (conflictReasons !== undefined) {
        bundle.conflict_reasons = conflictReasons;
    }
    return Object.keys(bundle).length > 0 ? bundle : undefined;
};

const parseSignalStrengthSummary = (
    value: unknown,
    context: string
): TechnicalSignalStrengthSummary | undefined => {
    if (value === undefined || value === null) return undefined;
    const record = toRecord(value, context);
    const summary: TechnicalSignalStrengthSummary = {};
    const rawValue = parseNullableOptionalNumber(record.raw_value, `${context}.raw_value`);
    const effectiveValue = parseNullableOptionalNumber(
        record.effective_value,
        `${context}.effective_value`
    );
    const displayPercent = parseNullableOptionalNumber(
        record.display_percent,
        `${context}.display_percent`
    );
    const strengthLevel = parseNullableOptionalString(
        record.strength_level,
        `${context}.strength_level`
    );
    const calibrationStatus = parseNullableOptionalString(
        record.calibration_status,
        `${context}.calibration_status`
    );
    const source = parseNullableOptionalString(record.source, `${context}.source`);
    const probabilityEligible = parseNullableOptionalBoolean(
        record.probability_eligible,
        `${context}.probability_eligible`
    );
    if (rawValue !== undefined) summary.raw_value = rawValue;
    if (effectiveValue !== undefined) summary.effective_value = effectiveValue;
    if (displayPercent !== undefined) summary.display_percent = displayPercent;
    if (strengthLevel !== undefined) summary.strength_level = strengthLevel ?? null;
    if (calibrationStatus !== undefined) {
        summary.calibration_status = calibrationStatus ?? null;
    }
    if (source !== undefined) summary.source = source ?? null;
    if (probabilityEligible !== undefined) {
        summary.probability_eligible = probabilityEligible;
    }
    return Object.keys(summary).length > 0 ? summary : undefined;
};

const parseSetupReliabilitySummary = (
    value: unknown,
    context: string
): TechnicalSetupReliabilitySummary | undefined => {
    if (value === undefined || value === null) return undefined;
    const record = toRecord(value, context);
    const summary: TechnicalSetupReliabilitySummary = {};
    const stringFields = [
        'level',
        'calibration_status',
        'coverage_status',
        'conflict_level',
        'recommended_reliance',
    ] as const;
    for (const field of stringFields) {
        const parsed = parseNullableOptionalString(record[field], `${context}.${field}`);
        if (parsed !== undefined) {
            summary[field] = parsed ?? null;
        }
    }
    const reasons =
        record.reasons === undefined || record.reasons === null
            ? undefined
            : parseStringArray(record.reasons, `${context}.reasons`);
    if (reasons !== undefined) {
        summary.reasons = reasons;
    }
    return Object.keys(summary).length > 0 ? summary : undefined;
};

const parseNumberMap = (
    value: unknown,
    context: string
): Record<string, number> | undefined => {
    if (value === undefined || value === null) return undefined;
    const record = toRecord(value, context);
    const parsed: Record<string, number> = {};
    for (const [key, entry] of Object.entries(record)) {
        parsed[key] = parseNumber(entry, `${context}.${key}`);
    }
    return Object.keys(parsed).length > 0 ? parsed : undefined;
};

const parseQualitySummary = (
    value: unknown,
    context: string
): TechnicalQualitySummary | undefined => {
    if (value === undefined || value === null) return undefined;
    const record = toRecord(value, context);
    const summary: TechnicalQualitySummary = {};
    const isDegraded = parseNullableOptionalBoolean(
        record.is_degraded,
        `${context}.is_degraded`
    );
    const overallQuality = parseNullableOptionalString(
        record.overall_quality,
        `${context}.overall_quality`
    );
    const unavailableIndicatorCount = parseNullableOptionalNumber(
        record.unavailable_indicator_count,
        `${context}.unavailable_indicator_count`
    );
    const primaryTimeframe = parseNullableOptionalString(
        record.primary_timeframe,
        `${context}.primary_timeframe`
    );
    const degradedReasons =
        record.degraded_reasons === undefined || record.degraded_reasons === null
            ? undefined
            : parseStringArray(record.degraded_reasons, `${context}.degraded_reasons`);
    const readyTimeframes =
        record.ready_timeframes === undefined || record.ready_timeframes === null
            ? undefined
            : parseStringArray(record.ready_timeframes, `${context}.ready_timeframes`);
    const degradedTimeframes =
        record.degraded_timeframes === undefined || record.degraded_timeframes === null
            ? undefined
            : parseStringArray(
                  record.degraded_timeframes,
                  `${context}.degraded_timeframes`
              );
    const regimeInputsReadyTimeframes =
        record.regime_inputs_ready_timeframes === undefined ||
        record.regime_inputs_ready_timeframes === null
            ? undefined
            : parseStringArray(
                  record.regime_inputs_ready_timeframes,
                  `${context}.regime_inputs_ready_timeframes`
              );
    const alertQualityGateCounts = parseNumberMap(
        record.alert_quality_gate_counts,
        `${context}.alert_quality_gate_counts`
    );

    if (isDegraded !== undefined) summary.is_degraded = isDegraded;
    if (degradedReasons !== undefined) summary.degraded_reasons = degradedReasons;
    if (overallQuality !== undefined) summary.overall_quality = overallQuality ?? null;
    if (readyTimeframes !== undefined) summary.ready_timeframes = readyTimeframes;
    if (degradedTimeframes !== undefined) {
        summary.degraded_timeframes = degradedTimeframes;
    }
    if (regimeInputsReadyTimeframes !== undefined) {
        summary.regime_inputs_ready_timeframes = regimeInputsReadyTimeframes;
    }
    if (unavailableIndicatorCount !== undefined) {
        summary.unavailable_indicator_count = unavailableIndicatorCount;
    }
    if (alertQualityGateCounts !== undefined) {
        summary.alert_quality_gate_counts = alertQualityGateCounts;
    }
    if (primaryTimeframe !== undefined) {
        summary.primary_timeframe = primaryTimeframe ?? null;
    }
    return Object.keys(summary).length > 0 ? summary : undefined;
};

const parseAlertReadoutItem = (
    value: unknown,
    context: string
): TechnicalAlertReadoutItem => {
    const record = toRecord(value, context);
    const item: TechnicalAlertReadoutItem = {
        code: parseString(record.code, `${context}.code`),
        title: parseString(record.title, `${context}.title`),
        severity: parseString(record.severity, `${context}.severity`),
        timeframe: parseString(record.timeframe, `${context}.timeframe`),
    };
    const policyCode = parseNullableOptionalString(
        record.policy_code,
        `${context}.policy_code`
    );
    const lifecycleState = parseNullableOptionalString(
        record.lifecycle_state,
        `${context}.lifecycle_state`
    );
    if (policyCode !== undefined) item.policy_code = policyCode ?? null;
    if (lifecycleState !== undefined) {
        item.lifecycle_state = lifecycleState ?? null;
    }
    return item;
};

const parseAlertReadout = (
    value: unknown,
    context: string
): TechnicalAlertReadout | undefined => {
    if (value === undefined || value === null) return undefined;
    const record = toRecord(value, context);
    const readout: TechnicalAlertReadout = {};
    const totalAlerts = parseNullableOptionalNumber(
        record.total_alerts,
        `${context}.total_alerts`
    );
    const policyCount = parseNullableOptionalNumber(
        record.policy_count,
        `${context}.policy_count`
    );
    const highestSeverity = parseNullableOptionalString(
        record.highest_severity,
        `${context}.highest_severity`
    );
    const activeAlertCount = parseNullableOptionalNumber(
        record.active_alert_count,
        `${context}.active_alert_count`
    );
    const monitoringAlertCount = parseNullableOptionalNumber(
        record.monitoring_alert_count,
        `${context}.monitoring_alert_count`
    );
    const suppressedAlertCount = parseNullableOptionalNumber(
        record.suppressed_alert_count,
        `${context}.suppressed_alert_count`
    );
    const qualityGateCounts = parseNumberMap(
        record.quality_gate_counts,
        `${context}.quality_gate_counts`
    );
    if (record.top_alerts !== undefined && record.top_alerts !== null) {
        if (!Array.isArray(record.top_alerts)) {
            throw new TypeError(`${context}.top_alerts must be an array.`);
        }
        readout.top_alerts = record.top_alerts.map((item, index) =>
            parseAlertReadoutItem(item, `${context}.top_alerts[${index}]`)
        );
    }
    if (totalAlerts !== undefined) readout.total_alerts = totalAlerts;
    if (policyCount !== undefined) readout.policy_count = policyCount;
    if (highestSeverity !== undefined) {
        readout.highest_severity = highestSeverity ?? null;
    }
    if (activeAlertCount !== undefined) {
        readout.active_alert_count = activeAlertCount;
    }
    if (monitoringAlertCount !== undefined) {
        readout.monitoring_alert_count = monitoringAlertCount;
    }
    if (suppressedAlertCount !== undefined) {
        readout.suppressed_alert_count = suppressedAlertCount;
    }
    if (qualityGateCounts !== undefined) {
        readout.quality_gate_counts = qualityGateCounts;
    }
    return Object.keys(readout).length > 0 ? readout : undefined;
};

const parseObservabilitySummary = (
    value: unknown,
    context: string
): TechnicalObservabilitySummary | undefined => {
    if (value === undefined || value === null) return undefined;
    const record = toRecord(value, context);
    const summary: TechnicalObservabilitySummary = {};
    const primaryTimeframe = parseNullableOptionalString(
        record.primary_timeframe,
        `${context}.primary_timeframe`
    );
    const observedTimeframes =
        record.observed_timeframes === undefined || record.observed_timeframes === null
            ? undefined
            : parseStringArray(record.observed_timeframes, `${context}.observed_timeframes`);
    const loadedArtifacts =
        record.loaded_artifacts === undefined || record.loaded_artifacts === null
            ? undefined
            : parseStringArray(record.loaded_artifacts, `${context}.loaded_artifacts`);
    const missingArtifacts =
        record.missing_artifacts === undefined || record.missing_artifacts === null
            ? undefined
            : parseStringArray(record.missing_artifacts, `${context}.missing_artifacts`);
    const degradedArtifacts =
        record.degraded_artifacts === undefined || record.degraded_artifacts === null
            ? undefined
            : parseStringArray(record.degraded_artifacts, `${context}.degraded_artifacts`);
    const loadedArtifactCount = parseNullableOptionalNumber(
        record.loaded_artifact_count,
        `${context}.loaded_artifact_count`
    );
    const missingArtifactCount = parseNullableOptionalNumber(
        record.missing_artifact_count,
        `${context}.missing_artifact_count`
    );
    const degradedReasonCount = parseNullableOptionalNumber(
        record.degraded_reason_count,
        `${context}.degraded_reason_count`
    );
    if (primaryTimeframe !== undefined) {
        summary.primary_timeframe = primaryTimeframe ?? null;
    }
    if (observedTimeframes !== undefined) summary.observed_timeframes = observedTimeframes;
    if (loadedArtifacts !== undefined) summary.loaded_artifacts = loadedArtifacts;
    if (missingArtifacts !== undefined) summary.missing_artifacts = missingArtifacts;
    if (degradedArtifacts !== undefined) summary.degraded_artifacts = degradedArtifacts;
    if (loadedArtifactCount !== undefined) {
        summary.loaded_artifact_count = loadedArtifactCount;
    }
    if (missingArtifactCount !== undefined) {
        summary.missing_artifact_count = missingArtifactCount;
    }
    if (degradedReasonCount !== undefined) {
        summary.degraded_reason_count = degradedReasonCount;
    }
    return Object.keys(summary).length > 0 ? summary : undefined;
};

const parsePatternSummary = (
    value: unknown,
    context: string
): TechnicalPatternSummary | undefined => {
    if (value === undefined || value === null) return undefined;
    const record = toRecord(value, context);
    return {
        timeframe_count: parseNumber(record.timeframe_count, `${context}.timeframe_count`),
        support_level_count: parseNumber(
            record.support_level_count,
            `${context}.support_level_count`
        ),
        resistance_level_count: parseNumber(
            record.resistance_level_count,
            `${context}.resistance_level_count`
        ),
        volume_profile_level_count: parseNumber(
            record.volume_profile_level_count,
            `${context}.volume_profile_level_count`
        ),
        breakout_count: parseNumber(record.breakout_count, `${context}.breakout_count`),
        trendline_count: parseNumber(record.trendline_count, `${context}.trendline_count`),
        strong_confluence_count: parseNumber(
            record.strong_confluence_count,
            `${context}.strong_confluence_count`
        ),
    };
};

const parseAlignmentReport = (
    value: unknown,
    context: string
): TechnicalFusionReport['alignment_report'] | undefined => {
    if (value === undefined || value === null) return undefined;
    const record = toRecord(value, context);
    const report: NonNullable<TechnicalFusionReport['alignment_report']> = {
        schema_version: parseString(record.schema_version, `${context}.schema_version`),
        anchor_timeframe: parseString(
            record.anchor_timeframe,
            `${context}.anchor_timeframe`
        ),
        input_timeframes: parseStringArray(
            record.input_timeframes,
            `${context}.input_timeframes`
        ),
        alignment_window_start: parseString(
            record.alignment_window_start,
            `${context}.alignment_window_start`
        ),
        alignment_window_end: parseString(
            record.alignment_window_end,
            `${context}.alignment_window_end`
        ),
        rows_before: parseNumber(record.rows_before, `${context}.rows_before`),
        rows_after: parseNumber(record.rows_after, `${context}.rows_after`),
        dropped_rows: parseNumber(record.dropped_rows, `${context}.dropped_rows`),
        gap_count: parseNumber(record.gap_count, `${context}.gap_count`),
    };
    const gapSamples =
        record.gap_samples === undefined || record.gap_samples === null
            ? undefined
            : parseStringArray(record.gap_samples, `${context}.gap_samples`);
    const lookAheadDetected = parseNullableOptionalBoolean(
        record.look_ahead_detected,
        `${context}.look_ahead_detected`
    );
    const notes =
        record.notes === undefined || record.notes === null
            ? undefined
            : parseStringArray(record.notes, `${context}.notes`);
    if (gapSamples !== undefined) report.gap_samples = gapSamples;
    if (lookAheadDetected !== undefined) {
        report.look_ahead_detected = lookAheadDetected;
    }
    if (notes !== undefined) report.notes = notes;
    return report;
};

const parseMomentumExtremes = (
    value: unknown,
    context: string
): TechnicalMomentumExtremes | undefined => {
    if (value === undefined || value === null) return undefined;
    const record = toRecord(value, context);
    const timeframe = parseNullableOptionalString(
        record.timeframe,
        `${context}.timeframe`
    );
    const source = parseNullableOptionalString(record.source, `${context}.source`);
    const rsiValue = parseNullableOptionalNumber(
        record.rsi_value,
        `${context}.rsi_value`
    );
    const rsiBias = parseNullableOptionalString(
        record.rsi_bias,
        `${context}.rsi_bias`
    );
    const fdZScore = parseNullableOptionalNumber(
        record.fd_z_score,
        `${context}.fd_z_score`
    );
    const fdLabel = parseNullableOptionalString(
        record.fd_label,
        `${context}.fd_label`
    );
    const fdPolarity = parseNullableOptionalString(
        record.fd_polarity,
        `${context}.fd_polarity`
    );
    const fdRiskHint = parseNullableOptionalString(
        record.fd_risk_hint,
        `${context}.fd_risk_hint`
    );

    const momentum: TechnicalMomentumExtremes = {};
    if (timeframe !== undefined) momentum.timeframe = timeframe ?? null;
    if (source !== undefined) momentum.source = source ?? null;
    if (rsiValue !== undefined) momentum.rsi_value = rsiValue;
    if (rsiBias !== undefined) momentum.rsi_bias = rsiBias ?? null;
    if (fdZScore !== undefined) momentum.fd_z_score = fdZScore;
    if (fdLabel !== undefined) momentum.fd_label = fdLabel ?? null;
    if (fdPolarity !== undefined) momentum.fd_polarity = fdPolarity ?? null;
    if (fdRiskHint !== undefined) momentum.fd_risk_hint = fdRiskHint ?? null;

    if (Object.keys(momentum).length === 0) {
        return undefined;
    }
    return momentum;
};

const parseAnalystPerspectiveEvidenceItem = (
    value: unknown,
    context: string
): TechnicalAnalystPerspectiveEvidenceItem => {
    const record = toRecord(value, context);
    const item: TechnicalAnalystPerspectiveEvidenceItem = {
        label: parseString(record.label, `${context}.label`),
        rationale: parseString(record.rationale, `${context}.rationale`),
    };
    const valueText = parseNullableOptionalString(
        record.value_text,
        `${context}.value_text`
    );
    const timeframe = parseNullableOptionalString(
        record.timeframe,
        `${context}.timeframe`
    );
    if (valueText !== undefined) {
        item.value_text = valueText;
    }
    if (timeframe !== undefined) {
        item.timeframe = timeframe;
    }
    return item;
};

const parseAnalystPerspectiveSignalExplainer = (
    value: unknown,
    context: string
): TechnicalAnalystPerspectiveSignalExplainer => {
    const record = toRecord(value, context);
    const item: TechnicalAnalystPerspectiveSignalExplainer = {
        signal: parseString(record.signal, `${context}.signal`),
        plain_name: parseString(record.plain_name, `${context}.plain_name`),
        what_it_means_now: parseString(
            record.what_it_means_now,
            `${context}.what_it_means_now`
        ),
        why_it_matters_now: parseString(
            record.why_it_matters_now,
            `${context}.why_it_matters_now`
        ),
    };
    const valueText = parseNullableOptionalString(
        record.value_text,
        `${context}.value_text`
    );
    const timeframe = parseNullableOptionalString(
        record.timeframe,
        `${context}.timeframe`
    );
    if (valueText !== undefined) {
        item.value_text = valueText;
    }
    if (timeframe !== undefined) {
        item.timeframe = timeframe;
    }
    return item;
};

const parseAnalystPerspective = (
    value: unknown,
    context: string
): TechnicalAnalystPerspective | undefined => {
    if (value === undefined || value === null) return undefined;
    const record = toRecord(value, context);
    const perspective: TechnicalAnalystPerspective = {
        stance: parseString(record.stance, `${context}.stance`),
        stance_summary: parseString(
            record.stance_summary,
            `${context}.stance_summary`
        ),
        rationale_summary: parseString(
            record.rationale_summary,
            `${context}.rationale_summary`
        ),
    };
    const plainLanguageSummary = parseNullableOptionalString(
        record.plain_language_summary,
        `${context}.plain_language_summary`
    );
    if (plainLanguageSummary !== undefined) {
        perspective.plain_language_summary = plainLanguageSummary;
    }
    if (Array.isArray(record.signal_explainers)) {
        perspective.signal_explainers = record.signal_explainers.map((item, index) =>
            parseAnalystPerspectiveSignalExplainer(
                item,
                `${context}.signal_explainers.${index}`
            )
        );
    }
    if (Array.isArray(record.top_evidence)) {
        perspective.top_evidence = record.top_evidence.map((item, index) =>
            parseAnalystPerspectiveEvidenceItem(
                item,
                `${context}.top_evidence.${index}`
            )
        );
    }
    const triggerCondition = parseNullableOptionalString(
        record.trigger_condition,
        `${context}.trigger_condition`
    );
    const invalidationCondition = parseNullableOptionalString(
        record.invalidation_condition,
        `${context}.invalidation_condition`
    );
    const invalidationLevel = parseNullableOptionalNumber(
        record.invalidation_level,
        `${context}.invalidation_level`
    );
    const validationNote = parseNullableOptionalString(
        record.validation_note,
        `${context}.validation_note`
    );
    const confidenceNote = parseNullableOptionalString(
        record.confidence_note,
        `${context}.confidence_note`
    );
    const decisionPosture = parseNullableOptionalString(
        record.decision_posture,
        `${context}.decision_posture`
    );
    if (triggerCondition !== undefined) {
        perspective.trigger_condition = triggerCondition;
    }
    if (invalidationCondition !== undefined) {
        perspective.invalidation_condition = invalidationCondition;
    }
    if (invalidationLevel !== undefined) {
        perspective.invalidation_level = invalidationLevel;
    }
    if (validationNote !== undefined) {
        perspective.validation_note = validationNote;
    }
    if (confidenceNote !== undefined) {
        perspective.confidence_note = confidenceNote;
    }
    if (decisionPosture !== undefined) {
        perspective.decision_posture = decisionPosture;
    }
    return perspective;
};

const parseForwardSignalDirection = (
    value: unknown,
    context: string
): 'up' | 'down' | 'neutral' => {
    if (value === 'up' || value === 'down' || value === 'neutral') {
        return value;
    }
    throw new TypeError(`${context} must be up | down | neutral.`);
};

const parseSignalUnit = (
    value: unknown,
    context: string
): 'basis_points' | 'ratio' => {
    if (value === 'basis_points' || value === 'ratio') {
        return value;
    }
    throw new TypeError(`${context} must be basis_points | ratio.`);
};

const parseForwardSignalEvidence = (
    value: unknown,
    context: string
): ForwardSignalEvidence => {
    const record = toRecord(value, context);
    const docType = parseNullableOptionalString(record.doc_type, `${context}.doc_type`);
    const period = parseNullableOptionalString(record.period, `${context}.period`);
    const filingDate = parseNullableOptionalString(
        record.filing_date,
        `${context}.filing_date`
    );
    const accessionNumber = parseNullableOptionalString(
        record.accession_number,
        `${context}.accession_number`
    );
    const focusStrategy = parseNullableOptionalString(
        record.focus_strategy,
        `${context}.focus_strategy`
    );
    const rule = parseNullableOptionalString(record.rule, `${context}.rule`);
    const valueBasisPoints = parseNullableOptionalNumber(
        record.value_basis_points,
        `${context}.value_basis_points`
    );
    const sourceLocatorRecord =
        record.source_locator === undefined || record.source_locator === null
            ? undefined
            : toRecord(record.source_locator, `${context}.source_locator`);
    const sourceLocator: NonNullable<ForwardSignalEvidence['source_locator']> | undefined =
        sourceLocatorRecord === undefined
            ? undefined
            : (() => {
                  const textScope = parseString(
                      sourceLocatorRecord.text_scope,
                      `${context}.source_locator.text_scope`
                  );
                  if (textScope !== 'metric_text') {
                      throw new TypeError(
                          `${context}.source_locator.text_scope must be metric_text.`
                      );
                  }
                  const charStart = parseNumber(
                      sourceLocatorRecord.char_start,
                      `${context}.source_locator.char_start`
                  );
                  const charEnd = parseNumber(
                      sourceLocatorRecord.char_end,
                      `${context}.source_locator.char_end`
                  );
                  if (!Number.isInteger(charStart) || charStart < 0) {
                      throw new TypeError(
                          `${context}.source_locator.char_start must be an integer >= 0.`
                      );
                  }
                  if (!Number.isInteger(charEnd) || charEnd <= 0) {
                      throw new TypeError(
                          `${context}.source_locator.char_end must be an integer > 0.`
                      );
                  }
                  if (charEnd < charStart) {
                      throw new TypeError(
                          `${context}.source_locator.char_end must be >= char_start.`
                      );
                  }
                  return {
                      text_scope: 'metric_text',
                      char_start: charStart,
                      char_end: charEnd,
                  };
              })();

    return {
        preview_text: parseString(record.preview_text, `${context}.preview_text`),
        full_text: parseString(record.full_text, `${context}.full_text`),
        source_url: parseString(record.source_url, `${context}.source_url`),
        ...(typeof docType === 'string' ? { doc_type: docType } : {}),
        ...(typeof period === 'string' ? { period } : {}),
        ...(typeof filingDate === 'string' ? { filing_date: filingDate } : {}),
        ...(typeof accessionNumber === 'string'
            ? { accession_number: accessionNumber }
            : {}),
        ...(typeof focusStrategy === 'string' ? { focus_strategy: focusStrategy } : {}),
        ...(typeof rule === 'string' ? { rule } : {}),
        ...(typeof valueBasisPoints === 'number'
            ? { value_basis_points: valueBasisPoints }
            : {}),
        ...(sourceLocator ? { source_locator: sourceLocator } : {}),
    };
};

const parseForwardSignal = (value: unknown, context: string): ForwardSignal => {
    const record = toRecord(value, context);
    if (!Array.isArray(record.evidence)) {
        throw new TypeError(`${context}.evidence must be an array.`);
    }
    return {
        signal_id: parseString(record.signal_id, `${context}.signal_id`),
        source_type: parseString(record.source_type, `${context}.source_type`),
        metric: parseString(record.metric, `${context}.metric`),
        direction: parseForwardSignalDirection(record.direction, `${context}.direction`),
        value: parseNumber(record.value, `${context}.value`),
        unit: parseSignalUnit(record.unit, `${context}.unit`),
        confidence: parseNumber(record.confidence, `${context}.confidence`),
        as_of: parseString(record.as_of, `${context}.as_of`),
        ...(() => {
            const medianFilingAgeDays = parseNullableOptionalNumber(
                record.median_filing_age_days,
                `${context}.median_filing_age_days`
            );
            return typeof medianFilingAgeDays === 'number'
                ? { median_filing_age_days: medianFilingAgeDays }
                : {};
        })(),
        evidence: record.evidence.map((item, idx) =>
            parseForwardSignalEvidence(item, `${context}.evidence[${idx}]`)
        ),
    };
};

const parseStringArray = (value: unknown, context: string): string[] => {
    if (!Array.isArray(value) || !value.every((entry) => typeof entry === 'string')) {
        throw new TypeError(`${context} must be an array of strings.`);
    }
    return value;
};

const parseNumberArray = (value: unknown, context: string): number[] => {
    if (!Array.isArray(value) || !value.every((entry) => typeof entry === 'number')) {
        throw new TypeError(`${context} must be an array of numbers.`);
    }
    return value;
};

const parseSentimentLabel = (
    value: unknown,
    context: string
): SentimentLabel => {
    if (value === 'bullish' || value === 'bearish' || value === 'neutral') {
        return value;
    }
    throw new TypeError(`${context} must be bullish | bearish | neutral.`);
};

const parseImpactLevel = (value: unknown, context: string): ImpactLevel => {
    if (value === 'high' || value === 'medium' || value === 'low') {
        return value;
    }
    throw new TypeError(`${context} must be high | medium | low.`);
};

const parseSearchCategory = (value: unknown, context: string): SearchCategory => {
    if (
        value === 'general' ||
        value === 'corporate_event' ||
        value === 'financials' ||
        value === 'trusted_news' ||
        value === 'analyst_opinion' ||
        value === 'bullish' ||
        value === 'bearish'
    ) {
        return value;
    }
    throw new TypeError(`${context} has unsupported category value.`);
};

const parseSearchCategoryArray = (
    value: unknown,
    context: string
): SearchCategory[] => {
    if (!Array.isArray(value)) {
        throw new TypeError(`${context} must be an array.`);
    }
    return value.map((entry, idx) =>
        parseSearchCategory(entry, `${context}[${idx}]`)
    );
};

const parseSourceInfo = (value: unknown, context: string): SourceInfo => {
    const record = toRecord(value, context);
    const author = parseNullableOptionalString(record.author, `${context}.author`);

    const source: SourceInfo = {
        name: parseString(record.name, `${context}.name`),
        domain: parseString(record.domain, `${context}.domain`),
        reliability_score: parseNumber(
            record.reliability_score,
            `${context}.reliability_score`
        ),
    };
    if (author !== undefined) source.author = author;
    return source;
};

const parseFinancialEntity = (
    value: unknown,
    context: string
): FinancialEntity => {
    const record = toRecord(value, context);
    return {
        ticker: parseString(record.ticker, `${context}.ticker`),
        company_name: parseString(record.company_name, `${context}.company_name`),
        relevance_score: parseNumber(
            record.relevance_score,
            `${context}.relevance_score`
        ),
    };
};

const parseKeyFact = (value: unknown, context: string): KeyFact => {
    const record = toRecord(value, context);
    const citation = parseNullableOptionalString(
        record.citation,
        `${context}.citation`
    );
    const fact: KeyFact = {
        content: parseString(record.content, `${context}.content`),
        is_quantitative: parseBoolean(
            record.is_quantitative,
            `${context}.is_quantitative`
        ),
        sentiment: parseSentimentLabel(record.sentiment, `${context}.sentiment`),
    };
    if (citation !== undefined) fact.citation = citation;
    return fact;
};

const parseAIAnalysis = (
    value: unknown,
    context: string
): AIAnalysis | null | undefined => {
    if (value === undefined || value === null) return value;
    const record = toRecord(value, context);
    const keyEvent = parseNullableOptionalString(
        record.key_event,
        `${context}.key_event`
    );
    const analysis: AIAnalysis = {
        summary: parseString(record.summary, `${context}.summary`),
        sentiment: parseSentimentLabel(record.sentiment, `${context}.sentiment`),
        sentiment_score: parseNumber(
            record.sentiment_score,
            `${context}.sentiment_score`
        ),
        impact_level: parseImpactLevel(record.impact_level, `${context}.impact_level`),
        reasoning: parseString(record.reasoning, `${context}.reasoning`),
        key_facts: Array.isArray(record.key_facts)
            ? record.key_facts.map((fact, idx) =>
                  parseKeyFact(fact, `${context}.key_facts[${idx}]`)
              )
            : (() => {
                  throw new TypeError(`${context}.key_facts must be an array.`);
              })(),
    };
    if (keyEvent !== undefined) analysis.key_event = keyEvent;
    return analysis;
};

const parseNewsItem = (value: unknown, context: string): FinancialNewsItem => {
    const record = toRecord(value, context);
    const publishedAt = parseNullableOptionalString(
        record.published_at,
        `${context}.published_at`
    );
    const fullContent = parseNullableOptionalString(
        record.full_content,
        `${context}.full_content`
    );
    const analysis = parseAIAnalysis(record.analysis, `${context}.analysis`);

    const item: FinancialNewsItem = {
        id: parseString(record.id, `${context}.id`),
        url: parseString(record.url, `${context}.url`),
        fetched_at: parseString(record.fetched_at, `${context}.fetched_at`),
        title: parseString(record.title, `${context}.title`),
        snippet: parseString(record.snippet, `${context}.snippet`),
        source: parseSourceInfo(record.source, `${context}.source`),
        related_tickers: Array.isArray(record.related_tickers)
            ? record.related_tickers.map((entity, idx) =>
                  parseFinancialEntity(
                      entity,
                      `${context}.related_tickers[${idx}]`
                  )
              )
            : (() => {
                  throw new TypeError(
                      `${context}.related_tickers must be an array.`
                  );
              })(),
        categories: parseSearchCategoryArray(record.categories, `${context}.categories`),
        tags: parseStringArray(record.tags, `${context}.tags`),
    };
    if (publishedAt !== undefined) item.published_at = publishedAt;
    if (fullContent !== undefined) item.full_content = fullContent;
    if (analysis !== undefined) item.analysis = analysis;
    return item;
};

export const parseNewsArtifact = (
    value: unknown,
    context = 'news artifact'
): NewsResearchOutput => {
    const record = toRecord(value, context);
    if (!Array.isArray(record.news_items)) {
        throw new TypeError(`${context}.news_items must be an array.`);
    }
    return {
        ticker: parseString(record.ticker, `${context}.ticker`),
        news_items: record.news_items.map((item, idx) =>
            parseNewsItem(item, `${context}.news_items[${idx}]`)
        ),
        overall_sentiment: parseSentimentLabel(
            record.overall_sentiment,
            `${context}.overall_sentiment`
        ),
        sentiment_score: parseNumber(record.sentiment_score, `${context}.sentiment_score`),
        key_themes: parseStringArray(record.key_themes, `${context}.key_themes`),
    };
};

const parsePriceImplication = (
    value: unknown,
    context: string
): PriceImplication => {
    if (
        value === 'SURGE' ||
        value === 'MODERATE_UP' ||
        value === 'FLAT' ||
        value === 'MODERATE_DOWN' ||
        value === 'CRASH'
    ) {
        return value;
    }
    throw new TypeError(`${context} has unsupported price implication value.`);
};

const parseDirection = (value: unknown, context: string): Direction => {
    if (
        value === 'STRONG_LONG' ||
        value === 'LONG' ||
        value === 'NEUTRAL' ||
        value === 'AVOID' ||
        value === 'SHORT' ||
        value === 'STRONG_SHORT'
    ) {
        return value;
    }
    throw new TypeError(`${context} has unsupported direction value.`);
};

const parseRiskProfile = (value: unknown, context: string): RiskProfileType => {
    if (
        value === 'DEFENSIVE_VALUE' ||
        value === 'GROWTH_TECH' ||
        value === 'SPECULATIVE_CRYPTO_BIO'
    ) {
        return value;
    }
    throw new TypeError(`${context} has unsupported risk profile value.`);
};

const parseScenario = (value: unknown, context: string): Scenario => {
    const record = toRecord(value, context);
    return {
        probability: parseNumber(record.probability, `${context}.probability`),
        outcome_description: parseString(
            record.outcome_description,
            `${context}.outcome_description`
        ),
        price_implication: parsePriceImplication(
            record.price_implication,
            `${context}.price_implication`
        ),
    };
};

const parseDebateHistoryMessage = (
    value: unknown,
    context: string
): DebateHistoryMessage => {
    const record = toRecord(value, context);
    const name = parseNullableOptionalString(record.name, `${context}.name`);
    const role = parseNullableOptionalString(record.role, `${context}.role`);

    const item: DebateHistoryMessage = {
        content: parseString(record.content, `${context}.content`),
    };
    if (typeof name === 'string') item.name = name;
    if (typeof role === 'string') item.role = role;
    return item;
};

const parseEvidenceFact = (value: unknown, context: string): EvidenceFact => {
    const record = toRecord(value, context);
    const sourceType = record.source_type;
    const sourceWeight = record.source_weight;
    if (
        sourceType !== 'financials' &&
        sourceType !== 'news' &&
        sourceType !== 'technicals' &&
        sourceType !== 'valuation'
    ) {
        throw new TypeError(`${context}.source_type has unsupported value.`);
    }
    if (
        sourceWeight !== 'HIGH' &&
        sourceWeight !== 'MEDIUM' &&
        sourceWeight !== 'LOW'
    ) {
        throw new TypeError(`${context}.source_weight has unsupported value.`);
    }

    const valueField = record.value;
    if (
        valueField !== undefined &&
        valueField !== null &&
        typeof valueField !== 'string' &&
        typeof valueField !== 'number'
    ) {
        throw new TypeError(
            `${context}.value must be string | number | null | undefined.`
        );
    }

    const provenanceRaw = record.provenance;
    if (
        provenanceRaw !== undefined &&
        !isRecord(provenanceRaw) &&
        provenanceRaw !== null
    ) {
        throw new TypeError(`${context}.provenance must be an object | null | undefined.`);
    }

    const fact: EvidenceFact = {
        fact_id: parseString(record.fact_id, `${context}.fact_id`),
        source_type: sourceType,
        source_weight: sourceWeight,
        summary: parseString(record.summary, `${context}.summary`),
    };
    if (valueField !== undefined && valueField !== null) fact.value = valueField;
    const units = parseNullableOptionalString(record.units, `${context}.units`);
    if (typeof units === 'string') {
        fact.units = units;
    }
    const period = parseNullableOptionalString(record.period, `${context}.period`);
    if (typeof period === 'string') {
        fact.period = period;
    }
    if (provenanceRaw !== undefined && provenanceRaw !== null) {
        fact.provenance = provenanceRaw;
    }
    return fact;
};

export const parseDebateArtifact = (
    value: unknown,
    context = 'debate artifact'
): DebateSuccess => {
    const record = toRecord(value, context);
    const scenarioAnalysisRecord = toRecord(
        record.scenario_analysis,
        `${context}.scenario_analysis`
    );

    const historyRaw = record.history;
    const factsRaw = record.facts;
    const artifact: DebateSuccess = {
        scenario_analysis: {
            bull_case: parseScenario(
                scenarioAnalysisRecord.bull_case,
                `${context}.scenario_analysis.bull_case`
            ),
            bear_case: parseScenario(
                scenarioAnalysisRecord.bear_case,
                `${context}.scenario_analysis.bear_case`
            ),
            base_case: parseScenario(
                scenarioAnalysisRecord.base_case,
                `${context}.scenario_analysis.base_case`
            ),
        },
        risk_profile: parseRiskProfile(record.risk_profile, `${context}.risk_profile`),
        final_verdict: parseDirection(record.final_verdict, `${context}.final_verdict`),
        winning_thesis: parseString(record.winning_thesis, `${context}.winning_thesis`),
        primary_catalyst: parseString(
            record.primary_catalyst,
            `${context}.primary_catalyst`
        ),
        primary_risk: parseString(record.primary_risk, `${context}.primary_risk`),
        supporting_factors: parseStringArray(
            record.supporting_factors,
            `${context}.supporting_factors`
        ),
        debate_rounds: parseNumber(record.debate_rounds, `${context}.debate_rounds`),
    };

    const rrRatio = parseNullableOptionalNumber(record.rr_ratio, `${context}.rr_ratio`);
    if (rrRatio !== undefined) artifact.rr_ratio = rrRatio;
    const alpha = parseNullableOptionalNumber(record.alpha, `${context}.alpha`);
    if (alpha !== undefined) artifact.alpha = alpha;
    const riskFreeBenchmark = parseNullableOptionalNumber(
        record.risk_free_benchmark,
        `${context}.risk_free_benchmark`
    );
    if (riskFreeBenchmark !== undefined) {
        artifact.risk_free_benchmark = riskFreeBenchmark;
    }
    const rawEv = parseNullableOptionalNumber(record.raw_ev, `${context}.raw_ev`);
    if (rawEv !== undefined) artifact.raw_ev = rawEv;
    const conviction = parseNullableOptionalNumber(
        record.conviction,
        `${context}.conviction`
    );
    if (conviction !== undefined) artifact.conviction = conviction;
    const analysisBias = parseNullableOptionalString(
        record.analysis_bias,
        `${context}.analysis_bias`
    );
    if (typeof analysisBias === 'string') {
        artifact.analysis_bias = analysisBias;
    }
    const modelSummary = parseNullableOptionalString(
        record.model_summary,
        `${context}.model_summary`
    );
    if (typeof modelSummary === 'string') {
        artifact.model_summary = modelSummary;
    }
    const dataQualityWarning = parseNullableOptionalBoolean(
        record.data_quality_warning,
        `${context}.data_quality_warning`
    );
    if (dataQualityWarning !== undefined) {
        artifact.data_quality_warning = dataQualityWarning;
    }

    if (historyRaw !== undefined) {
        if (!Array.isArray(historyRaw)) {
            throw new TypeError(`${context}.history must be an array.`);
        }
        artifact.history = historyRaw.map((entry, idx) =>
            parseDebateHistoryMessage(entry, `${context}.history[${idx}]`)
        );
    }
    if (factsRaw !== undefined) {
        if (!Array.isArray(factsRaw)) {
            throw new TypeError(`${context}.facts must be an array.`);
        }
        artifact.facts = factsRaw.map((entry, idx) =>
            parseEvidenceFact(entry, `${context}.facts[${idx}]`)
        );
    }

    return artifact;
};

const parseRiskLevel = (value: unknown, context: string): RiskLevel => {
    if (
        value === RiskLevel.LOW ||
        value === RiskLevel.MEDIUM ||
        value === RiskLevel.CRITICAL
    ) {
        return value;
    }
    throw new TypeError(`${context} has unsupported risk level value.`);
};

const parseAlertSeverity = (value: unknown, context: string): AlertSeverity => {
    if (value === 'info' || value === 'warning' || value === 'critical') {
        return value;
    }
    throw new TypeError(`${context} must be info | warning | critical.`);
};

const parseTechnicalAlertSignal = (
    value: unknown,
    context: string
): TechnicalAlertSignal => {
    const record = toRecord(value, context);
    const metadata =
        record.metadata === undefined || record.metadata === null
            ? undefined
            : toRecord(record.metadata, `${context}.metadata`);
    const message = parseNullableOptionalString(record.message, `${context}.message`);
    const direction = parseNullableOptionalString(
        record.direction,
        `${context}.direction`
    );
    const triggeredAt = parseNullableOptionalString(
        record.triggered_at,
        `${context}.triggered_at`
    );
    const source = parseNullableOptionalString(record.source, `${context}.source`);
    const valueNum = parseNullableOptionalNumber(record.value, `${context}.value`);
    const thresholdNum = parseNullableOptionalNumber(
        record.threshold,
        `${context}.threshold`
    );
    const policy =
        record.policy === undefined || record.policy === null
            ? undefined
            : parseTechnicalAlertPolicy(record.policy, `${context}.policy`);

    const signal: TechnicalAlertSignal = {
        code: parseString(record.code, `${context}.code`),
        severity: parseAlertSeverity(record.severity, `${context}.severity`),
        timeframe: parseString(record.timeframe, `${context}.timeframe`),
        title: parseString(record.title, `${context}.title`),
    };

    if (message !== undefined) signal.message = message;
    if (valueNum !== undefined) signal.value = valueNum;
    if (thresholdNum !== undefined) signal.threshold = thresholdNum;
    if (direction !== undefined) signal.direction = direction;
    if (triggeredAt !== undefined) signal.triggered_at = triggeredAt;
    if (source !== undefined) signal.source = source;
    if (metadata !== undefined) signal.metadata = metadata;
    if (policy !== undefined) signal.policy = policy;

    return signal;
};

const parseTechnicalAlertPolicy = (
    value: unknown,
    context: string
): NonNullable<TechnicalAlertSignal['policy']> => {
    const record = toRecord(value, context);
    const policy: NonNullable<TechnicalAlertSignal['policy']> = {
        policy_code: parseString(record.policy_code, `${context}.policy_code`),
        policy_version: parseString(
            record.policy_version,
            `${context}.policy_version`
        ),
        lifecycle_state: parseString(
            record.lifecycle_state,
            `${context}.lifecycle_state`
        ),
    };
    const qualityGate = parseNullableOptionalString(
        record.quality_gate,
        `${context}.quality_gate`
    );
    const triggerReason = parseNullableOptionalString(
        record.trigger_reason,
        `${context}.trigger_reason`
    );
    const suppressionReason = parseNullableOptionalString(
        record.suppression_reason,
        `${context}.suppression_reason`
    );
    if (qualityGate !== undefined) policy.quality_gate = qualityGate ?? null;
    if (triggerReason !== undefined) policy.trigger_reason = triggerReason ?? null;
    if (suppressionReason !== undefined) {
        policy.suppression_reason = suppressionReason ?? null;
    }
    if (record.evidence_refs !== undefined && record.evidence_refs !== null) {
        if (!Array.isArray(record.evidence_refs)) {
            throw new TypeError(`${context}.evidence_refs must be an array.`);
        }
        policy.evidence_refs = record.evidence_refs.map((entry, index) => {
            const refRecord = toRecord(entry, `${context}.evidence_refs[${index}]`);
            const ref: NonNullable<
                NonNullable<TechnicalAlertSignal['policy']>['evidence_refs']
            >[number] = {
                artifact_kind: parseString(
                    refRecord.artifact_kind,
                    `${context}.evidence_refs[${index}].artifact_kind`
                ),
            };
            const artifactId = parseNullableOptionalString(
                refRecord.artifact_id,
                `${context}.evidence_refs[${index}].artifact_id`
            );
            const timeframe = parseNullableOptionalString(
                refRecord.timeframe,
                `${context}.evidence_refs[${index}].timeframe`
            );
            const signalKey = parseNullableOptionalString(
                refRecord.signal_key,
                `${context}.evidence_refs[${index}].signal_key`
            );
            if (artifactId !== undefined) ref.artifact_id = artifactId ?? null;
            if (timeframe !== undefined) ref.timeframe = timeframe ?? null;
            if (signalKey !== undefined) ref.signal_key = signalKey ?? null;
            return ref;
        });
    }
    return policy;
};

const parseTechnicalAlertSummary = (
    value: unknown,
    context: string
): TechnicalAlertSummary => {
    const record = toRecord(value, context);
    const total = parseNullableOptionalNumber(record.total, `${context}.total`);
    const generatedAt = parseNullableOptionalString(
        record.generated_at,
        `${context}.generated_at`
    );
    const policyCount = parseNullableOptionalNumber(
        record.policy_count,
        `${context}.policy_count`
    );
    const severityCountsRecord =
        record.severity_counts === undefined || record.severity_counts === null
            ? undefined
            : toRecord(record.severity_counts, `${context}.severity_counts`);
    const lifecycleCountsRecord =
        record.lifecycle_counts === undefined || record.lifecycle_counts === null
            ? undefined
            : toRecord(record.lifecycle_counts, `${context}.lifecycle_counts`);
    const qualityGateCountsRecord =
        record.quality_gate_counts === undefined || record.quality_gate_counts === null
            ? undefined
            : toRecord(record.quality_gate_counts, `${context}.quality_gate_counts`);
    const severityCounts: Record<string, number> = {};
    const lifecycleCounts: Record<string, number> = {};
    const qualityGateCounts: Record<string, number> = {};
    if (severityCountsRecord) {
        for (const [key, entry] of Object.entries(severityCountsRecord)) {
            severityCounts[key] = parseNumber(
                entry,
                `${context}.severity_counts.${key}`
            );
        }
    }
    if (lifecycleCountsRecord) {
        for (const [key, entry] of Object.entries(lifecycleCountsRecord)) {
            lifecycleCounts[key] = parseNumber(
                entry,
                `${context}.lifecycle_counts.${key}`
            );
        }
    }
    if (qualityGateCountsRecord) {
        for (const [key, entry] of Object.entries(qualityGateCountsRecord)) {
            qualityGateCounts[key] = parseNumber(
                entry,
                `${context}.quality_gate_counts.${key}`
            );
        }
    }

    const summary: TechnicalAlertSummary = {};
    if (total !== undefined) summary.total = total;
    if (generatedAt !== undefined) summary.generated_at = generatedAt;
    if (policyCount !== undefined) summary.policy_count = policyCount;
    if (Object.keys(severityCounts).length > 0) {
        summary.severity_counts = severityCounts;
    }
    if (Object.keys(lifecycleCounts).length > 0) {
        summary.lifecycle_counts = lifecycleCounts;
    }
    if (Object.keys(qualityGateCounts).length > 0) {
        summary.quality_gate_counts = qualityGateCounts;
    }
    return summary;
};

const parseTechnicalFeatureIndicator = (
    value: unknown,
    context: string
): TechnicalFeatureIndicator => {
    const record = toRecord(value, context);
    const metadata =
        record.metadata === undefined || record.metadata === null
            ? undefined
            : toRecord(record.metadata, `${context}.metadata`);
    const state = parseNullableOptionalString(record.state, `${context}.state`);
    const rawValue = record.value;
    let parsedValue: number | null = null;
    if (rawValue === null) {
        parsedValue = null;
    } else if (rawValue !== undefined) {
        parsedValue = parseNumber(rawValue, `${context}.value`);
    }

    const indicator: TechnicalFeatureIndicator = {
        name: parseString(record.name, `${context}.name`),
        value: parsedValue,
    };
    if (typeof state === 'string') {
        indicator.state = state;
    }
    if (record.provenance !== undefined && record.provenance !== null) {
        const provenance = toRecord(record.provenance, `${context}.provenance`);
        indicator.provenance = {
            method: parseNullableOptionalString(provenance.method, `${context}.provenance.method`) ?? undefined,
            input_basis:
                parseNullableOptionalString(
                    provenance.input_basis,
                    `${context}.provenance.input_basis`
                ) ?? undefined,
            source_timeframe:
                parseNullableOptionalString(
                    provenance.source_timeframe,
                    `${context}.provenance.source_timeframe`
                ) ?? undefined,
            calculation_version:
                parseNullableOptionalString(
                    provenance.calculation_version,
                    `${context}.provenance.calculation_version`
                ) ?? undefined,
        };
    }
    if (record.quality !== undefined && record.quality !== null) {
        const quality = toRecord(record.quality, `${context}.quality`);
        indicator.quality = {
            effective_sample_count:
                quality.effective_sample_count === undefined ||
                quality.effective_sample_count === null
                    ? undefined
                    : parseNumber(
                          quality.effective_sample_count,
                          `${context}.quality.effective_sample_count`
                      ),
            minimum_samples:
                quality.minimum_samples === undefined || quality.minimum_samples === null
                    ? undefined
                    : parseNumber(
                          quality.minimum_samples,
                          `${context}.quality.minimum_samples`
                      ),
            warmup_status:
                parseNullableOptionalString(
                    quality.warmup_status,
                    `${context}.quality.warmup_status`
                ) ?? undefined,
            fidelity:
                parseNullableOptionalString(
                    quality.fidelity,
                    `${context}.quality.fidelity`
                ) ?? undefined,
            quality_flags:
                quality.quality_flags === undefined || quality.quality_flags === null
                    ? undefined
                    : parseStringArray(
                          quality.quality_flags,
                          `${context}.quality.quality_flags`
                      ),
        };
    }
    if (metadata) {
        indicator.metadata = metadata;
    }
    return indicator;
};

const parseTechnicalFeatureFrame = (
    value: unknown,
    context: string
): TechnicalFeatureFrame => {
    const record = toRecord(value, context);
    const classic = toRecord(record.classic_indicators, `${context}.classic_indicators`);
    const quant = toRecord(record.quant_features, `${context}.quant_features`);

    const classicIndicators: TechnicalFeatureFrame['classic_indicators'] = {};
    for (const [key, entry] of Object.entries(classic)) {
        classicIndicators[key] = parseTechnicalFeatureIndicator(
            entry,
            `${context}.classic_indicators.${key}`
        );
    }

    const quantFeatures: TechnicalFeatureFrame['quant_features'] = {};
    for (const [key, entry] of Object.entries(quant)) {
        quantFeatures[key] = parseTechnicalFeatureIndicator(
            entry,
            `${context}.quant_features.${key}`
        );
    }

    return {
        classic_indicators: classicIndicators,
        quant_features: quantFeatures,
    };
};

export const parseTechnicalFeaturePackArtifact = (
    value: unknown,
    context = 'technical feature pack'
): TechnicalFeaturePack => {
    const record = toRecord(value, context);
    const timeframes = toRecord(record.timeframes, `${context}.timeframes`);
    const parsedTimeframes: TechnicalFeaturePack['timeframes'] = {};
    for (const [key, frame] of Object.entries(timeframes)) {
        parsedTimeframes[key] = parseTechnicalFeatureFrame(
            frame,
            `${context}.timeframes.${key}`
        );
    }

    const featureSummary =
        record.feature_summary === undefined || record.feature_summary === null
            ? undefined
            : toRecord(record.feature_summary, `${context}.feature_summary`);
    const degradedReasons =
        record.degraded_reasons === undefined || record.degraded_reasons === null
            ? undefined
            : parseStringArray(
                  record.degraded_reasons,
                  `${context}.degraded_reasons`
              );

    const pack: TechnicalFeaturePack = {
        ticker: parseString(record.ticker, `${context}.ticker`),
        as_of: parseString(record.as_of, `${context}.as_of`),
        timeframes: parsedTimeframes,
    };
    if (featureSummary) {
        pack.feature_summary = {
            classic_count: parseNumber(
                featureSummary.classic_count ?? 0,
                `${context}.feature_summary.classic_count`
            ),
            quant_count: parseNumber(
                featureSummary.quant_count ?? 0,
                `${context}.feature_summary.quant_count`
            ),
            timeframe_count: parseNumber(
                featureSummary.timeframe_count ?? 0,
                `${context}.feature_summary.timeframe_count`
            ),
            ready_timeframes:
                featureSummary.ready_timeframes === undefined ||
                featureSummary.ready_timeframes === null
                    ? undefined
                    : parseStringArray(
                          featureSummary.ready_timeframes,
                          `${context}.feature_summary.ready_timeframes`
                      ),
            degraded_timeframes:
                featureSummary.degraded_timeframes === undefined ||
                featureSummary.degraded_timeframes === null
                    ? undefined
                    : parseStringArray(
                          featureSummary.degraded_timeframes,
                          `${context}.feature_summary.degraded_timeframes`
                      ),
            regime_inputs_ready_timeframes:
                featureSummary.regime_inputs_ready_timeframes === undefined ||
                featureSummary.regime_inputs_ready_timeframes === null
                    ? undefined
                    : parseStringArray(
                          featureSummary.regime_inputs_ready_timeframes,
                          `${context}.feature_summary.regime_inputs_ready_timeframes`
                      ),
            unavailable_indicator_count:
                featureSummary.unavailable_indicator_count === undefined ||
                featureSummary.unavailable_indicator_count === null
                    ? undefined
                    : parseNumber(
                          featureSummary.unavailable_indicator_count,
                          `${context}.feature_summary.unavailable_indicator_count`
                      ),
            overall_quality:
                parseNullableOptionalString(
                    featureSummary.overall_quality,
                    `${context}.feature_summary.overall_quality`
                ) ?? undefined,
        };
    }
    if (degradedReasons) {
        pack.degraded_reasons = degradedReasons;
    }
    return pack;
};

const parseTechnicalPatternLevel = (
    value: unknown,
    context: string
): TechnicalPatternLevel => {
    const record = toRecord(value, context);
    const strength = parseNullableOptionalNumber(
        record.strength,
        `${context}.strength`
    );
    const touches = parseNullableOptionalNumber(
        record.touches,
        `${context}.touches`
    );
    const label = parseNullableOptionalString(record.label, `${context}.label`);
    return {
        price: parseNumber(record.price, `${context}.price`),
        strength: strength ?? null,
        touches: touches ?? null,
        label: label ?? null,
    };
};

const parseTechnicalPatternFlag = (
    value: unknown,
    context: string
): TechnicalPatternFlag => {
    const record = toRecord(value, context);
    const confidence = parseNullableOptionalNumber(
        record.confidence,
        `${context}.confidence`
    );
    const notes = parseNullableOptionalString(record.notes, `${context}.notes`);
    return {
        name: parseString(record.name, `${context}.name`),
        confidence: confidence ?? null,
        notes: notes ?? null,
    };
};

const parseTechnicalPatternFrame = (
    value: unknown,
    context: string
): TechnicalPatternFrame => {
    const record = toRecord(value, context);
    const supportLevels = Array.isArray(record.support_levels)
        ? record.support_levels.map((entry, idx) =>
              parseTechnicalPatternLevel(
                  entry,
                  `${context}.support_levels[${idx}]`
              )
          )
        : (() => {
              throw new TypeError(`${context}.support_levels must be an array.`);
          })();
    const resistanceLevels = Array.isArray(record.resistance_levels)
        ? record.resistance_levels.map((entry, idx) =>
              parseTechnicalPatternLevel(
                  entry,
                  `${context}.resistance_levels[${idx}]`
              )
          )
        : (() => {
              throw new TypeError(`${context}.resistance_levels must be an array.`);
          })();
    const volumeProfileLevels = Array.isArray(record.volume_profile_levels)
        ? record.volume_profile_levels.map((entry, idx) =>
              parseTechnicalPatternLevel(
                  entry,
                  `${context}.volume_profile_levels[${idx}]`
              )
          )
        : [];
    const breakouts = Array.isArray(record.breakouts)
        ? record.breakouts.map((entry, idx) =>
              parseTechnicalPatternFlag(entry, `${context}.breakouts[${idx}]`)
          )
        : (() => {
              throw new TypeError(`${context}.breakouts must be an array.`);
          })();
    const trendlines = Array.isArray(record.trendlines)
        ? record.trendlines.map((entry, idx) =>
              parseTechnicalPatternFlag(entry, `${context}.trendlines[${idx}]`)
          )
        : (() => {
              throw new TypeError(`${context}.trendlines must be an array.`);
          })();
    const patternFlags = Array.isArray(record.pattern_flags)
        ? record.pattern_flags.map((entry, idx) =>
              parseTechnicalPatternFlag(entry, `${context}.pattern_flags[${idx}]`)
          )
        : (() => {
              throw new TypeError(`${context}.pattern_flags must be an array.`);
          })();

    const confidenceScoresRecord =
        record.confidence_scores === undefined || record.confidence_scores === null
            ? undefined
            : toRecord(record.confidence_scores, `${context}.confidence_scores`);
    const confidenceScores: Record<string, number> = {};
    if (confidenceScoresRecord) {
        for (const [key, entry] of Object.entries(confidenceScoresRecord)) {
            confidenceScores[key] = parseNumber(
                entry,
                `${context}.confidence_scores.${key}`
            );
        }
    }
    const volumeProfileSummary =
        record.volume_profile_summary === undefined ||
        record.volume_profile_summary === null
            ? undefined
            : parseVolumeProfileSummary(
                  record.volume_profile_summary,
                  `${context}.volume_profile_summary`
              );
    const confluenceMetadata = parseStructureConfluenceSummary(
        record.confluence_metadata,
        `${context}.confluence_metadata`
    );

    const frame: TechnicalPatternFrame = {
        support_levels: supportLevels,
        resistance_levels: resistanceLevels,
        volume_profile_levels: volumeProfileLevels,
        breakouts,
        trendlines,
        pattern_flags: patternFlags,
        confidence_scores: confidenceScores,
    };
    if (volumeProfileSummary) {
        frame.volume_profile_summary = volumeProfileSummary;
    }
    if (confluenceMetadata) {
        frame.confluence_metadata = confluenceMetadata;
    }
    return frame;
};

export const parseTechnicalPatternPackArtifact = (
    value: unknown,
    context = 'technical pattern pack'
): TechnicalPatternPack => {
    const record = toRecord(value, context);
    const timeframes = toRecord(record.timeframes, `${context}.timeframes`);
    const parsedTimeframes: TechnicalPatternPack['timeframes'] = {};
    for (const [key, frame] of Object.entries(timeframes)) {
        parsedTimeframes[key] = parseTechnicalPatternFrame(
            frame,
            `${context}.timeframes.${key}`
        );
    }

    const patternSummary = parsePatternSummary(
        record.pattern_summary,
        `${context}.pattern_summary`
    );
    const degradedReasons =
        record.degraded_reasons === undefined || record.degraded_reasons === null
            ? undefined
            : parseStringArray(
                  record.degraded_reasons,
                  `${context}.degraded_reasons`
              );

    const pack: TechnicalPatternPack = {
        ticker: parseString(record.ticker, `${context}.ticker`),
        as_of: parseString(record.as_of, `${context}.as_of`),
        timeframes: parsedTimeframes,
    };
    if (patternSummary) {
        pack.pattern_summary = patternSummary;
    }
    if (degradedReasons) {
        pack.degraded_reasons = degradedReasons;
    }
    return pack;
};

export const parseTechnicalAlertsArtifact = (
    value: unknown,
    context = 'technical alerts'
): TechnicalAlertsArtifact => {
    const record = toRecord(value, context);
    if (!Array.isArray(record.alerts)) {
        throw new TypeError(`${context}.alerts must be an array.`);
    }
    const alerts = record.alerts.map((entry, idx) =>
        parseTechnicalAlertSignal(entry, `${context}.alerts[${idx}]`)
    );
    const summaryRecord =
        record.summary === undefined || record.summary === null
            ? undefined
            : parseTechnicalAlertSummary(record.summary, `${context}.summary`);
    const degradedReasons =
        record.degraded_reasons === undefined || record.degraded_reasons === null
            ? undefined
            : parseStringArray(
                  record.degraded_reasons,
                  `${context}.degraded_reasons`
              );
    const sourceArtifactsRecord =
        record.source_artifacts === undefined || record.source_artifacts === null
            ? undefined
            : toRecord(record.source_artifacts, `${context}.source_artifacts`);
    const sourceArtifacts: Record<string, string | null> = {};
    if (sourceArtifactsRecord) {
        for (const [key, entry] of Object.entries(sourceArtifactsRecord)) {
            if (entry === null) {
                sourceArtifacts[key] = null;
            } else {
                sourceArtifacts[key] = parseString(
                    entry,
                    `${context}.source_artifacts.${key}`
                );
            }
        }
    }

    const artifact: TechnicalAlertsArtifact = {
        ticker: parseString(record.ticker, `${context}.ticker`),
        as_of: parseString(record.as_of, `${context}.as_of`),
        alerts,
    };
    if (summaryRecord && Object.keys(summaryRecord).length > 0) {
        artifact.summary = summaryRecord;
    }
    if (degradedReasons) {
        artifact.degraded_reasons = degradedReasons;
    }
    if (Object.keys(sourceArtifacts).length > 0) {
        artifact.source_artifacts = sourceArtifacts;
    }
    return artifact;
};

export const parseTechnicalFusionReportArtifact = (
    value: unknown,
    context = 'technical fusion report'
): TechnicalFusionReport => {
    const record = toRecord(value, context);
    const confidence = parseNullableOptionalNumber(
        record.confidence,
        `${context}.confidence`
    );
    const confidenceRaw = parseNullableOptionalNumber(
        record.confidence_raw,
        `${context}.confidence_raw`
    );
    const confidenceCalibrated = parseNullableOptionalNumber(
        record.confidence_calibrated,
        `${context}.confidence_calibrated`
    );
    const signalStrengthRaw = parseNullableOptionalNumber(
        record.signal_strength_raw,
        `${context}.signal_strength_raw`
    );
    const signalStrengthEffective = parseNullableOptionalNumber(
        record.signal_strength_effective,
        `${context}.signal_strength_effective`
    );
    const confidenceCalibration = parseConfidenceCalibration(
        record.confidence_calibration,
        `${context}.confidence_calibration`
    );
    const confidenceEligibility = parseConfidenceEligibility(
        record.confidence_eligibility,
        `${context}.confidence_eligibility`
    );
    const confluenceMatrixRecord =
        record.confluence_matrix === undefined || record.confluence_matrix === null
            ? undefined
            : toRecord(record.confluence_matrix, `${context}.confluence_matrix`);
    const confluenceMatrix: Record<string, Record<string, unknown>> = {};
    if (confluenceMatrixRecord) {
        for (const [key, entry] of Object.entries(confluenceMatrixRecord)) {
            confluenceMatrix[key] = toRecord(
                entry,
                `${context}.confluence_matrix.${key}`
            );
        }
    }

    const conflictReasons =
        record.conflict_reasons === undefined || record.conflict_reasons === null
            ? undefined
            : parseStringArray(
                  record.conflict_reasons,
                  `${context}.conflict_reasons`
              );

    const alignmentReport = parseAlignmentReport(
        record.alignment_report,
        `${context}.alignment_report`
    );
    const regimeSummary = parseRegimeSummary(
        record.regime_summary,
        `${context}.regime_summary`
    );

    const sourceArtifactsRecord =
        record.source_artifacts === undefined || record.source_artifacts === null
            ? undefined
            : toRecord(record.source_artifacts, `${context}.source_artifacts`);
    const sourceArtifacts: Record<string, string | null> = {};
    if (sourceArtifactsRecord) {
        for (const [key, entry] of Object.entries(sourceArtifactsRecord)) {
            if (entry === null) {
                sourceArtifacts[key] = null;
            } else {
                sourceArtifacts[key] = parseString(
                    entry,
                    `${context}.source_artifacts.${key}`
                );
            }
        }
    }

    const degradedReasons =
        record.degraded_reasons === undefined || record.degraded_reasons === null
            ? undefined
            : parseStringArray(
                  record.degraded_reasons,
                  `${context}.degraded_reasons`
              );

    const report: TechnicalFusionReport = {
        schema_version: parseString(record.schema_version, `${context}.schema_version`),
        ticker: parseString(record.ticker, `${context}.ticker`),
        as_of: parseString(record.as_of, `${context}.as_of`),
        direction: parseString(record.direction, `${context}.direction`),
        risk_level: parseRiskLevel(record.risk_level, `${context}.risk_level`),
    };
    if (confidence !== undefined) report.confidence = confidence;
    if (confidenceRaw !== undefined) report.confidence_raw = confidenceRaw;
    if (confidenceCalibrated !== undefined) {
        report.confidence_calibrated = confidenceCalibrated;
    }
    if (signalStrengthRaw !== undefined) {
        report.signal_strength_raw = signalStrengthRaw;
    }
    if (signalStrengthEffective !== undefined) {
        report.signal_strength_effective = signalStrengthEffective;
    }
    if (confidenceCalibration) {
        report.confidence_calibration = confidenceCalibration;
    }
    if (confidenceEligibility) {
        report.confidence_eligibility = confidenceEligibility;
    }
    if (regimeSummary) {
        report.regime_summary = regimeSummary;
    }
    if (Object.keys(confluenceMatrix).length > 0) {
        report.confluence_matrix = confluenceMatrix;
    }
    if (conflictReasons) report.conflict_reasons = conflictReasons;
    if (alignmentReport) report.alignment_report = alignmentReport;
    if (Object.keys(sourceArtifacts).length > 0) {
        report.source_artifacts = sourceArtifacts;
    }
    if (degradedReasons) report.degraded_reasons = degradedReasons;
    return report;
};

const parseScorecardContribution = (
    value: unknown,
    context: string
): TechnicalScorecardContribution => {
    const record = toRecord(value, context);
    const valueField = parseNullableOptionalNumber(record.value, `${context}.value`);
    const state = parseNullableOptionalString(record.state, `${context}.state`);
    const weight = parseNullableOptionalNumber(record.weight, `${context}.weight`);
    const notes = parseNullableOptionalString(record.notes, `${context}.notes`);
    const contribution = parseNumber(record.contribution, `${context}.contribution`);
    const result: TechnicalScorecardContribution = {
        name: parseString(record.name, `${context}.name`),
        value: valueField ?? null,
        contribution,
    };
    if (state !== undefined) result.state = state;
    if (weight !== undefined) result.weight = weight;
    if (notes !== undefined) result.notes = notes;
    return result;
};

const parseScorecardFrame = (
    value: unknown,
    context: string
): TechnicalScorecardFrame => {
    const record = toRecord(value, context);
    const contributionsRecord = toRecord(
        record.contributions,
        `${context}.contributions`
    );
    const contributions: Record<string, TechnicalScorecardContribution[]> = {};
    for (const [key, entry] of Object.entries(contributionsRecord)) {
        if (!Array.isArray(entry)) {
            throw new TypeError(`${context}.contributions.${key} must be an array.`);
        }
        contributions[key] = entry.map((item, idx) =>
            parseScorecardContribution(
                item,
                `${context}.contributions.${key}[${idx}]`
            )
        );
    }

    return {
        timeframe: parseString(record.timeframe, `${context}.timeframe`),
        classic_score: parseNumber(record.classic_score, `${context}.classic_score`),
        quant_score: parseNumber(record.quant_score, `${context}.quant_score`),
        pattern_score: parseNumber(record.pattern_score, `${context}.pattern_score`),
        total_score: parseNumber(record.total_score, `${context}.total_score`),
        classic_label: parseString(record.classic_label, `${context}.classic_label`),
        quant_label: parseString(record.quant_label, `${context}.quant_label`),
        pattern_label: parseString(record.pattern_label, `${context}.pattern_label`),
        contributions,
    };
};

export const parseTechnicalDirectionScorecardArtifact = (
    value: unknown,
    context = 'technical direction scorecard'
): TechnicalDirectionScorecard => {
    const record = toRecord(value, context);
    const confidence = parseNullableOptionalNumber(
        record.confidence,
        `${context}.confidence`
    );
    const modelVersion = parseNullableOptionalString(
        record.model_version,
        `${context}.model_version`
    );
    const conflictReasons =
        record.conflict_reasons === undefined || record.conflict_reasons === null
            ? undefined
            : parseStringArray(
                  record.conflict_reasons,
                  `${context}.conflict_reasons`
              );
    const degradedReasons =
        record.degraded_reasons === undefined || record.degraded_reasons === null
            ? undefined
            : parseStringArray(
                  record.degraded_reasons,
                  `${context}.degraded_reasons`
              );
    const sourceArtifactsRecord =
        record.source_artifacts === undefined || record.source_artifacts === null
            ? undefined
            : toRecord(record.source_artifacts, `${context}.source_artifacts`);
    const sourceArtifacts: Record<string, string | null> = {};
    if (sourceArtifactsRecord) {
        for (const [key, entry] of Object.entries(sourceArtifactsRecord)) {
            if (entry === null) {
                sourceArtifacts[key] = null;
            } else {
                sourceArtifacts[key] = parseString(
                    entry,
                    `${context}.source_artifacts.${key}`
                );
            }
        }
    }

    const timeframesRecord = toRecord(record.timeframes, `${context}.timeframes`);
    const timeframes: Record<string, TechnicalScorecardFrame> = {};
    for (const [key, frame] of Object.entries(timeframesRecord)) {
        timeframes[key] = parseScorecardFrame(
            frame,
            `${context}.timeframes.${key}`
        );
    }

    const scorecard: TechnicalDirectionScorecard = {
        schema_version: parseString(record.schema_version, `${context}.schema_version`),
        ticker: parseString(record.ticker, `${context}.ticker`),
        as_of: parseString(record.as_of, `${context}.as_of`),
        direction: parseString(record.direction, `${context}.direction`),
        risk_level: parseRiskLevel(record.risk_level, `${context}.risk_level`),
        neutral_threshold: parseNumber(
            record.neutral_threshold,
            `${context}.neutral_threshold`
        ),
        overall_score: parseNumber(record.overall_score, `${context}.overall_score`),
        timeframes,
    };

    if (confidence !== undefined) scorecard.confidence = confidence;
    if (modelVersion !== undefined) scorecard.model_version = modelVersion;
    if (conflictReasons) scorecard.conflict_reasons = conflictReasons;
    if (degradedReasons) scorecard.degraded_reasons = degradedReasons;
    if (Object.keys(sourceArtifacts).length > 0) {
        scorecard.source_artifacts = sourceArtifacts;
    }
    return scorecard;
};

export const parseTechnicalVerificationReportArtifact = (
    value: unknown,
    context = 'technical verification report'
): TechnicalVerificationReport => {
    const record = toRecord(value, context);
    const backtestSummaryRecord =
        record.backtest_summary === undefined || record.backtest_summary === null
            ? undefined
            : toRecord(record.backtest_summary, `${context}.backtest_summary`);
    const wfaSummaryRecord =
        record.wfa_summary === undefined || record.wfa_summary === null
            ? undefined
            : toRecord(record.wfa_summary, `${context}.wfa_summary`);

    const baselineGates =
        record.baseline_gates === undefined || record.baseline_gates === null
            ? undefined
            : toRecord(record.baseline_gates, `${context}.baseline_gates`);

    const robustnessFlags =
        record.robustness_flags === undefined || record.robustness_flags === null
            ? undefined
            : parseStringArray(
                  record.robustness_flags,
                  `${context}.robustness_flags`
              );

    const sourceArtifactsRecord =
        record.source_artifacts === undefined || record.source_artifacts === null
            ? undefined
            : toRecord(record.source_artifacts, `${context}.source_artifacts`);
    const sourceArtifacts: Record<string, string | null> = {};
    if (sourceArtifactsRecord) {
        for (const [key, entry] of Object.entries(sourceArtifactsRecord)) {
            if (entry === null) {
                sourceArtifacts[key] = null;
            } else {
                sourceArtifacts[key] = parseString(
                    entry,
                    `${context}.source_artifacts.${key}`
                );
            }
        }
    }

    const degradedReasons =
        record.degraded_reasons === undefined || record.degraded_reasons === null
            ? undefined
            : parseStringArray(
                  record.degraded_reasons,
                  `${context}.degraded_reasons`
              );

    const report: TechnicalVerificationReport = {
        schema_version: parseString(record.schema_version, `${context}.schema_version`),
        ticker: parseString(record.ticker, `${context}.ticker`),
        as_of: parseString(record.as_of, `${context}.as_of`),
    };

    if (backtestSummaryRecord) {
        report.backtest_summary = {
            strategy_name: parseNullableOptionalString(
                backtestSummaryRecord.strategy_name,
                `${context}.backtest_summary.strategy_name`
            ) ?? null,
            win_rate: parseNullableOptionalNumber(
                backtestSummaryRecord.win_rate,
                `${context}.backtest_summary.win_rate`
            ) ?? null,
            profit_factor: parseNullableOptionalNumber(
                backtestSummaryRecord.profit_factor,
                `${context}.backtest_summary.profit_factor`
            ) ?? null,
            sharpe_ratio: parseNullableOptionalNumber(
                backtestSummaryRecord.sharpe_ratio,
                `${context}.backtest_summary.sharpe_ratio`
            ) ?? null,
            max_drawdown: parseNullableOptionalNumber(
                backtestSummaryRecord.max_drawdown,
                `${context}.backtest_summary.max_drawdown`
            ) ?? null,
            total_trades: parseNullableOptionalNumber(
                backtestSummaryRecord.total_trades,
                `${context}.backtest_summary.total_trades`
            ) ?? null,
        };
    }

    if (wfaSummaryRecord) {
        report.wfa_summary = {
            wfa_sharpe: parseNullableOptionalNumber(
                wfaSummaryRecord.wfa_sharpe,
                `${context}.wfa_summary.wfa_sharpe`
            ) ?? null,
            wfe_ratio: parseNullableOptionalNumber(
                wfaSummaryRecord.wfe_ratio,
                `${context}.wfa_summary.wfe_ratio`
            ) ?? null,
            wfa_max_drawdown: parseNullableOptionalNumber(
                wfaSummaryRecord.wfa_max_drawdown,
                `${context}.wfa_summary.wfa_max_drawdown`
            ) ?? null,
            period_count: parseNullableOptionalNumber(
                wfaSummaryRecord.period_count,
                `${context}.wfa_summary.period_count`
            ) ?? null,
        };
    }

    if (baselineGates) report.baseline_gates = baselineGates;
    if (robustnessFlags) report.robustness_flags = robustnessFlags;
    if (Object.keys(sourceArtifacts).length > 0) {
        report.source_artifacts = sourceArtifacts;
    }
    if (degradedReasons) report.degraded_reasons = degradedReasons;
    return report;
};

const parseTechnicalArtifactRefs = (
    value: unknown,
    context: string
): TechnicalArtifactRefs => {
    const record = toRecord(value, context);
    const chartDataId = parseNullableOptionalString(
        record.chart_data_id,
        `${context}.chart_data_id`
    );
    const timeseriesBundleId = parseNullableOptionalString(
        record.timeseries_bundle_id,
        `${context}.timeseries_bundle_id`
    );
    const indicatorSeriesId = parseNullableOptionalString(
        record.indicator_series_id,
        `${context}.indicator_series_id`
    );
    const featurePackId = parseNullableOptionalString(
        record.feature_pack_id,
        `${context}.feature_pack_id`
    );
    const patternPackId = parseNullableOptionalString(
        record.pattern_pack_id,
        `${context}.pattern_pack_id`
    );
    const regimePackId = parseNullableOptionalString(
        record.regime_pack_id,
        `${context}.regime_pack_id`
    );
    const alertsId = parseNullableOptionalString(
        record.alerts_id,
        `${context}.alerts_id`
    );
    const fusionReportId = parseNullableOptionalString(
        record.fusion_report_id,
        `${context}.fusion_report_id`
    );
    const directionScorecardId = parseNullableOptionalString(
        record.direction_scorecard_id,
        `${context}.direction_scorecard_id`
    );
    const verificationReportId = parseNullableOptionalString(
        record.verification_report_id,
        `${context}.verification_report_id`
    );

    const refs: TechnicalArtifactRefs = {};
    if (typeof chartDataId === 'string') {
        refs.chart_data_id = chartDataId;
    }
    if (typeof timeseriesBundleId === 'string') {
        refs.timeseries_bundle_id = timeseriesBundleId;
    }
    if (typeof indicatorSeriesId === 'string') {
        refs.indicator_series_id = indicatorSeriesId;
    }
    if (typeof featurePackId === 'string') {
        refs.feature_pack_id = featurePackId;
    }
    if (typeof patternPackId === 'string') {
        refs.pattern_pack_id = patternPackId;
    }
    if (typeof regimePackId === 'string') {
        refs.regime_pack_id = regimePackId;
    }
    if (typeof alertsId === 'string') {
        refs.alerts_id = alertsId;
    }
    if (typeof fusionReportId === 'string') {
        refs.fusion_report_id = fusionReportId;
    }
    if (typeof directionScorecardId === 'string') {
        refs.direction_scorecard_id = directionScorecardId;
    }
    if (typeof verificationReportId === 'string') {
        refs.verification_report_id = verificationReportId;
    }
    return refs;
};

const parseTechnicalDiagnostics = (
    value: unknown,
    context: string
): TechnicalDiagnostics => {
    const record = toRecord(value, context);
    const isDegraded = parseNullableOptionalBoolean(
        record.is_degraded,
        `${context}.is_degraded`
    );
    const degradedReasons =
        record.degraded_reasons === undefined || record.degraded_reasons === null
            ? undefined
            : parseStringArray(
                  record.degraded_reasons,
                  `${context}.degraded_reasons`
              );

    const diagnostics: TechnicalDiagnostics = {};
    if (typeof isDegraded === 'boolean') {
        diagnostics.is_degraded = isDegraded;
    }
    if (degradedReasons !== undefined) {
        diagnostics.degraded_reasons = degradedReasons;
    }
    return diagnostics;
};

const parseSeriesMapNullable = (
    value: unknown,
    context: string
): Record<string, number | null> => {
    const record = toRecord(value, context);
    const parsed: Record<string, number | null> = {};
    for (const [key, seriesValue] of Object.entries(record)) {
        if (seriesValue === null) {
            parsed[key] = null;
            continue;
        }
        if (typeof seriesValue !== 'number') {
            throw new TypeError(`${context}.${key} must be a number or null.`);
        }
        parsed[key] = seriesValue;
    }
    return parsed;
};

const parseTechnicalTimeseriesFrame = (
    value: unknown,
    context: string
): TechnicalTimeseriesFrame => {
    const record = toRecord(value, context);
    const timezone = parseNullableOptionalString(
        record.timezone,
        `${context}.timezone`
    );
    const metadata = parseTechnicalTimeseriesFrameMetadata(
        record.metadata,
        `${context}.metadata`
    );

    const frame: TechnicalTimeseriesFrame = {
        timeframe: parseString(record.timeframe, `${context}.timeframe`),
        start: parseString(record.start, `${context}.start`),
        end: parseString(record.end, `${context}.end`),
        open_series: parseSeriesMapNullable(
            record.open_series,
            `${context}.open_series`
        ),
        high_series: parseSeriesMapNullable(
            record.high_series,
            `${context}.high_series`
        ),
        low_series: parseSeriesMapNullable(
            record.low_series,
            `${context}.low_series`
        ),
        close_series: parseSeriesMapNullable(
            record.close_series,
            `${context}.close_series`
        ),
        price_series: parseSeriesMapNullable(
            record.price_series,
            `${context}.price_series`
        ),
        volume_series: parseSeriesMapNullable(
            record.volume_series,
            `${context}.volume_series`
        ),
    };

    if (timezone !== undefined) {
        frame.timezone = timezone;
    }
    if (metadata !== undefined) {
        frame.metadata = metadata;
    }

    return frame;
};

const parseTechnicalTimeseriesFrameMetadata = (
    value: unknown,
    context: string
): TechnicalTimeseriesFrame['metadata'] | undefined => {
    if (value === undefined || value === null) return undefined;
    const record = toRecord(value, context);
    const metadata: NonNullable<TechnicalTimeseriesFrame['metadata']> = {
        row_count: parseNumber(record.row_count, `${context}.row_count`),
    };
    const source = parseNullableOptionalString(record.source, `${context}.source`);
    const sourceTimeframe = parseNullableOptionalString(
        record.source_timeframe,
        `${context}.source_timeframe`
    );
    const priceBasis = parseNullableOptionalString(
        record.price_basis,
        `${context}.price_basis`
    );
    const timezoneNormalized = parseNullableOptionalBoolean(
        record.timezone_normalized,
        `${context}.timezone_normalized`
    );
    const cacheHit = parseNullableOptionalBoolean(
        record.cache_hit,
        `${context}.cache_hit`
    );
    const cacheAgeSeconds = parseNullableOptionalNumber(
        record.cache_age_seconds,
        `${context}.cache_age_seconds`
    );
    const cacheBucket = parseNullableOptionalString(
        record.cache_bucket,
        `${context}.cache_bucket`
    );
    const qualityFlags =
        record.quality_flags === undefined || record.quality_flags === null
            ? undefined
            : parseStringArray(record.quality_flags, `${context}.quality_flags`);

    if (source !== undefined) metadata.source = source ?? undefined;
    if (sourceTimeframe !== undefined) {
        metadata.source_timeframe = sourceTimeframe ?? undefined;
    }
    if (priceBasis !== undefined) metadata.price_basis = priceBasis ?? undefined;
    if (timezoneNormalized !== undefined) {
        metadata.timezone_normalized = timezoneNormalized;
    }
    if (cacheHit !== undefined) metadata.cache_hit = cacheHit;
    if (cacheAgeSeconds !== undefined) metadata.cache_age_seconds = cacheAgeSeconds;
    if (cacheBucket !== undefined) metadata.cache_bucket = cacheBucket;
    if (qualityFlags !== undefined) metadata.quality_flags = qualityFlags;
    return metadata;
};

export const parseTechnicalTimeseriesBundleArtifact = (
    value: unknown,
    context = 'technical timeseries bundle'
): TechnicalTimeseriesBundle => {
    const record = toRecord(value, context);
    const frames = toRecord(record.frames, `${context}.frames`);
    const parsedFrames: TechnicalTimeseriesBundle['frames'] = {};
    for (const [key, frame] of Object.entries(frames)) {
        parsedFrames[key] = parseTechnicalTimeseriesFrame(
            frame,
            `${context}.frames.${key}`
        );
    }

    const degradedReasons =
        record.degraded_reasons === undefined || record.degraded_reasons === null
            ? undefined
            : parseStringArray(
                  record.degraded_reasons,
                  `${context}.degraded_reasons`
              );

    const bundle: TechnicalTimeseriesBundle = {
        ticker: parseString(record.ticker, `${context}.ticker`),
        as_of: parseString(record.as_of, `${context}.as_of`),
        frames: parsedFrames,
    };
    if (degradedReasons) {
        bundle.degraded_reasons = degradedReasons;
    }
    return bundle;
};

const parseIndicatorSeriesFrame = (
    value: unknown,
    context: string
): TechnicalIndicatorSeriesFrame => {
    const record = toRecord(value, context);
    const timezone = parseNullableOptionalString(
        record.timezone,
        `${context}.timezone`
    );
    const metadata = parseTechnicalIndicatorSeriesFrameMetadata(
        record.metadata,
        `${context}.metadata`
    );

    const seriesRecord = toRecord(record.series, `${context}.series`);
    const parsedSeries: TechnicalIndicatorSeriesFrame['series'] = {};
    for (const [seriesKey, seriesValue] of Object.entries(seriesRecord)) {
        parsedSeries[seriesKey] = parseSeriesMapNullable(
            seriesValue,
            `${context}.series.${seriesKey}`
        );
    }

    const frame: TechnicalIndicatorSeriesFrame = {
        timeframe: parseString(record.timeframe, `${context}.timeframe`),
        start: parseString(record.start, `${context}.start`),
        end: parseString(record.end, `${context}.end`),
        series: parsedSeries,
    };
    if (timezone !== undefined) {
        frame.timezone = timezone;
    }
    if (metadata !== undefined) {
        frame.metadata = metadata;
    }
    return frame;
};

const parseTechnicalIndicatorSeriesFrameMetadata = (
    value: unknown,
    context: string
): TechnicalIndicatorSeriesFrame['metadata'] | undefined => {
    if (value === undefined || value === null) return undefined;
    const record = toRecord(value, context);
    const metadata: NonNullable<TechnicalIndicatorSeriesFrame['metadata']> = {
        source_points: parseNumber(record.source_points, `${context}.source_points`),
        max_points: parseNumber(record.max_points, `${context}.max_points`),
        downsample_step: parseNumber(
            record.downsample_step,
            `${context}.downsample_step`
        ),
    };
    const sourceTimeframe = parseNullableOptionalString(
        record.source_timeframe,
        `${context}.source_timeframe`
    );
    const sourcePriceBasis = parseNullableOptionalString(
        record.source_price_basis,
        `${context}.source_price_basis`
    );
    const effectiveSampleCount = parseNullableOptionalNumber(
        record.effective_sample_count,
        `${context}.effective_sample_count`
    );
    const minimumSampleCount = parseNullableOptionalNumber(
        record.minimum_sample_count,
        `${context}.minimum_sample_count`
    );
    const sampleReadiness = parseNullableOptionalString(
        record.sample_readiness,
        `${context}.sample_readiness`
    );
    const fidelity = parseNullableOptionalString(
        record.fidelity,
        `${context}.fidelity`
    );
    const qualityFlags =
        record.quality_flags === undefined || record.quality_flags === null
            ? undefined
            : parseStringArray(record.quality_flags, `${context}.quality_flags`);

    if (sourceTimeframe !== undefined) {
        metadata.source_timeframe = sourceTimeframe ?? undefined;
    }
    if (sourcePriceBasis !== undefined) {
        metadata.source_price_basis = sourcePriceBasis ?? undefined;
    }
    if (effectiveSampleCount !== undefined) {
        metadata.effective_sample_count = effectiveSampleCount;
    }
    if (minimumSampleCount !== undefined) {
        metadata.minimum_sample_count = minimumSampleCount;
    }
    if (sampleReadiness !== undefined) {
        metadata.sample_readiness = sampleReadiness ?? undefined;
    }
    if (fidelity !== undefined) metadata.fidelity = fidelity ?? undefined;
    if (qualityFlags !== undefined) metadata.quality_flags = qualityFlags;
    return metadata;
};

export const parseTechnicalIndicatorSeriesArtifact = (
    value: unknown,
    context = 'technical indicator series'
): TechnicalIndicatorSeriesArtifact => {
    const record = toRecord(value, context);
    const timeframes = toRecord(record.timeframes, `${context}.timeframes`);
    const parsedFrames: TechnicalIndicatorSeriesArtifact['timeframes'] = {};
    for (const [key, frame] of Object.entries(timeframes)) {
        parsedFrames[key] = parseIndicatorSeriesFrame(
            frame,
            `${context}.timeframes.${key}`
        );
    }

    const degradedReasons =
        record.degraded_reasons === undefined || record.degraded_reasons === null
            ? undefined
            : parseStringArray(
                  record.degraded_reasons,
                  `${context}.degraded_reasons`
              );

    const artifact: TechnicalIndicatorSeriesArtifact = {
        ticker: parseString(record.ticker, `${context}.ticker`),
        as_of: parseString(record.as_of, `${context}.as_of`),
        timeframes: parsedFrames,
    };
    if (degradedReasons) {
        artifact.degraded_reasons = degradedReasons;
    }
    return artifact;
};

export const parseTechnicalChartData = (
    value: unknown,
    context = 'technical chart data'
): TechnicalChartData => {
    const record = toRecord(value, context);
    return {
        fracdiff_series: parseSeriesMapNullable(
            record.fracdiff_series,
            `${context}.fracdiff_series`
        ),
        z_score_series: parseSeriesMapNullable(
            record.z_score_series,
            `${context}.z_score_series`
        ),
        indicators: toRecord(record.indicators, `${context}.indicators`),
    };
};

const parseTechnicalAnalysisReport = (
    record: Record<string, unknown>,
    context: string
): TechnicalAnalysisReport => {
    const report: TechnicalAnalysisReport = {
        schema_version: parseString(record.schema_version, `${context}.schema_version`),
        ticker: parseString(record.ticker, `${context}.ticker`),
        as_of: parseString(record.as_of, `${context}.as_of`),
        direction: parseString(record.direction, `${context}.direction`),
        risk_level: parseRiskLevel(record.risk_level, `${context}.risk_level`),
        artifact_refs: parseTechnicalArtifactRefs(
            record.artifact_refs,
            `${context}.artifact_refs`
        ),
        summary_tags: parseStringArray(record.summary_tags, `${context}.summary_tags`),
    };

    const confidence = parseNullableOptionalNumber(
        record.confidence,
        `${context}.confidence`
    );
    if (typeof confidence === 'number') {
        report.confidence = confidence;
    }
    const confidenceRaw = parseNullableOptionalNumber(
        record.confidence_raw,
        `${context}.confidence_raw`
    );
    if (typeof confidenceRaw === 'number') {
        report.confidence_raw = confidenceRaw;
    }
    const confidenceCalibrated = parseNullableOptionalNumber(
        record.confidence_calibrated,
        `${context}.confidence_calibrated`
    );
    if (typeof confidenceCalibrated === 'number') {
        report.confidence_calibrated = confidenceCalibrated;
    }
    const signalStrengthRaw = parseNullableOptionalNumber(
        record.signal_strength_raw,
        `${context}.signal_strength_raw`
    );
    if (typeof signalStrengthRaw === 'number') {
        report.signal_strength_raw = signalStrengthRaw;
    }
    const signalStrengthEffective = parseNullableOptionalNumber(
        record.signal_strength_effective,
        `${context}.signal_strength_effective`
    );
    if (typeof signalStrengthEffective === 'number') {
        report.signal_strength_effective = signalStrengthEffective;
    }
    const confidenceCalibration = parseConfidenceCalibration(
        record.confidence_calibration,
        `${context}.confidence_calibration`
    );
    if (confidenceCalibration) {
        report.confidence_calibration = confidenceCalibration;
    }
    const confidenceEligibility = parseConfidenceEligibility(
        record.confidence_eligibility,
        `${context}.confidence_eligibility`
    );
    if (confidenceEligibility) {
        report.confidence_eligibility = confidenceEligibility;
    }
    const momentumExtremes = parseMomentumExtremes(
        record.momentum_extremes,
        `${context}.momentum_extremes`
    );
    if (momentumExtremes) {
        report.momentum_extremes = momentumExtremes;
    }
    const analystPerspective = parseAnalystPerspective(
        record.analyst_perspective,
        `${context}.analyst_perspective`
    );
    if (analystPerspective) {
        report.analyst_perspective = analystPerspective;
    }
    const regimeSummary = parseRegimeSummary(
        record.regime_summary,
        `${context}.regime_summary`
    );
    if (regimeSummary) {
        report.regime_summary = regimeSummary;
    }
    const volumeProfileSummary = parseVolumeProfileSummary(
        record.volume_profile_summary,
        `${context}.volume_profile_summary`
    );
    if (volumeProfileSummary) {
        report.volume_profile_summary = volumeProfileSummary;
    }
    const structureConfluenceSummary = parseStructureConfluenceSummary(
        record.structure_confluence_summary,
        `${context}.structure_confluence_summary`
    );
    if (structureConfluenceSummary) {
        report.structure_confluence_summary = structureConfluenceSummary;
    }
    const evidenceBundle = parseEvidenceBundle(
        record.evidence_bundle,
        `${context}.evidence_bundle`
    );
    if (evidenceBundle) {
        report.evidence_bundle = evidenceBundle;
    }
    const signalStrengthSummary = parseSignalStrengthSummary(
        record.signal_strength_summary,
        `${context}.signal_strength_summary`
    );
    if (signalStrengthSummary) {
        report.signal_strength_summary = signalStrengthSummary;
    }
    const setupReliabilitySummary = parseSetupReliabilitySummary(
        record.setup_reliability_summary,
        `${context}.setup_reliability_summary`
    );
    if (setupReliabilitySummary) {
        report.setup_reliability_summary = setupReliabilitySummary;
    }
    const qualitySummary = parseQualitySummary(
        record.quality_summary,
        `${context}.quality_summary`
    );
    if (qualitySummary) {
        report.quality_summary = qualitySummary;
    }
    const alertReadout = parseAlertReadout(
        record.alert_readout,
        `${context}.alert_readout`
    );
    if (alertReadout) {
        report.alert_readout = alertReadout;
    }
    const observabilitySummary = parseObservabilitySummary(
        record.observability_summary,
        `${context}.observability_summary`
    );
    if (observabilitySummary) {
        report.observability_summary = observabilitySummary;
    }

    if (record.diagnostics !== undefined && record.diagnostics !== null) {
        const diagnostics = parseTechnicalDiagnostics(
            record.diagnostics,
            `${context}.diagnostics`
        );
        if (Object.keys(diagnostics).length > 0) {
            report.diagnostics = diagnostics;
        }
    }

    return report;
};

export const parseTechnicalArtifact = (
    value: unknown,
    context = 'technical artifact'
): TechnicalAnalysisSuccess => {
    const record = toRecord(value, context);
    return parseTechnicalAnalysisReport(record, context);
};

export const parseFundamentalArtifact = (
    value: unknown,
    context = 'fundamental artifact'
): FundamentalAnalysisSuccess => {
    const record = toRecord(value, context);
    if (record.status !== 'done') {
        throw new TypeError(`${context}.status must be done.`);
    }
    const parsed = parseFinancialPreview(
        {
            financial_reports: record.financial_reports,
            valuation_diagnostics: record.valuation_diagnostics,
        },
        `${context}.financial_reports_wrapper`
    );
    if (!parsed?.financial_reports) {
        throw new TypeError(`${context}.financial_reports is required.`);
    }
    const ticker = parseString(record.ticker, `${context}.ticker`);
    const companyName = parseNullableOptionalString(
        record.company_name,
        `${context}.company_name`
    );
    const sector = parseNullableOptionalString(record.sector, `${context}.sector`);
    const industry = parseNullableOptionalString(record.industry, `${context}.industry`);
    const reasoning = parseNullableOptionalString(
        record.reasoning,
        `${context}.reasoning`
    );
    const forwardSignals = (() => {
        if (record.forward_signals === undefined || record.forward_signals === null) {
            return undefined;
        }
        if (!Array.isArray(record.forward_signals)) {
            throw new TypeError(`${context}.forward_signals must be an array.`);
        }
        return record.forward_signals.map((item, idx) =>
            parseForwardSignal(item, `${context}.forward_signals[${idx}]`)
        );
    })();
    const valuationDiagnostics = parsed?.valuation_diagnostics
        ? (() => {
              const diagnostics = {
                  growth_rates_converged:
                      parsed.valuation_diagnostics.growth_rates_converged,
                  terminal_growth_effective:
                      parsed.valuation_diagnostics.terminal_growth_effective,
                  growth_consensus_policy:
                      parsed.valuation_diagnostics.growth_consensus_policy,
                  growth_consensus_horizon:
                      parsed.valuation_diagnostics.growth_consensus_horizon,
                  terminal_anchor_policy:
                      parsed.valuation_diagnostics.terminal_anchor_policy,
                  terminal_anchor_stale_fallback:
                      parsed.valuation_diagnostics.terminal_anchor_stale_fallback,
                  forward_signal_mapping_version:
                      parsed.valuation_diagnostics.forward_signal_mapping_version,
                  forward_signal_calibration_applied:
                      parsed.valuation_diagnostics
                          .forward_signal_calibration_applied,
                  sensitivity_summary:
                      parsed.valuation_diagnostics.sensitivity_summary,
              };
              const hasField = Object.values(diagnostics).some(
                  (value) => value !== undefined
              );
              return hasField ? diagnostics : undefined;
          })()
        : undefined;

    return {
        ticker,
        model_type: parseString(record.model_type, `${context}.model_type`),
        company_name: companyName ?? ticker,
        sector: sector ?? 'Unknown',
        industry: industry ?? 'Unknown',
        reasoning: reasoning ?? '',
        financial_reports: parsed.financial_reports,
        ...(forwardSignals ? { forward_signals: forwardSignals } : {}),
        ...(valuationDiagnostics
            ? { valuation_diagnostics: valuationDiagnostics }
            : {}),
        status: 'done',
    };
};

export type JsonValue =
    | string
    | number
    | boolean
    | null
    | JsonValue[]
    | { [key: string]: JsonValue };

const isJsonValue = (value: unknown): value is JsonValue => {
    if (
        value === null ||
        typeof value === 'string' ||
        typeof value === 'number' ||
        typeof value === 'boolean'
    ) {
        return true;
    }
    if (Array.isArray(value)) {
        return value.every((entry) => isJsonValue(entry));
    }
    if (!isRecord(value)) {
        return false;
    }
    return Object.values(value).every((entry) => isJsonValue(entry));
};

export const parseUnknownArtifact = (
    value: unknown,
    context = 'artifact'
): JsonValue => {
    if (!isJsonValue(value)) {
        throw new TypeError(`${context} must be valid JSON value.`);
    }
    return value;
};
