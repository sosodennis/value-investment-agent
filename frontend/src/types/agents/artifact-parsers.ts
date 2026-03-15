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
    TechnicalAlertsArtifact,
    TechnicalAnalysisReport,
    TechnicalAnalysisSuccess,
    TechnicalArtifactRefs,
    TechnicalChartData,
    TechnicalDiagnostics,
    TechnicalFeatureFrame,
    TechnicalFeatureIndicator,
    TechnicalFeaturePack,
    TechnicalFusionReport,
    TechnicalVerificationReport,
    TechnicalPatternFlag,
    TechnicalPatternFrame,
    TechnicalPatternLevel,
    TechnicalPatternPack,
    TechnicalIndicatorSeriesArtifact,
    TechnicalIndicatorSeriesFrame,
    TechnicalTimeseriesBundle,
    TechnicalTimeseriesFrame,
} from './technical';
import { isRecord } from '../preview';

const toRecord = (value: unknown, context: string): Record<string, unknown> => {
    if (!isRecord(value) || Array.isArray(value)) {
        throw new TypeError(`${context} must be an object.`);
    }
    return value;
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

    return signal;
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
    const severityCountsRecord =
        record.severity_counts === undefined || record.severity_counts === null
            ? undefined
            : toRecord(record.severity_counts, `${context}.severity_counts`);
    const severityCounts: Record<string, number> = {};
    if (severityCountsRecord) {
        for (const [key, entry] of Object.entries(severityCountsRecord)) {
            severityCounts[key] = parseNumber(
                entry,
                `${context}.severity_counts.${key}`
            );
        }
    }

    const summary: TechnicalAlertSummary = {};
    if (total !== undefined) summary.total = total;
    if (generatedAt !== undefined) summary.generated_at = generatedAt;
    if (Object.keys(severityCounts).length > 0) {
        summary.severity_counts = severityCounts;
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
        pack.feature_summary = featureSummary;
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

    return {
        support_levels: supportLevels,
        resistance_levels: resistanceLevels,
        breakouts,
        trendlines,
        pattern_flags: patternFlags,
        confidence_scores: confidenceScores,
    };
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

    const patternSummary =
        record.pattern_summary === undefined || record.pattern_summary === null
            ? undefined
            : toRecord(record.pattern_summary, `${context}.pattern_summary`);
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

    const alignmentReport =
        record.alignment_report === undefined || record.alignment_report === null
            ? undefined
            : toRecord(record.alignment_report, `${context}.alignment_report`);

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
    const alertsId = parseNullableOptionalString(
        record.alerts_id,
        `${context}.alerts_id`
    );
    const fusionReportId = parseNullableOptionalString(
        record.fusion_report_id,
        `${context}.fusion_report_id`
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
    if (typeof alertsId === 'string') {
        refs.alerts_id = alertsId;
    }
    if (typeof fusionReportId === 'string') {
        refs.fusion_report_id = fusionReportId;
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
    const metadata =
        record.metadata === undefined || record.metadata === null
            ? undefined
            : toRecord(record.metadata, `${context}.metadata`);

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
    const metadata =
        record.metadata === undefined || record.metadata === null
            ? undefined
            : toRecord(record.metadata, `${context}.metadata`);

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

    const llmInterpretation = parseNullableOptionalString(
        record.llm_interpretation,
        `${context}.llm_interpretation`
    );
    if (typeof llmInterpretation === 'string') {
        report.llm_interpretation = llmInterpretation;
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
