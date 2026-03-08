import {
    FinancialReport,
    FinancialReportBase,
    FinancialServicesExtension,
    IndustrialExtension,
    Provenance,
    RealEstateExtension,
    TraceableField,
} from './fundamental';
import { isRecord } from '../preview';

type SignalRiskLevel = 'low' | 'medium' | 'high';

export interface ParsedSignalState {
    risk_level: SignalRiskLevel;
    z_score: number;
}

export interface ParsedDistributionMetrics {
    mean?: number;
    median?: number;
    std?: number;
    percentile_5?: number;
    percentile_25?: number;
    percentile_75?: number;
    percentile_95?: number;
    min?: number;
    max?: number;
}

export interface ParsedDistributionSummary {
    summary: ParsedDistributionMetrics;
    diagnostics?: Record<string, number | boolean | string>;
}

export interface ParsedDistributionScenario {
    label: string;
    price: number;
}

export interface ParsedDistributionScenarios {
    bear?: ParsedDistributionScenario;
    base?: ParsedDistributionScenario;
    bull?: ParsedDistributionScenario;
}

export interface ParsedSensitivityDriver {
    shock_dimension?: string;
    shock_value_bp?: number;
    delta_pct_vs_base?: number;
}

export interface ParsedSensitivitySummary {
    enabled?: boolean;
    scenario_count?: number;
    max_upside_delta_pct?: number;
    max_downside_delta_pct?: number;
    top_drivers?: ParsedSensitivityDriver[];
}

export interface ParsedValuationDiagnostics {
    growth_rates_converged?: number[];
    terminal_growth_effective?: number;
    growth_consensus_policy?: string;
    growth_consensus_horizon?: string;
    terminal_anchor_policy?: string;
    terminal_anchor_stale_fallback?: boolean;
    base_growth_guardrail_applied?: boolean;
    base_growth_guardrail_version?: string;
    base_growth_raw_year1?: number;
    base_growth_raw_yearN?: number;
    base_growth_guarded_year1?: number;
    base_growth_guarded_yearN?: number;
    base_margin_guardrail_applied?: boolean;
    base_margin_guardrail_version?: string;
    base_margin_raw_year1?: number;
    base_margin_raw_yearN?: number;
    base_margin_guarded_year1?: number;
    base_margin_guarded_yearN?: number;
    forward_signal_mapping_version?: string;
    forward_signal_calibration_applied?: boolean;
    sensitivity_summary?: ParsedSensitivitySummary;
}

export interface ParsedBaseAssumptionGuardrailSlice {
    applied?: boolean;
    version?: string;
    raw_year1?: number;
    raw_yearN?: number;
    guarded_year1?: number;
    guarded_yearN?: number;
    reasons?: string[];
}

export interface ParsedBaseAssumptionGuardrailSummary {
    version?: string;
    growth?: ParsedBaseAssumptionGuardrailSlice;
    margin?: ParsedBaseAssumptionGuardrailSlice;
}

export interface ParsedAssumptionItem {
    statement: string;
    category?: string;
    severity?: string;
}

export interface ParsedForwardSignalSummary {
    signals_total?: number;
    signals_accepted?: number;
    signals_rejected?: number;
    evidence_count?: number;
    growth_adjustment_basis_points?: number;
    margin_adjustment_basis_points?: number;
    calibration_applied?: boolean;
    mapping_version?: string;
    risk_level?: string;
    source_types?: string[];
    decision_count?: number;
}

export interface ParsedAssumptionBreakdown {
    total_assumptions?: number;
    assumptions?: ParsedAssumptionItem[];
    key_parameters?: Record<string, string | number | boolean>;
    monte_carlo?: Record<string, string | number | boolean>;
    assumption_risk_level?: string;
    data_quality_flags?: string[];
    time_alignment_status?: string;
    forward_signal_summary?: ParsedForwardSignalSummary;
    forward_signal_risk_level?: string;
    forward_signal_evidence_count?: number;
    base_assumption_guardrail?: ParsedBaseAssumptionGuardrailSummary;
}

export interface ParsedDataFreshnessFinancialStatement {
    fiscal_year?: number;
    period_end_date?: string;
}

export interface ParsedDataFreshnessMarketData {
    provider?: string;
    as_of?: string;
    missing_fields?: string[];
    quality_flags?: string[];
    license_note?: string;
    market_datums?: Record<string, ParsedMarketDatumMeta>;
}

export interface ParsedMarketDatumMeta {
    value?: number;
    source?: string;
    as_of?: string;
    quality_flags?: string[];
    license_note?: string;
}

export interface ParsedDataFreshnessTimeAlignment {
    status?: string;
    policy?: string;
    lag_days?: number;
    threshold_days?: number;
    market_as_of?: string;
    filing_period_end?: string;
}

export interface ParsedDataFreshness {
    financial_statement?: ParsedDataFreshnessFinancialStatement;
    market_data?: ParsedDataFreshnessMarketData;
    shares_outstanding_source?: string;
    time_alignment?: ParsedDataFreshnessTimeAlignment;
}

export interface ParsedFinancialPreview {
    ticker?: string;
    valuation_score?: number;
    equity_value?: number;
    intrinsic_value?: number;
    upside_potential?: number;
    key_metrics?: Record<string, string>;
    signal_state?: ParsedSignalState;
    distribution_summary?: ParsedDistributionSummary;
    distribution_scenarios?: ParsedDistributionScenarios;
    valuation_diagnostics?: ParsedValuationDiagnostics;
    assumption_breakdown?: ParsedAssumptionBreakdown;
    data_freshness?: ParsedDataFreshness;
    assumption_risk_level?: string;
    data_quality_flags?: string[];
    time_alignment_status?: string;
    forward_signal_summary?: ParsedForwardSignalSummary;
    forward_signal_risk_level?: string;
    forward_signal_evidence_count?: number;
    financial_reports?: FinancialReport[];
}

const toRecord = (value: unknown, context: string): Record<string, unknown> => {
    if (!isRecord(value) || Array.isArray(value)) {
        throw new TypeError(`${context} must be an object.`);
    }
    return value;
};

const parseOptionalString = (
    value: unknown,
    context: string
): string | undefined => {
    if (value === undefined) return undefined;
    if (typeof value === 'string') return value;
    throw new TypeError(`${context} must be a string | undefined.`);
};

const parseNullableOptionalString = (
    value: unknown,
    context: string
): string | undefined => {
    if (value === null) return undefined;
    return parseOptionalString(value, context);
};

const parseOptionalNumber = (
    value: unknown,
    context: string
): number | undefined => {
    if (value === undefined) return undefined;
    if (typeof value === 'number') return value;
    throw new TypeError(`${context} must be a number | undefined.`);
};

