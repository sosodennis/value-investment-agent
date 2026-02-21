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
    diagnostics?: Record<string, number | boolean>;
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

export interface ParsedAssumptionItem {
    statement: string;
    category?: string;
    severity?: string;
}

export interface ParsedAssumptionBreakdown {
    total_assumptions?: number;
    assumptions?: ParsedAssumptionItem[];
    key_parameters?: Record<string, string | number | boolean>;
    monte_carlo?: Record<string, string | number | boolean>;
}

export interface ParsedDataFreshnessFinancialStatement {
    fiscal_year?: number;
    period_end_date?: string;
}

export interface ParsedDataFreshnessMarketData {
    provider?: string;
    as_of?: string;
    missing_fields?: string[];
}

export interface ParsedDataFreshness {
    financial_statement?: ParsedDataFreshnessFinancialStatement;
    market_data?: ParsedDataFreshnessMarketData;
    shares_outstanding_source?: string;
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
    assumption_breakdown?: ParsedAssumptionBreakdown;
    data_freshness?: ParsedDataFreshness;
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
): Record<string, number | boolean> | undefined => {
    if (value === undefined || value === null) return undefined;
    const record = toRecord(value, context);
    const parsed: Record<string, number | boolean> = {};
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
        if (typeof rawValue !== 'number' && typeof rawValue !== 'boolean') {
            throw new TypeError(`${context}.${key} must be a number | boolean.`);
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
        parsed.market_data = marketData;
    }

    const sharesOutstandingSource = parseNullableOptionalString(
        record.shares_outstanding_source,
        `${context}.shares_outstanding_source`
    );
    if (sharesOutstandingSource !== undefined) {
        parsed.shares_outstanding_source = sharesOutstandingSource;
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

    const reports = parseFinancialReports(
        record.financial_reports,
        `${context}.financial_reports`
    );
    if (reports !== undefined) parsed.financial_reports = reports;

    return parsed;
};
