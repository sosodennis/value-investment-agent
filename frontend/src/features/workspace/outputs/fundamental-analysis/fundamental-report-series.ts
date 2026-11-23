import type { EvidenceSelection } from '../../workspace-evidence-inspector';
import { exactNumber, type ExactNumber, type FundamentalFactModel, type FundamentalReportModel, type FundamentalValuationModel } from './fundamental-report-model';

export type ReportSeriesPoint = { label: string; value: ExactNumber | null; evidence: EvidenceSelection | null };
export type ReportSeries = { id: string; label: string; currency: string; points: ReportSeriesPoint[] };
export type HistoricalSeries =
    | { kind: 'comparable'; series: ReportSeries; periods: string[] }
    | { kind: 'unavailable'; id: string; label: string; reasons: string[] };

const FORECAST_FIELDS = [
    { id: 'revenue', label: 'Revenue' },
    { id: 'fcff', label: 'Free cash flow to firm' },
    { id: 'discounted_fcff', label: 'Discounted FCFF' },
];
const HISTORY_FIELDS = [
    { id: 'revenue', label: 'Revenue' },
    { id: 'operating_income', label: 'Operating income' },
    { id: 'net_income', label: 'Net income' },
];

export function projectForecastSeries(report: FundamentalValuationModel): ReportSeries[] {
    return FORECAST_FIELDS.map((field) => ({
        ...field,
        currency: report.currency ?? '',
        points: Array.from({ length: 5 }, (_, index) => {
            const node = report.base.nodes.find((item) => item.id === `${field.id}_${index + 1}`);
            const usable = node?.semantic.kind === 'money' && node.semantic.currency === report.currency;
            return { label: `Year ${index + 1}`, value: usable ? node.value : null, evidence: node?.evidence ?? null };
        }),
    }));
}

function dimensionKey(fact: FundamentalFactModel): string {
    return JSON.stringify(fact.dimensions.map((item) => [item.name, item.member]).sort(([a], [b]) => a.localeCompare(b)));
}

function contextKey(fact: FundamentalFactModel): string {
    const context = fact.context;
    return JSON.stringify([
        context.issuerId, context.securityId, context.securityScope, context.entityScope, context.consolidationScope,
        context.periodType, fact.currency, fact.unit, context.unitQname, context.measure, context.conceptQname, dimensionKey(fact),
    ]);
}

function durationDays(fact: FundamentalFactModel): number | null {
    return fact.context.start === null ? null : (Date.parse(fact.context.end) - Date.parse(fact.context.start)) / 86400000 + 1;
}

function comparableHistory(report: FundamentalReportModel, field: typeof HISTORY_FIELDS[number]): HistoricalSeries {
    const facts = report.facts.filter((fact) => fact.normalizedField === field.id).sort((a, b) => a.context.end.localeCompare(b.context.end));
    const reasons = new Set<string>();
    const first = facts[0];
    if (facts.some((fact) => fact.context.periodType !== 'duration')) reasons.add('Revenue and income trends require annual duration periods.');
    if (facts.length < 2) reasons.add('At least two comparable annual periods are required.');
    if (first && facts.some((fact) => contextKey(fact) !== contextKey(first))) reasons.add('Issuer, security, consolidation, currency, unit, period type, concept or dimensions differ.');
    if (facts.some((fact) => fact.context.issuerId !== report.issuerId || fact.context.entityScope !== fact.context.issuerId || fact.context.consolidationScope !== 'consolidated')) reasons.add('Consolidated issuer coverage is not established.');
    if (facts.some((fact) => fact.value.kind !== 'number' || fact.value.semantic.kind !== 'money')) reasons.add('A numeric monetary value is missing or has unsupported units.');
    if (facts.some((fact) => !fact.context.accession || !fact.context.filingVersion)) reasons.add('Filing version or accession metadata is unavailable.');
    if (facts.some((fact) => fact.context.isAmendment && (!fact.context.amendsAccession || fact.context.amendmentScope !== 'valuation_relevant'))) reasons.add('Amendment lineage is unresolved.');
    if (new Set(facts.map((fact) => fact.context.end)).size !== facts.length) reasons.add('Multiple facts or filing versions cover the same period.');
    if (facts.some((fact) => fact.context.periodType === 'duration' && ((durationDays(fact) ?? 0) < 350 || (durationDays(fact) ?? 0) > 380))) reasons.add('Annual duration coverage is incomplete or inconsistent.');
    if (facts.some((fact, index) => {
        if (index === 0) return false;
        const previous = facts[index - 1];
        const spacing = (Date.parse(fact.context.end) - Date.parse(previous.context.end)) / 86400000;
        return spacing < 350 || spacing > 380 || (fact.context.start !== null && fact.context.start <= previous.context.end);
    })) reasons.add('The annual history contains a coverage gap or overlapping periods.');
    if (reasons.size > 0 || !first) return { kind: 'unavailable', ...field, reasons: [...reasons] };
    return {
        kind: 'comparable', periods: facts.map((fact) => fact.period),
        series: {
            ...field, currency: first.currency ?? '',
            points: facts.map((fact) => ({ label: fact.context.end, value: fact.value.kind === 'number' ? exactNumber(fact.value.raw) : null, evidence: fact.evidence })),
        },
    };
}

export function projectHistoricalSeries(report: FundamentalReportModel): HistoricalSeries[] {
    return HISTORY_FIELDS.map((field) => comparableHistory(report, field));
}