const parseNullableOptionalNumber = (
    value: unknown,
    context: string
): number | undefined => {
    if (value === null) return undefined;
    return parseOptionalNumber(value, context);
};

const parseOptionalBoolean = (
    value: unknown,
    context: string
): boolean | undefined => {
    if (value === undefined) return undefined;
    if (typeof value === 'boolean') return value;
    throw new TypeError(`${context} must be a boolean | undefined.`);
};

const parseNullableOptionalBoolean = (
    value: unknown,
    context: string
): boolean | undefined => {
    if (value === null) return undefined;
    return parseOptionalBoolean(value, context);
};

const parseProvenance = (value: unknown, context: string): Provenance | null => {
    if (value === null || value === undefined) return null;
    const record = toRecord(value, context);
    const provenance: Provenance = {};

    const concept = parseOptionalString(record.concept, `${context}.concept`);
    const expression = parseOptionalString(
        record.expression,
        `${context}.expression`
    );
    const description = parseOptionalString(
        record.description,
        `${context}.description`
    );
    if (concept !== undefined) provenance.concept = concept;
    if (expression !== undefined) provenance.expression = expression;
    if (description !== undefined) provenance.description = description;
    return provenance;
};

const parseTraceableField = (value: unknown, context: string): TraceableField | null => {
    if (value === null) return null;
    const record = toRecord(value, context);
    const rawValue = record.value;
    if (
        rawValue !== null &&
        typeof rawValue !== 'string' &&
        typeof rawValue !== 'number'
    ) {
        throw new TypeError(`${context}.value must be string | number | null.`);
    }

    const field: TraceableField = { value: rawValue };
    if ('provenance' in record) {
        field.provenance = parseProvenance(
            record.provenance,
            `${context}.provenance`
        );
    }
    if ('timestamp' in record) {
        field.timestamp = parseOptionalString(
            record.timestamp,
            `${context}.timestamp`
        );
    }
    return field;
};

const parseOptionalTraceableField = (
    value: unknown,
    context: string
): TraceableField | null => {
    if (value === undefined || value === null) return null;
    return parseTraceableField(value, context);
};

const parseBase = (value: unknown, context: string): FinancialReportBase => {
    const record = toRecord(value, context);
    return {
        fiscal_year: parseTraceableField(record.fiscal_year, `${context}.fiscal_year`),
        fiscal_period: parseTraceableField(
            record.fiscal_period,
            `${context}.fiscal_period`
        ),
        period_end_date: parseOptionalTraceableField(
            record.period_end_date,
            `${context}.period_end_date`
        ),
        currency: parseOptionalTraceableField(record.currency, `${context}.currency`),
        company_name: parseTraceableField(
            record.company_name,
            `${context}.company_name`
        ),
        cik: parseTraceableField(record.cik, `${context}.cik`),
        sic_code: parseTraceableField(record.sic_code, `${context}.sic_code`),
        shares_outstanding: parseTraceableField(
            record.shares_outstanding,
            `${context}.shares_outstanding`
        ),
        total_revenue: parseTraceableField(
            record.total_revenue,
            `${context}.total_revenue`
        ),
        net_income: parseTraceableField(record.net_income, `${context}.net_income`),
        income_tax_expense: parseTraceableField(
            record.income_tax_expense,
            `${context}.income_tax_expense`
        ),
        total_assets: parseTraceableField(
            record.total_assets,
            `${context}.total_assets`
        ),
        total_liabilities: parseTraceableField(
            record.total_liabilities,
            `${context}.total_liabilities`
        ),
        total_equity: parseTraceableField(
            record.total_equity,
            `${context}.total_equity`
        ),
        cash_and_equivalents: parseTraceableField(
            record.cash_and_equivalents,
            `${context}.cash_and_equivalents`
        ),
        operating_cash_flow: parseTraceableField(
            record.operating_cash_flow,
            `${context}.operating_cash_flow`
        ),
    };
};

const parseIndustrialExtension = (
    value: unknown,
    context: string
): IndustrialExtension => {
    const record = toRecord(value, context);
    return {
        inventory: parseTraceableField(record.inventory, `${context}.inventory`),
        accounts_receivable: parseTraceableField(
            record.accounts_receivable,
            `${context}.accounts_receivable`
        ),
        cogs: parseTraceableField(record.cogs, `${context}.cogs`),
        rd_expense: parseTraceableField(record.rd_expense, `${context}.rd_expense`),
        sga_expense: parseTraceableField(
            record.sga_expense,
            `${context}.sga_expense`
        ),
        capex: parseTraceableField(record.capex, `${context}.capex`),
    };
};

const parseFinancialServicesExtension = (
    value: unknown,
    context: string
): FinancialServicesExtension => {
    const record = toRecord(value, context);
    return {
        loans_and_leases: parseTraceableField(
            record.loans_and_leases,
            `${context}.loans_and_leases`
        ),
        deposits: parseTraceableField(record.deposits, `${context}.deposits`),
        allowance_for_credit_losses: parseTraceableField(
            record.allowance_for_credit_losses,
            `${context}.allowance_for_credit_losses`
        ),
        interest_income: parseTraceableField(
            record.interest_income,
            `${context}.interest_income`
        ),
        interest_expense: parseTraceableField(
            record.interest_expense,
            `${context}.interest_expense`
        ),
        provision_for_loan_losses: parseTraceableField(
            record.provision_for_loan_losses,
            `${context}.provision_for_loan_losses`
        ),
    };
};

const parseRealEstateExtension = (
    value: unknown,
    context: string
): RealEstateExtension => {
    const record = toRecord(value, context);
    return {
        real_estate_assets: parseTraceableField(
            record.real_estate_assets,
            `${context}.real_estate_assets`
        ),
        accumulated_depreciation: parseTraceableField(
            record.accumulated_depreciation,
            `${context}.accumulated_depreciation`
        ),
        depreciation_and_amortization: parseTraceableField(
            record.depreciation_and_amortization,
            `${context}.depreciation_and_amortization`
        ),
        ffo: parseTraceableField(record.ffo, `${context}.ffo`),
    };
};

const parseExtensionType = (
    value: unknown,
    context: string
): FinancialReport['extension_type'] => {
    if (value === undefined) return undefined;
    if (value === null) return null;
    if (
        value === 'Industrial' ||
        value === 'FinancialServices' ||
        value === 'RealEstate'
    ) {
        return value;
    }
    throw new TypeError(
        `${context} must be Industrial | FinancialServices | RealEstate | null | undefined.`
    );
};

