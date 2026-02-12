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
import { FundamentalAnalysisSuccess } from './fundamental';
import { parseFinancialPreview } from './fundamental-preview-parser';
import {
    ConfluenceEvidence,
    FracDiffMetrics,
    MemoryStrength,
    RiskLevel,
    SignalState,
    StatisticalState,
    TechnicalAnalysisSuccess,
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
        sourceType !== 'technicals'
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

const parseMemoryStrength = (value: unknown, context: string): MemoryStrength => {
    if (
        value === MemoryStrength.STRUCTURALLY_STABLE ||
        value === MemoryStrength.BALANCED ||
        value === MemoryStrength.FRAGILE
    ) {
        return value;
    }
    throw new TypeError(`${context} has unsupported memory strength value.`);
};

const parseStatisticalState = (
    value: unknown,
    context: string
): StatisticalState => {
    if (
        value === StatisticalState.EQUILIBRIUM ||
        value === StatisticalState.DEVIATING ||
        value === StatisticalState.STATISTICAL_ANOMALY
    ) {
        return value;
    }
    throw new TypeError(`${context} has unsupported statistical state value.`);
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

const parseConfluenceEvidence = (
    value: unknown,
    context: string
): ConfluenceEvidence => {
    const record = toRecord(value, context);
    return {
        bollinger_state: parseString(
            record.bollinger_state,
            `${context}.bollinger_state`
        ),
        macd_momentum: parseString(record.macd_momentum, `${context}.macd_momentum`),
        obv_state: parseString(record.obv_state, `${context}.obv_state`),
        statistical_strength: parseNumber(
            record.statistical_strength,
            `${context}.statistical_strength`
        ),
    };
};

const parseFracDiffMetrics = (
    value: unknown,
    context: string
): FracDiffMetrics => {
    const record = toRecord(value, context);
    return {
        optimal_d: parseNumber(record.optimal_d, `${context}.optimal_d`),
        window_length: parseNumber(record.window_length, `${context}.window_length`),
        adf_statistic: parseNumber(record.adf_statistic, `${context}.adf_statistic`),
        adf_pvalue: parseNumber(record.adf_pvalue, `${context}.adf_pvalue`),
        memory_strength: parseMemoryStrength(
            record.memory_strength,
            `${context}.memory_strength`
        ),
    };
};

const parseSignalState = (value: unknown, context: string): SignalState => {
    const record = toRecord(value, context);
    return {
        z_score: parseNumber(record.z_score, `${context}.z_score`),
        statistical_state: parseStatisticalState(
            record.statistical_state,
            `${context}.statistical_state`
        ),
        direction: parseString(record.direction, `${context}.direction`),
        risk_level: parseRiskLevel(record.risk_level, `${context}.risk_level`),
        confluence: parseConfluenceEvidence(
            record.confluence,
            `${context}.confluence`
        ),
    };
};

const parseSeriesMap = (
    value: unknown,
    context: string
): Record<string, number> => {
    const record = toRecord(value, context);
    const parsed: Record<string, number> = {};
    for (const [key, seriesValue] of Object.entries(record)) {
        if (typeof seriesValue !== 'number') {
            throw new TypeError(`${context}.${key} must be a number.`);
        }
        parsed[key] = seriesValue;
    }
    return parsed;
};

export const parseTechnicalArtifact = (
    value: unknown,
    context = 'technical artifact'
): TechnicalAnalysisSuccess => {
    const record = toRecord(value, context);
    const rawDataRecord =
        record.raw_data === undefined
            ? undefined
            : toRecord(record.raw_data, `${context}.raw_data`);

    const artifact: TechnicalAnalysisSuccess = {
        ticker: parseString(record.ticker, `${context}.ticker`),
        timestamp: parseString(record.timestamp, `${context}.timestamp`),
        frac_diff_metrics: parseFracDiffMetrics(
            record.frac_diff_metrics,
            `${context}.frac_diff_metrics`
        ),
        signal_state: parseSignalState(record.signal_state, `${context}.signal_state`),
        semantic_tags: parseStringArray(record.semantic_tags, `${context}.semantic_tags`),
    };

    const llmInterpretation = parseNullableOptionalString(
        record.llm_interpretation,
        `${context}.llm_interpretation`
    );
    if (typeof llmInterpretation === 'string') {
        artifact.llm_interpretation = llmInterpretation;
    }

    if (rawDataRecord !== undefined) {
        const rawData: NonNullable<TechnicalAnalysisSuccess['raw_data']> = {};
        if ('price_series' in rawDataRecord && rawDataRecord.price_series !== undefined) {
            rawData.price_series = parseSeriesMap(
                rawDataRecord.price_series,
                `${context}.raw_data.price_series`
            );
        }
        if (
            'fracdiff_series' in rawDataRecord &&
            rawDataRecord.fracdiff_series !== undefined
        ) {
            rawData.fracdiff_series = parseSeriesMap(
                rawDataRecord.fracdiff_series,
                `${context}.raw_data.fracdiff_series`
            );
        }
        if (
            'z_score_series' in rawDataRecord &&
            rawDataRecord.z_score_series !== undefined
        ) {
            rawData.z_score_series = parseSeriesMap(
                rawDataRecord.z_score_series,
                `${context}.raw_data.z_score_series`
            );
        }
        artifact.raw_data = rawData;
    }

    return artifact;
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
        { financial_reports: record.financial_reports },
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

    return {
        ticker,
        model_type: parseString(record.model_type, `${context}.model_type`),
        company_name: companyName ?? ticker,
        sector: sector ?? 'Unknown',
        industry: industry ?? 'Unknown',
        reasoning: reasoning ?? '',
        financial_reports: parsed.financial_reports,
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
