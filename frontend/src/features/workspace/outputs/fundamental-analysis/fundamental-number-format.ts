export type NumberSemantic =
    | { kind: 'money' | 'per-share'; currency: string }
    | { kind: 'ratio' | 'beta' | 'shares' | 'count' | 'year' | 'percentage-points' | 'basis-points' }
    | { kind: 'unclassified'; unit: string };

export type ReportDatum =
    | { kind: 'number'; raw: string; semantic: NumberSemantic }
    | { kind: 'boolean'; value: boolean }
    | { kind: 'unavailable'; status: 'missing' | 'not_applicable' | 'unsupported' | 'unresolved'; reason: string };

type Decimal = { negative: boolean; digits: string; exponent: bigint };
type FormatContext = { precision?: number; moneyScale?: 0 | 6 | 9 | 12; includeUnit?: boolean };

const MONEY_FIELDS = new Set([
    'revenue', 'cash_and_equivalents', 'income_before_tax', 'income_tax_expense', 'inventory',
    'net_income', 'operating_current_payables', 'operating_current_receivables', 'operating_income',
    'operating_lease_cost', 'current_finance_lease_liabilities', 'current_operating_lease_liabilities',
    'long_term_finance_lease_liabilities', 'long_term_interest_bearing_debt', 'long_term_operating_lease_liabilities',
    'restricted_stock_nonvested_aggregate_unrecognized_compensation', 'total_assets', 'total_liabilities',
    'total_equity', 'capital_expenditures', 'depreciation_and_amortization', 'operating_cash_flow',
]);
const SHARE_FIELDS = new Set(['basic_weighted_average_shares', 'diluted_weighted_average_shares', 'common_shares_outstanding', 'restricted_stock_nonvested_aggregate_quantity']);
const RATE_PATHS = new Set([
    'assumptions.terminal_growth', 'assumptions.wacc', 'assumptions.wacc.tax_rate',
    'assumptions.wacc.risk_free_rate', 'assumptions.wacc.equity_risk_premium',
    'assumptions.wacc.pre_tax_cost_of_debt', 'assumptions.wacc.debt_weight', 'assumptions.wacc.equity_weight',
]);
const CAPITAL_MONEY_PATHS = new Set(['cash', 'non_operating_assets', 'debt', 'preferred_stock', 'lease_liabilities', 'non_controlling_interest'].map((key) => `assumptions.capital_bridge.${key}`));

export function factNumberSemantic(field: string, currency: string | null, unit: string): NumberSemantic {
    if (SHARE_FIELDS.has(field)) return { kind: 'shares' };
    if (MONEY_FIELDS.has(field) && currency) return { kind: 'money', currency };
    if (field === 'fiscal_year') return { kind: 'year' };
    return { kind: 'unclassified', unit };
}

export function assumptionNumberSemantic(path: string, currency: string): NumberSemantic {
    if (path === 'assumptions.wacc.beta') return { kind: 'beta' };
    if (RATE_PATHS.has(path) || /^assumptions\.forecast\.(revenue_growth|operating_margin|reinvestment_rate)\[[0-4]\]$/.test(path)) return { kind: 'ratio' };
    if (path === 'assumptions.capital_bridge.diluted_shares') return { kind: 'shares' };
    if (path === 'assumptions.forecast.base_revenue' || CAPITAL_MONEY_PATHS.has(path)) return { kind: 'money', currency };
    return { kind: 'unclassified', unit: '' };
}

export function nodeNumberSemantic(nodeId: string, unit: string, currency: string): NumberSemantic {
    if (unit === 'rate' || unit === 'ratio') return { kind: 'ratio' };
    if (unit === 'currency/share' || unit === `${currency}/share` || unit === `${currency} / share`) return { kind: 'per-share', currency };
    if (unit === 'currency' || unit === currency || unit === `iso4217:${currency}`) return { kind: 'money', currency };
    if (unit === 'shares' || unit === 'xbrli:shares') return { kind: 'shares' };
    if (nodeId === 'beta') return { kind: 'beta' };
    return { kind: 'unclassified', unit };
}

function decimal(raw: string): Decimal {
    const match = /^([+-]?)(\d*)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/.exec(raw);
    if (!match || !(match[2] || match[3])) throw new TypeError('Expected a canonical finite Decimal string.');
    const fraction = match[3] ?? '';
    const digits = `${match[2]}${fraction}`.replace(/^0+/, '') || '0';
    return { negative: match[1] === '-' && digits !== '0', digits, exponent: BigInt(match[4] ?? '0') - BigInt(fraction.length) };
}

function shifted(value: Decimal, exponent: number): Decimal {
    return { ...value, exponent: value.exponent + BigInt(exponent) };
}

function coefficient(value: Decimal, precision: number): bigint {
    const shift = value.exponent + BigInt(precision);
    if (value.digits === '0') return BigInt(0);
    if (shift >= BigInt(0)) return BigInt(value.digits + '0'.repeat(Number(shift)));
    const keep = BigInt(value.digits.length) + shift;
    if (keep < BigInt(0)) return BigInt(0);
    const index = Number(keep);
    const kept = BigInt(value.digits.slice(0, index) || '0');
    return kept + ((value.digits[index] ?? '0') >= '5' ? BigInt(1) : BigInt(0));
}