const parseIndustryType = (
    value: unknown,
    context: string
): FinancialReport['extension_type'] => {
    if (value === undefined || value === null) return undefined;
    if (value === 'Industrial') return 'Industrial';
    if (value === 'FinancialServices' || value === 'Financial') {
        return 'FinancialServices';
    }
    if (value === 'RealEstate') return 'RealEstate';
    if (value === 'General') return null;
    throw new TypeError(
        `${context} must be Industrial | Financial | FinancialServices | RealEstate | General | null | undefined.`
    );
};

const inferExtensionTypeFromShape = (
    value: unknown,
    context: string
): FinancialReport['extension_type'] => {
    if (value === undefined || value === null) return undefined;
    const record = toRecord(value, context);
    if ('inventory' in record || 'accounts_receivable' in record || 'capex' in record) {
        return 'Industrial';
    }
    if (
        'loans_and_leases' in record ||
        'deposits' in record ||
        'allowance_for_credit_losses' in record
    ) {
        return 'FinancialServices';
    }
    if ('real_estate_assets' in record || 'ffo' in record) {
        return 'RealEstate';
    }
    return undefined;
};

const parseExtension = (
    value: unknown,
    extensionType: FinancialReport['extension_type'],
    context: string
): FinancialReport['extension'] => {
    if (value === undefined) return undefined;
    if (value === null) return null;
    if (!extensionType) {
        throw new TypeError(
            `${context} requires extension_type when extension is present.`
        );
    }

    if (extensionType === 'Industrial') {
        return parseIndustrialExtension(value, context);
    }
    if (extensionType === 'FinancialServices') {
        return parseFinancialServicesExtension(value, context);
    }
    return parseRealEstateExtension(value, context);
};

const parseFinancialReport = (value: unknown, context: string): FinancialReport => {
    const record = toRecord(value, context);
    if (!('base' in record)) {
        throw new TypeError(`${context}.base is required.`);
    }

    const extensionTypeExplicit = parseExtensionType(
        record.extension_type,
        `${context}.extension_type`
    );
    const extensionTypeFromIndustry = parseIndustryType(
        record.industry_type,
        `${context}.industry_type`
    );
    const extensionTypeInferred = inferExtensionTypeFromShape(
        record.extension,
        `${context}.extension`
    );
    const extensionType =
        extensionTypeExplicit ??
        extensionTypeFromIndustry ??
        extensionTypeInferred;

    const report: FinancialReport = {
        base: parseBase(record.base, `${context}.base`),
    };

    if (extensionType !== undefined) {
        report.extension_type = extensionType ?? null;
    }
    if ('extension' in record) {
        report.extension = parseExtension(
            record.extension,
            extensionType,
            `${context}.extension`
        );
    }
    return report;
};

const parseFinancialReports = (
    value: unknown,
    context: string
): FinancialReport[] | undefined => {
    if (value === undefined) return undefined;
    if (!Array.isArray(value)) {
        throw new TypeError(`${context} must be an array.`);
    }
    return value.map((report, index) =>
        parseFinancialReport(report, `${context}[${index}]`)
    );
};

const parseKeyMetrics = (
    value: unknown,
    context: string
): Record<string, string> | undefined => {
    if (value === undefined) return undefined;
    const record = toRecord(value, context);
    const metrics: Record<string, string> = {};
    for (const [key, metricValue] of Object.entries(record)) {
        if (typeof metricValue !== 'string') {
            throw new TypeError(`${context}.${key} must be a string.`);
        }
        metrics[key] = metricValue;
    }
    return metrics;
};

const parseSignalState = (
    value: unknown,
    context: string
): ParsedSignalState | undefined => {
    if (value === undefined) return undefined;
    const record = toRecord(value, context);
    const riskLevel = record.risk_level;
    const zScore = record.z_score;

    if (riskLevel !== 'low' && riskLevel !== 'medium' && riskLevel !== 'high') {
        throw new TypeError(`${context}.risk_level must be low | medium | high.`);
    }
    if (typeof zScore !== 'number') {
        throw new TypeError(`${context}.z_score must be a number.`);
    }

    return {
        risk_level: riskLevel,
        z_score: zScore,
    };
};

const parseDistributionMetrics = (
    value: unknown,
    context: string
): ParsedDistributionMetrics => {
    const record = toRecord(value, context);
    const parsed: ParsedDistributionMetrics = {};
    const numericKeys: Array<keyof ParsedDistributionMetrics> = [
        'mean',
        'median',
        'std',
        'percentile_5',
        'percentile_25',
        'percentile_75',
        'percentile_95',
        'min',
        'max',
    ];
    for (const key of numericKeys) {
        const parsedValue = parseNullableOptionalNumber(record[key], `${context}.${key}`);
        if (parsedValue !== undefined) {
            parsed[key] = parsedValue;
        }
    }
    return parsed;
};

const parseDiagnostics = (
    value: unknown,
    context: string
): Record<string, number | boolean | string> | undefined => {
    if (value === undefined || value === null) return undefined;
    const record = toRecord(value, context);
    const parsed: Record<string, number | boolean | string> = {};
    for (const [key, rawValue] of Object.entries(record)) {
        if (rawValue === null || rawValue === undefined) {
            continue;
        }
        if (typeof rawValue === 'number') {
            if (Number.isFinite(rawValue)) {
                parsed[key] = rawValue;
            }
            continue;
        }
        if (typeof rawValue === 'boolean') {
            parsed[key] = rawValue;
            continue;
        }
        if (typeof rawValue === 'string') {
            parsed[key] = rawValue;
            continue;
        }
        if (
            typeof rawValue !== 'number' &&
            typeof rawValue !== 'boolean' &&
            typeof rawValue !== 'string'
        ) {
            throw new TypeError(
                `${context}.${key} must be a number | boolean | string.`
            );
        }
    }
    return parsed;
};

const parseDistributionSummary = (
    value: unknown,
    context: string
): ParsedDistributionSummary | undefined => {
    if (value === undefined || value === null) return undefined;
    const record = toRecord(value, context);
    if (!('summary' in record)) {
        throw new TypeError(`${context}.summary is required.`);
    }
    const summary = parseDistributionMetrics(record.summary, `${context}.summary`);
    const diagnostics = parseDiagnostics(record.diagnostics, `${context}.diagnostics`);
    const parsed: ParsedDistributionSummary = { summary };
    if (diagnostics !== undefined) parsed.diagnostics = diagnostics;
    return parsed;
};

const parseDistributionScenario = (
    value: unknown,
    context: string
): ParsedDistributionScenario | undefined => {
    if (value === undefined || value === null) return undefined;
    const record = toRecord(value, context);
    const label = parseOptionalString(record.label, `${context}.label`);
    if (label === undefined) {
        throw new TypeError(`${context}.label must be a string.`);
    }
    const price = parseNullableOptionalNumber(record.price, `${context}.price`);
    if (price === undefined) {
        throw new TypeError(`${context}.price must be a number.`);
    }
    return { label, price };
};

