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

export interface ParsedFinancialPreview {
    ticker?: string;
    valuation_score?: number;
    key_metrics?: Record<string, string>;
    signal_state?: ParsedSignalState;
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

    const keyMetrics = parseKeyMetrics(record.key_metrics, `${context}.key_metrics`);
    if (keyMetrics !== undefined) parsed.key_metrics = keyMetrics;

    const signalState = parseSignalState(
        record.signal_state,
        `${context}.signal_state`
    );
    if (signalState !== undefined) parsed.signal_state = signalState;

    const reports = parseFinancialReports(
        record.financial_reports,
        `${context}.financial_reports`
    );
    if (reports !== undefined) parsed.financial_reports = reports;

    return parsed;
};