function scientific(value: Decimal): string {
    if (value.digits === '0') return '0.00';
    let magnitude = BigInt(value.digits.length - 1) + value.exponent;
    let rounded = BigInt(value.digits.slice(0, 3).padEnd(3, '0'));
    if ((value.digits[3] ?? '0') >= '5') rounded += BigInt(1);
    if (rounded >= BigInt(1000)) { rounded = BigInt(100); magnitude += BigInt(1); }
    const digits = String(rounded).padStart(3, '0');
    return `${value.negative ? '−' : ''}${digits[0]}.${digits.slice(1)}e${magnitude < BigInt(0) ? '−' : '+'}${magnitude < BigInt(0) ? -magnitude : magnitude}`;
}

function fixed(value: Decimal, precision: number): string {
    const rounded = coefficient(value, precision);
    const digits = String(rounded).padStart(precision + 1, '0');
    const integer = (precision ? digits.slice(0, -precision) : digits).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    return `${value.negative && rounded !== BigInt(0) ? '−' : ''}${integer}${precision ? `.${digits.slice(-precision)}` : ''}`;
}

function nonzeroPrecision(value: Decimal, preferred: number): number | null {
    if (magnitude(value) >= BigInt(0)) return preferred;
    if (value.digits === '0' || coefficient(value, preferred) !== BigInt(0)) return preferred;
    return coefficient(value, 6) === BigInt(0) ? null : 6;
}

function magnitude(value: Decimal): bigint {
    return value.digits === '0' ? BigInt(0) : BigInt(value.digits.length - 1) + value.exponent;
}

export function formatReportNumber(raw: string, semantic: NumberSemantic, context: FormatContext = {}): string {
    if (semantic.kind === 'unclassified') return `${raw}${semantic.unit ? ` ${semantic.unit}` : ''} · Format not defined`;
    const original = decimal(raw);
    if (semantic.kind === 'year') return `FY${fixed(original, 0).replaceAll(',', '')}`;
    const isMoney = semantic.kind === 'money' || semantic.kind === 'per-share';
    const unit = context.includeUnit !== false;
    const prefix = isMoney && unit ? `${semantic.currency} ` : '';
    const suffix = semantic.kind === 'ratio' ? '%' : semantic.kind === 'percentage-points' ? ' percentage points'
        : semantic.kind === 'basis-points' ? ' bps' : semantic.kind === 'shares' && unit ? ' shares'
            : semantic.kind === 'per-share' && unit ? ' / share' : '';
    const rateShift = semantic.kind === 'ratio' || semantic.kind === 'percentage-points' ? 2 : semantic.kind === 'basis-points' ? 4 : 0;
    let scale = context.moneyScale ?? 0;
    const compact = context.moneyScale === undefined && (semantic.kind === 'money' || semantic.kind === 'shares');
    if (compact) {
        const power = magnitude(original);
        scale = power >= BigInt(12) ? 12 : power >= BigInt(9) ? 9 : power >= BigInt(6) ? 6 : 0;
    }
    let value = shifted(original, rateShift - scale);
    if (semantic.kind !== 'count' && magnitude(original) >= BigInt(15)) return `${prefix}${scientific(context.moneyScale === undefined ? shifted(original, rateShift) : value)}${suffix}`;
    const preferred = context.precision ?? (semantic.kind === 'count' ? 0 : 2);
    let precision = context.precision ?? nonzeroPrecision(value, preferred);
    if (compact && scale < 12 && scale > 0 && precision !== null && coefficient(value, precision) >= BigInt(1000) * (BigInt(10) ** BigInt(precision))) {
        scale = scale === 6 ? 9 : 12;
        value = shifted(original, -scale);
        precision = context.precision ?? nonzeroPrecision(value, preferred);
    }
    const scaleSuffix = context.moneyScale === undefined && scale ? scale === 12 ? 'T' : scale === 9 ? 'B' : 'M' : '';
    const text = precision === null || (original.digits !== '0' && coefficient(value, precision) === BigInt(0)) ? scientific(value) : fixed(value, precision);
    return `${prefix}${text}${scaleSuffix}${suffix}`;
}

export function formatReportDatum(datum: ReportDatum): string {
    switch (datum.kind) {
        case 'number': return formatReportNumber(datum.raw, datum.semantic);
        case 'boolean': return String(datum.value);
        case 'unavailable': return `${datum.status === 'not_applicable' ? 'Not applicable' : datum.status === 'missing' ? 'Missing' : 'Unavailable'} · ${datum.reason}`;
        default: { const exhaustive: never = datum; return exhaustive; }
    }
}

export function formatReportSeries(raws: readonly string[], semantic: NumberSemantic, moneyScale: 0 | 6 | 9 | 12 = 9) {
    const shift = semantic.kind === 'ratio' ? 2 : semantic.kind === 'money' ? -moneyScale : 0;
    const needsPrecision = raws.some((raw) => nonzeroPrecision(shifted(decimal(raw), shift), 2) !== 2);
    const precision = needsPrecision ? 6 : 2;
    return {
        precision,
        note: needsPrecision ? 'Small nonzero values use six decimal places or scientific notation.' : 'Displayed values are rounded to two decimal places.',
        values: raws.map((raw) => formatReportNumber(raw, semantic, { precision, moneyScale, includeUnit: false })),
    };
}