const parseDistributionScenarios = (
    value: unknown,
    context: string
): ParsedDistributionScenarios | undefined => {
    if (value === undefined || value === null) return undefined;
    const record = toRecord(value, context);
    const scenarios: ParsedDistributionScenarios = {};
    const bear = parseDistributionScenario(record.bear, `${context}.bear`);
    const base = parseDistributionScenario(record.base, `${context}.base`);
    const bull = parseDistributionScenario(record.bull, `${context}.bull`);
    if (bear !== undefined) scenarios.bear = bear;
    if (base !== undefined) scenarios.base = base;
    if (bull !== undefined) scenarios.bull = bull;
    return scenarios;
};

const parseScalarRecord = (
    value: unknown,
    context: string
): Record<string, string | number | boolean> | undefined => {
    if (value === undefined || value === null) return undefined;
    const record = toRecord(value, context);
    const parsed: Record<string, string | number | boolean> = {};
    for (const [key, rawValue] of Object.entries(record)) {
        if (
            typeof rawValue !== 'string' &&
            typeof rawValue !== 'number' &&
            typeof rawValue !== 'boolean'
        ) {
            throw new TypeError(
                `${context}.${key} must be string | number | boolean.`
            );
        }
        parsed[key] = rawValue;
    }
    return parsed;
};

const parseSensitivityDriver = (
    value: unknown,
    context: string
): ParsedSensitivityDriver => {
    const record = toRecord(value, context);
    const parsed: ParsedSensitivityDriver = {};
    const shockDimension = parseNullableOptionalString(
        record.shock_dimension,
        `${context}.shock_dimension`
    );
    const shockValueBp = parseNullableOptionalNumber(
        record.shock_value_bp,
        `${context}.shock_value_bp`
    );
    const deltaPctVsBase = parseNullableOptionalNumber(
        record.delta_pct_vs_base,
        `${context}.delta_pct_vs_base`
    );
    if (shockDimension !== undefined) parsed.shock_dimension = shockDimension;
    if (shockValueBp !== undefined) parsed.shock_value_bp = shockValueBp;
    if (deltaPctVsBase !== undefined) parsed.delta_pct_vs_base = deltaPctVsBase;
    return parsed;
};

const parseSensitivitySummary = (
    value: unknown,
    context: string
): ParsedSensitivitySummary | undefined => {
    if (value === undefined || value === null) return undefined;
    const record = toRecord(value, context);
    const parsed: ParsedSensitivitySummary = {};
    const enabled = parseNullableOptionalBoolean(record.enabled, `${context}.enabled`);
    const scenarioCount = parseNullableOptionalNumber(
        record.scenario_count,
        `${context}.scenario_count`
    );
    const maxUpsideDeltaPct = parseNullableOptionalNumber(
        record.max_upside_delta_pct,
        `${context}.max_upside_delta_pct`
    );
    const maxDownsideDeltaPct = parseNullableOptionalNumber(
        record.max_downside_delta_pct,
        `${context}.max_downside_delta_pct`
    );

    if (enabled !== undefined) parsed.enabled = enabled;
    if (scenarioCount !== undefined) parsed.scenario_count = scenarioCount;
    if (maxUpsideDeltaPct !== undefined) {
        parsed.max_upside_delta_pct = maxUpsideDeltaPct;
    }
    if (maxDownsideDeltaPct !== undefined) {
        parsed.max_downside_delta_pct = maxDownsideDeltaPct;
    }

    const topDriversRaw = record.top_drivers;
    if (topDriversRaw !== undefined && topDriversRaw !== null) {
        if (!Array.isArray(topDriversRaw)) {
            throw new TypeError(`${context}.top_drivers must be an array.`);
        }
        parsed.top_drivers = topDriversRaw.map((item, index) =>
            parseSensitivityDriver(item, `${context}.top_drivers[${index}]`)
        );
    }

    return parsed;
};

const parseValuationDiagnostics = (
    value: unknown,
    context: string
): ParsedValuationDiagnostics | undefined => {
    if (value === undefined || value === null) return undefined;
    const record = toRecord(value, context);
    const parsed: ParsedValuationDiagnostics = {};

    const growthRatesConverged = parseOptionalNumberArray(
        record.growth_rates_converged,
        `${context}.growth_rates_converged`
    );
    if (growthRatesConverged !== undefined) {
        parsed.growth_rates_converged = growthRatesConverged;
    }

    const terminalGrowthEffective = parseNullableOptionalNumber(
        record.terminal_growth_effective,
        `${context}.terminal_growth_effective`
    );
    if (terminalGrowthEffective !== undefined) {
        parsed.terminal_growth_effective = terminalGrowthEffective;
    }

    const growthConsensusPolicy = parseOptionalString(
        record.growth_consensus_policy,
        `${context}.growth_consensus_policy`
    );
    if (growthConsensusPolicy !== undefined) {
        parsed.growth_consensus_policy = growthConsensusPolicy;
    }

    const growthConsensusHorizon = parseOptionalString(
        record.growth_consensus_horizon,
        `${context}.growth_consensus_horizon`
    );
    if (growthConsensusHorizon !== undefined) {
        parsed.growth_consensus_horizon = growthConsensusHorizon;
    }

    const terminalAnchorPolicy = parseOptionalString(
        record.terminal_anchor_policy,
        `${context}.terminal_anchor_policy`
    );
    if (terminalAnchorPolicy !== undefined) {
        parsed.terminal_anchor_policy = terminalAnchorPolicy;
    }

    const terminalAnchorStaleFallback = parseOptionalBoolean(
        record.terminal_anchor_stale_fallback,
        `${context}.terminal_anchor_stale_fallback`
    );
    if (terminalAnchorStaleFallback !== undefined) {
        parsed.terminal_anchor_stale_fallback = terminalAnchorStaleFallback;
    }

    const baseGrowthGuardrailApplied = parseOptionalBoolean(
        record.base_growth_guardrail_applied,
        `${context}.base_growth_guardrail_applied`
    );
    if (baseGrowthGuardrailApplied !== undefined) {
        parsed.base_growth_guardrail_applied = baseGrowthGuardrailApplied;
    }
    const baseGrowthGuardrailVersion = parseOptionalString(
        record.base_growth_guardrail_version,
        `${context}.base_growth_guardrail_version`
    );
    if (baseGrowthGuardrailVersion !== undefined) {
        parsed.base_growth_guardrail_version = baseGrowthGuardrailVersion;
    }
    const baseGrowthRawYear1 = parseNullableOptionalNumber(
        record.base_growth_raw_year1,
        `${context}.base_growth_raw_year1`
    );
    if (baseGrowthRawYear1 !== undefined) {
        parsed.base_growth_raw_year1 = baseGrowthRawYear1;
    }
    const baseGrowthRawYearN = parseNullableOptionalNumber(
        record.base_growth_raw_yearN,
        `${context}.base_growth_raw_yearN`
    );
    if (baseGrowthRawYearN !== undefined) {
        parsed.base_growth_raw_yearN = baseGrowthRawYearN;
    }
    const baseGrowthGuardedYear1 = parseNullableOptionalNumber(
        record.base_growth_guarded_year1,
        `${context}.base_growth_guarded_year1`
    );
    if (baseGrowthGuardedYear1 !== undefined) {
        parsed.base_growth_guarded_year1 = baseGrowthGuardedYear1;
    }
    const baseGrowthGuardedYearN = parseNullableOptionalNumber(
        record.base_growth_guarded_yearN,
        `${context}.base_growth_guarded_yearN`
    );
    if (baseGrowthGuardedYearN !== undefined) {
        parsed.base_growth_guarded_yearN = baseGrowthGuardedYearN;
    }
    const baseMarginGuardrailApplied = parseOptionalBoolean(
        record.base_margin_guardrail_applied,
        `${context}.base_margin_guardrail_applied`
    );
    if (baseMarginGuardrailApplied !== undefined) {
        parsed.base_margin_guardrail_applied = baseMarginGuardrailApplied;
    }
    const baseMarginGuardrailVersion = parseOptionalString(
        record.base_margin_guardrail_version,
        `${context}.base_margin_guardrail_version`
    );
    if (baseMarginGuardrailVersion !== undefined) {
        parsed.base_margin_guardrail_version = baseMarginGuardrailVersion;
    }
    const baseMarginRawYear1 = parseNullableOptionalNumber(
        record.base_margin_raw_year1,
        `${context}.base_margin_raw_year1`
    );
    if (baseMarginRawYear1 !== undefined) {
        parsed.base_margin_raw_year1 = baseMarginRawYear1;
    }
    const baseMarginRawYearN = parseNullableOptionalNumber(
        record.base_margin_raw_yearN,
        `${context}.base_margin_raw_yearN`
    );
    if (baseMarginRawYearN !== undefined) {
        parsed.base_margin_raw_yearN = baseMarginRawYearN;
    }
    const baseMarginGuardedYear1 = parseNullableOptionalNumber(
        record.base_margin_guarded_year1,
        `${context}.base_margin_guarded_year1`
    );
    if (baseMarginGuardedYear1 !== undefined) {
        parsed.base_margin_guarded_year1 = baseMarginGuardedYear1;
    }
    const baseMarginGuardedYearN = parseNullableOptionalNumber(
        record.base_margin_guarded_yearN,
        `${context}.base_margin_guarded_yearN`
    );
    if (baseMarginGuardedYearN !== undefined) {
        parsed.base_margin_guarded_yearN = baseMarginGuardedYearN;
    }

    const forwardSignalMappingVersion = parseOptionalString(
        record.forward_signal_mapping_version,
        `${context}.forward_signal_mapping_version`
    );
    if (forwardSignalMappingVersion !== undefined) {
        parsed.forward_signal_mapping_version = forwardSignalMappingVersion;
    }

    const forwardSignalCalibrationApplied = parseOptionalBoolean(
        record.forward_signal_calibration_applied,
        `${context}.forward_signal_calibration_applied`
    );
    if (forwardSignalCalibrationApplied !== undefined) {
        parsed.forward_signal_calibration_applied =
            forwardSignalCalibrationApplied;
    }

    const sensitivitySummary = parseSensitivitySummary(
        record.sensitivity_summary,
        `${context}.sensitivity_summary`
    );
    if (sensitivitySummary !== undefined) {
        parsed.sensitivity_summary = sensitivitySummary;
    }

    return parsed;
};

const parseOptionalNumberArray = (
    value: unknown,
    context: string
): number[] | undefined => {
    if (value === undefined || value === null) return undefined;
    if (!Array.isArray(value)) {
        throw new TypeError(`${context} must be an array.`);
    }
    const parsed: number[] = [];
    for (let i = 0; i < value.length; i += 1) {
        const item = parseOptionalNumber(value[i], `${context}[${i}]`);
        if (item === undefined) {
            throw new TypeError(`${context}[${i}] must be a number.`);
        }
        parsed.push(item);
    }
    return parsed;
};

const parseOptionalStringArray = (
    value: unknown,
    context: string
): string[] | undefined => {
    if (value === undefined || value === null) return undefined;
    if (!Array.isArray(value)) {
        throw new TypeError(`${context} must be an array.`);
    }
    const parsed: string[] = [];
    for (let i = 0; i < value.length; i += 1) {
        const item = parseOptionalString(value[i], `${context}[${i}]`);
        if (item === undefined) {
            throw new TypeError(`${context}[${i}] must be a string.`);
        }
        parsed.push(item);
    }
    return parsed;
};

const parseForwardSignalSummary = (
    value: unknown,
    context: string
): ParsedForwardSignalSummary | undefined => {
    if (value === undefined || value === null) return undefined;
    const record = toRecord(value, context);
    const parsed: ParsedForwardSignalSummary = {};

    const signalsTotal = parseNullableOptionalNumber(
        record.signals_total,
        `${context}.signals_total`
    );
    if (signalsTotal !== undefined) parsed.signals_total = signalsTotal;
    const signalsAccepted = parseNullableOptionalNumber(
        record.signals_accepted,
        `${context}.signals_accepted`
    );
    if (signalsAccepted !== undefined) parsed.signals_accepted = signalsAccepted;
    const signalsRejected = parseNullableOptionalNumber(
        record.signals_rejected,
        `${context}.signals_rejected`
    );
    if (signalsRejected !== undefined) parsed.signals_rejected = signalsRejected;
    const evidenceCount = parseNullableOptionalNumber(
        record.evidence_count,
        `${context}.evidence_count`
    );
    if (evidenceCount !== undefined) parsed.evidence_count = evidenceCount;
    const growthAdjustmentBp = parseNullableOptionalNumber(
        record.growth_adjustment_basis_points,
        `${context}.growth_adjustment_basis_points`
    );
    if (growthAdjustmentBp !== undefined) {
        parsed.growth_adjustment_basis_points = growthAdjustmentBp;
    }
    const marginAdjustmentBp = parseNullableOptionalNumber(
        record.margin_adjustment_basis_points,
        `${context}.margin_adjustment_basis_points`
    );
    if (marginAdjustmentBp !== undefined) {
        parsed.margin_adjustment_basis_points = marginAdjustmentBp;
    }
    const calibrationApplied = parseNullableOptionalBoolean(
        record.calibration_applied,
        `${context}.calibration_applied`
    );
    if (calibrationApplied !== undefined) {
        parsed.calibration_applied = calibrationApplied;
    }
    const mappingVersion = parseNullableOptionalString(
        record.mapping_version,
        `${context}.mapping_version`
    );
    if (mappingVersion !== undefined) {
        parsed.mapping_version = mappingVersion;
    }

    const riskLevel = parseNullableOptionalString(
        record.risk_level,
        `${context}.risk_level`
    );
    if (riskLevel !== undefined) {
        parsed.risk_level = riskLevel;
    }

    const sourceTypes = parseOptionalStringArray(
        record.source_types,
        `${context}.source_types`
    );
    if (sourceTypes !== undefined) {
        parsed.source_types = sourceTypes;
    }

    const decisionsRaw = record.decisions;
    if (decisionsRaw !== undefined && decisionsRaw !== null) {
        if (!Array.isArray(decisionsRaw)) {
            throw new TypeError(`${context}.decisions must be an array.`);
        }
        parsed.decision_count = decisionsRaw.length;
    }

    return parsed;
};

const parseMarketDatums = (
    value: unknown,
    context: string
): Record<string, ParsedMarketDatumMeta> | undefined => {
    if (value === undefined || value === null) return undefined;
    const record = toRecord(value, context);
    const parsed: Record<string, ParsedMarketDatumMeta> = {};
    for (const [field, datumRaw] of Object.entries(record)) {
        const datum = toRecord(datumRaw, `${context}.${field}`);
        const meta: ParsedMarketDatumMeta = {};
        const datumValue = parseNullableOptionalNumber(
            datum.value,
            `${context}.${field}.value`
        );
        const source = parseNullableOptionalString(
            datum.source,
            `${context}.${field}.source`
        );
        const asOf = parseNullableOptionalString(
            datum.as_of,
            `${context}.${field}.as_of`
        );
        const qualityFlags = parseOptionalStringArray(
            datum.quality_flags,
            `${context}.${field}.quality_flags`
        );
        const licenseNote = parseNullableOptionalString(
            datum.license_note,
            `${context}.${field}.license_note`
        );
        if (datumValue !== undefined) meta.value = datumValue;
        if (source !== undefined) meta.source = source;
        if (asOf !== undefined) meta.as_of = asOf;
        if (qualityFlags !== undefined) meta.quality_flags = qualityFlags;
        if (licenseNote !== undefined) meta.license_note = licenseNote;
        parsed[field] = meta;
    }
    return parsed;
};

const parseAssumptionItem = (
    value: unknown,
    context: string
): ParsedAssumptionItem => {
    const record = toRecord(value, context);
    const statement = parseOptionalString(record.statement, `${context}.statement`);
    if (statement === undefined) {
        throw new TypeError(`${context}.statement must be a string.`);
    }
    const category = parseNullableOptionalString(record.category, `${context}.category`);
    const severity = parseNullableOptionalString(record.severity, `${context}.severity`);
    const parsed: ParsedAssumptionItem = { statement };
    if (category !== undefined) parsed.category = category;
    if (severity !== undefined) parsed.severity = severity;
    return parsed;
};

const parseBaseAssumptionGuardrailSlice = (
    value: unknown,
    context: string
): ParsedBaseAssumptionGuardrailSlice | undefined => {
    if (value === undefined || value === null) return undefined;
    const record = toRecord(value, context);
    const parsed: ParsedBaseAssumptionGuardrailSlice = {};

    const applied = parseNullableOptionalBoolean(record.applied, `${context}.applied`);
    if (applied !== undefined) parsed.applied = applied;
    const version = parseNullableOptionalString(record.version, `${context}.version`);
    if (version !== undefined) parsed.version = version;
    const rawYear1 = parseNullableOptionalNumber(record.raw_year1, `${context}.raw_year1`);
    if (rawYear1 !== undefined) parsed.raw_year1 = rawYear1;
    const rawYearN = parseNullableOptionalNumber(record.raw_yearN, `${context}.raw_yearN`);
    if (rawYearN !== undefined) parsed.raw_yearN = rawYearN;
    const guardedYear1 = parseNullableOptionalNumber(
        record.guarded_year1,
        `${context}.guarded_year1`
    );
    if (guardedYear1 !== undefined) parsed.guarded_year1 = guardedYear1;
    const guardedYearN = parseNullableOptionalNumber(
        record.guarded_yearN,
        `${context}.guarded_yearN`
    );
    if (guardedYearN !== undefined) parsed.guarded_yearN = guardedYearN;
    const reasons = parseOptionalStringArray(record.reasons, `${context}.reasons`);
    if (reasons !== undefined) parsed.reasons = reasons;
    return parsed;
};

const parseBaseAssumptionGuardrailSummary = (
    value: unknown,
    context: string
): ParsedBaseAssumptionGuardrailSummary | undefined => {
    if (value === undefined || value === null) return undefined;
    const record = toRecord(value, context);
    const parsed: ParsedBaseAssumptionGuardrailSummary = {};

    const version = parseNullableOptionalString(record.version, `${context}.version`);
    if (version !== undefined) parsed.version = version;
    const growth = parseBaseAssumptionGuardrailSlice(
        record.growth,
        `${context}.growth`
    );
    if (growth !== undefined) parsed.growth = growth;
    const margin = parseBaseAssumptionGuardrailSlice(
        record.margin,
        `${context}.margin`
    );
    if (margin !== undefined) parsed.margin = margin;
    return parsed;
};

const parseAssumptionBreakdown = (
    value: unknown,
    context: string
): ParsedAssumptionBreakdown | undefined => {
    if (value === undefined || value === null) return undefined;
    const record = toRecord(value, context);
    const parsed: ParsedAssumptionBreakdown = {};
    const totalAssumptions = parseNullableOptionalNumber(
        record.total_assumptions,
        `${context}.total_assumptions`
    );
    if (totalAssumptions !== undefined) {
        parsed.total_assumptions = totalAssumptions;
    }

    const assumptionsRaw = record.assumptions;
    if (assumptionsRaw !== undefined && assumptionsRaw !== null) {
        if (!Array.isArray(assumptionsRaw)) {
            throw new TypeError(`${context}.assumptions must be an array.`);
        }
        parsed.assumptions = assumptionsRaw.map((item, index) =>
            parseAssumptionItem(item, `${context}.assumptions[${index}]`)
        );
    }

    const keyParameters = parseScalarRecord(
        record.key_parameters,
        `${context}.key_parameters`
    );
    if (keyParameters !== undefined) {
        parsed.key_parameters = keyParameters;
    }

    const monteCarlo = parseScalarRecord(
        record.monte_carlo,
        `${context}.monte_carlo`
    );
    if (monteCarlo !== undefined) {
        parsed.monte_carlo = monteCarlo;
    }

    const assumptionRiskLevel = parseNullableOptionalString(
        record.assumption_risk_level,
        `${context}.assumption_risk_level`
    );
    if (assumptionRiskLevel !== undefined) {
        parsed.assumption_risk_level = assumptionRiskLevel;
    }

    const dataQualityFlags = parseOptionalStringArray(
        record.data_quality_flags,
        `${context}.data_quality_flags`
    );
    if (dataQualityFlags !== undefined) {
        parsed.data_quality_flags = dataQualityFlags;
    }

    const timeAlignmentStatus = parseNullableOptionalString(
        record.time_alignment_status,
        `${context}.time_alignment_status`
    );
    if (timeAlignmentStatus !== undefined) {
        parsed.time_alignment_status = timeAlignmentStatus;
    }

    const forwardSignalSummary = parseForwardSignalSummary(
        record.forward_signal_summary,
        `${context}.forward_signal_summary`
    );
    if (forwardSignalSummary !== undefined) {
        parsed.forward_signal_summary = forwardSignalSummary;
    }

    const forwardSignalRiskLevel = parseNullableOptionalString(
        record.forward_signal_risk_level,
        `${context}.forward_signal_risk_level`
    );
    if (forwardSignalRiskLevel !== undefined) {
        parsed.forward_signal_risk_level = forwardSignalRiskLevel;
    }

    const forwardSignalEvidenceCount = parseNullableOptionalNumber(
        record.forward_signal_evidence_count,
        `${context}.forward_signal_evidence_count`
    );
    if (forwardSignalEvidenceCount !== undefined) {
        parsed.forward_signal_evidence_count = forwardSignalEvidenceCount;
    }

    const baseAssumptionGuardrail = parseBaseAssumptionGuardrailSummary(
        record.base_assumption_guardrail,
        `${context}.base_assumption_guardrail`
    );
    if (baseAssumptionGuardrail !== undefined) {
        parsed.base_assumption_guardrail = baseAssumptionGuardrail;
    }
    return parsed;
};

const parseDataFreshness = (
    value: unknown,
    context: string
): ParsedDataFreshness | undefined => {
    if (value === undefined || value === null) return undefined;
    const record = toRecord(value, context);
    const parsed: ParsedDataFreshness = {};

    const financialStatementRaw = record.financial_statement;
    if (financialStatementRaw !== undefined && financialStatementRaw !== null) {
        const financialStatementRecord = toRecord(
            financialStatementRaw,
            `${context}.financial_statement`
        );
        const fiscalYear = parseNullableOptionalNumber(
            financialStatementRecord.fiscal_year,
            `${context}.financial_statement.fiscal_year`
        );
        const periodEndDate = parseNullableOptionalString(
            financialStatementRecord.period_end_date,
            `${context}.financial_statement.period_end_date`
        );
        const financialStatement: ParsedDataFreshnessFinancialStatement = {};
        if (fiscalYear !== undefined) financialStatement.fiscal_year = fiscalYear;
        if (periodEndDate !== undefined) financialStatement.period_end_date = periodEndDate;
        parsed.financial_statement = financialStatement;
    }

    const marketDataRaw = record.market_data;
    if (marketDataRaw !== undefined && marketDataRaw !== null) {
        const marketDataRecord = toRecord(marketDataRaw, `${context}.market_data`);
        const provider = parseNullableOptionalString(
            marketDataRecord.provider,
            `${context}.market_data.provider`
        );
        const asOf = parseNullableOptionalString(
            marketDataRecord.as_of,
            `${context}.market_data.as_of`
        );
        const missingFieldsRaw = marketDataRecord.missing_fields;
        const qualityFlagsRaw = marketDataRecord.quality_flags;

        const marketData: ParsedDataFreshnessMarketData = {};
        if (provider !== undefined) marketData.provider = provider;
        if (asOf !== undefined) marketData.as_of = asOf;
        if (missingFieldsRaw !== undefined && missingFieldsRaw !== null) {
            if (!Array.isArray(missingFieldsRaw)) {
                throw new TypeError(`${context}.market_data.missing_fields must be an array.`);
            }
            const missingFields: string[] = [];
            for (let i = 0; i < missingFieldsRaw.length; i += 1) {
                const fieldValue = parseOptionalString(
                    missingFieldsRaw[i],
                    `${context}.market_data.missing_fields[${i}]`
                );
                if (fieldValue === undefined) {
                    throw new TypeError(
                        `${context}.market_data.missing_fields[${i}] must be a string.`
                    );
                }
                missingFields.push(fieldValue);
            }
            marketData.missing_fields = missingFields;
        }
        const qualityFlags = parseOptionalStringArray(
            qualityFlagsRaw,
            `${context}.market_data.quality_flags`
        );
        if (qualityFlags !== undefined) marketData.quality_flags = qualityFlags;
        const licenseNote = parseNullableOptionalString(
            marketDataRecord.license_note,
            `${context}.market_data.license_note`
        );
        if (licenseNote !== undefined) marketData.license_note = licenseNote;
        const marketDatums = parseMarketDatums(
            marketDataRecord.market_datums,
            `${context}.market_data.market_datums`
        );
        if (marketDatums !== undefined) marketData.market_datums = marketDatums;
        parsed.market_data = marketData;
    }

    const sharesOutstandingSource = parseNullableOptionalString(
        record.shares_outstanding_source,
        `${context}.shares_outstanding_source`
    );
    if (sharesOutstandingSource !== undefined) {
        parsed.shares_outstanding_source = sharesOutstandingSource;
    }

    const timeAlignmentRaw = record.time_alignment;
    if (timeAlignmentRaw !== undefined && timeAlignmentRaw !== null) {
        const timeAlignmentRecord = toRecord(
            timeAlignmentRaw,
            `${context}.time_alignment`
        );
        const status = parseNullableOptionalString(
            timeAlignmentRecord.status,
            `${context}.time_alignment.status`
        );
        const policy = parseNullableOptionalString(
            timeAlignmentRecord.policy,
            `${context}.time_alignment.policy`
        );
        const lagDays = parseNullableOptionalNumber(
            timeAlignmentRecord.lag_days,
            `${context}.time_alignment.lag_days`
        );
        const thresholdDays = parseNullableOptionalNumber(
            timeAlignmentRecord.threshold_days,
            `${context}.time_alignment.threshold_days`
        );
        const marketAsOf = parseNullableOptionalString(
            timeAlignmentRecord.market_as_of,
            `${context}.time_alignment.market_as_of`
        );
        const filingPeriodEnd = parseNullableOptionalString(
            timeAlignmentRecord.filing_period_end,
            `${context}.time_alignment.filing_period_end`
        );
        const timeAlignment: ParsedDataFreshnessTimeAlignment = {};
        if (status !== undefined) timeAlignment.status = status;
        if (policy !== undefined) timeAlignment.policy = policy;
        if (lagDays !== undefined) timeAlignment.lag_days = lagDays;
        if (thresholdDays !== undefined) timeAlignment.threshold_days = thresholdDays;
        if (marketAsOf !== undefined) timeAlignment.market_as_of = marketAsOf;
        if (filingPeriodEnd !== undefined) {
            timeAlignment.filing_period_end = filingPeriodEnd;
        }
        parsed.time_alignment = timeAlignment;
    }
    return parsed;
};

export const parseFinancialPreview = (
    value: unknown,
    context = 'preview'
): ParsedFinancialPreview | null => {
    if (value === undefined || value === null) return null;

    const record = toRecord(value, context);
    const parsed: ParsedFinancialPreview = {};

    const ticker = parseNullableOptionalString(record.ticker, `${context}.ticker`);
    if (ticker !== undefined) parsed.ticker = ticker;

    const valuationScore = parseNullableOptionalNumber(
        record.valuation_score,
        `${context}.valuation_score`
    );
    if (valuationScore !== undefined) parsed.valuation_score = valuationScore;

    const equityValue = parseNullableOptionalNumber(
        record.equity_value,
        `${context}.equity_value`
    );
    if (equityValue !== undefined) parsed.equity_value = equityValue;

    const intrinsicValue = parseNullableOptionalNumber(
        record.intrinsic_value,
        `${context}.intrinsic_value`
    );
    if (intrinsicValue !== undefined) parsed.intrinsic_value = intrinsicValue;

    const upsidePotential = parseNullableOptionalNumber(
        record.upside_potential,
        `${context}.upside_potential`
    );
    if (upsidePotential !== undefined) parsed.upside_potential = upsidePotential;

    const keyMetrics = parseKeyMetrics(record.key_metrics, `${context}.key_metrics`);
    if (keyMetrics !== undefined) parsed.key_metrics = keyMetrics;

    const signalState = parseSignalState(
        record.signal_state,
        `${context}.signal_state`
    );
    if (signalState !== undefined) parsed.signal_state = signalState;

    const distributionSummary = parseDistributionSummary(
        record.distribution_summary,
        `${context}.distribution_summary`
    );
    if (distributionSummary !== undefined) {
        parsed.distribution_summary = distributionSummary;
    }

    const distributionScenarios = parseDistributionScenarios(
        record.distribution_scenarios,
        `${context}.distribution_scenarios`
    );
    if (distributionScenarios !== undefined) {
        parsed.distribution_scenarios = distributionScenarios;
    }

    const valuationDiagnostics = parseValuationDiagnostics(
        record.valuation_diagnostics,
        `${context}.valuation_diagnostics`
    );
    if (valuationDiagnostics !== undefined) {
        parsed.valuation_diagnostics = valuationDiagnostics;
    }

    const assumptionBreakdown = parseAssumptionBreakdown(
        record.assumption_breakdown,
        `${context}.assumption_breakdown`
    );
    if (assumptionBreakdown !== undefined) {
        parsed.assumption_breakdown = assumptionBreakdown;
    }

    const dataFreshness = parseDataFreshness(
        record.data_freshness,
        `${context}.data_freshness`
    );
    if (dataFreshness !== undefined) {
        parsed.data_freshness = dataFreshness;
    }

    const assumptionRiskLevel = parseNullableOptionalString(
        record.assumption_risk_level,
        `${context}.assumption_risk_level`
    );
    if (assumptionRiskLevel !== undefined) {
        parsed.assumption_risk_level = assumptionRiskLevel;
    } else if (assumptionBreakdown?.assumption_risk_level !== undefined) {
        parsed.assumption_risk_level = assumptionBreakdown.assumption_risk_level;
    }

    const dataQualityFlags = parseOptionalStringArray(
        record.data_quality_flags,
        `${context}.data_quality_flags`
    );
    if (dataQualityFlags !== undefined) {
        parsed.data_quality_flags = dataQualityFlags;
    } else if (assumptionBreakdown?.data_quality_flags !== undefined) {
        parsed.data_quality_flags = assumptionBreakdown.data_quality_flags;
    }

    const timeAlignmentStatus = parseNullableOptionalString(
        record.time_alignment_status,
        `${context}.time_alignment_status`
    );
    if (timeAlignmentStatus !== undefined) {
        parsed.time_alignment_status = timeAlignmentStatus;
    } else if (assumptionBreakdown?.time_alignment_status !== undefined) {
        parsed.time_alignment_status = assumptionBreakdown.time_alignment_status;
    }

    const forwardSignalSummary = parseForwardSignalSummary(
        record.forward_signal_summary,
        `${context}.forward_signal_summary`
    );
    if (forwardSignalSummary !== undefined) {
        parsed.forward_signal_summary = forwardSignalSummary;
    } else if (assumptionBreakdown?.forward_signal_summary !== undefined) {
        parsed.forward_signal_summary = assumptionBreakdown.forward_signal_summary;
    }

    const forwardSignalRiskLevel = parseNullableOptionalString(
        record.forward_signal_risk_level,
        `${context}.forward_signal_risk_level`
    );
    if (forwardSignalRiskLevel !== undefined) {
        parsed.forward_signal_risk_level = forwardSignalRiskLevel;
    } else if (assumptionBreakdown?.forward_signal_risk_level !== undefined) {
        parsed.forward_signal_risk_level = assumptionBreakdown.forward_signal_risk_level;
    }

    const forwardSignalEvidenceCount = parseNullableOptionalNumber(
        record.forward_signal_evidence_count,
        `${context}.forward_signal_evidence_count`
    );
    if (forwardSignalEvidenceCount !== undefined) {
        parsed.forward_signal_evidence_count = forwardSignalEvidenceCount;
    } else if (assumptionBreakdown?.forward_signal_evidence_count !== undefined) {
        parsed.forward_signal_evidence_count =
            assumptionBreakdown.forward_signal_evidence_count;
    }

    const reports = parseFinancialReports(
        record.financial_reports,
        `${context}.financial_reports`
    );
    if (reports !== undefined) parsed.financial_reports = reports;

    return parsed;
};
