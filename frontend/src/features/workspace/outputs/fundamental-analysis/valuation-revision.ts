import type { components } from '@/types/generated/api-contract';
import type { FundamentalReportModel } from './fundamental-report-model';

export const TERMINAL_GROWTH_FIELD = {
    path: 'assumptions.terminal_growth',
    label: 'Terminal growth',
    unit: '%',
} satisfies {
    path: components['schemas']['FundamentalValuationRevisionV1']['path'];
    label: string;
    unit: '%';
};

export type FundamentalRevisionSource = components['schemas']['FundamentalValuationRevisionSourceV1'];
export type FundamentalRevision = components['schemas']['FundamentalValuationRevisionV1'];
export type FundamentalRevisionControl =
    | { kind: 'read-only'; reason: string }
    | {
          kind: 'available';
          isPending: boolean;
          pendingSource: FundamentalRevisionSource | null;
          onRecalculate: (revision: FundamentalRevision, sourceTicker: string) => Promise<void>;
      };

export type ValuationRevisionContext = {
    canApplyResearch: boolean;
    source: FundamentalRevisionSource;
    sourceKey: string;
    savedValue: string;
    ticker: string;
    issuerId: string;
    modelId: 'fcff_dcf' | 'transition_fcff_dcf';
    valuationTimestamp: string;
};
export type ValuationRevisionAvailability =
    { kind: 'available'; context: ValuationRevisionContext } | { kind: 'read-only'; reason: string };

export function valuationRevisionAvailability(report: FundamentalReportModel): ValuationRevisionAvailability {
    if (report.kind !== 'valuation' || !report.preparationSummary)
        return { kind: 'read-only', reason: 'This report has no prepared valuation to revise.' };
    const preparation = report.preparationSummary;
    if (
        preparation.status !== 'prepared' ||
        preparation.isRevised ||
        report.issueCodes.includes('MANUAL_OVERRIDE_APPLIED')
    )
        return {
            kind: 'read-only',
            reason: 'Revised and manual reports are read-only. Start from an original automatic report for one revision.',
        };
    const fields = preparation.assumptions.filter((item) => item.path === TERMINAL_GROWTH_FIELD.path);
    const field = fields[0];
    if (fields.length !== 1 || !field?.editable || field.isManual)
        return {
            kind: 'read-only',
            reason: 'The service has not made terminal growth editable for this preparation.',
        };
    const { threadId, runId, artifactId, preparationDigest } = report.identity;
    if (!threadId || !runId || !artifactId || !preparationDigest || !report.issuerId)
        return { kind: 'read-only', reason: 'The saved source identity is incomplete.' };
    const source = {
        thread_id: threadId,
        run_id: runId,
        artifact_id: artifactId,
        preparation_digest: preparationDigest,
    };
    return {
        kind: 'available',
        context: {
            canApplyResearch: preparation.canApplyResearch,
            source,
            sourceKey: JSON.stringify(source),
            savedValue: field.value.raw,
            ticker: report.ticker,
            issuerId: report.issuerId,
            modelId: preparation.modelId,
            valuationTimestamp: report.base.valuationDate,
        },
    };
}

function normalizeDecimal(value: string): string {
    const negative = value.startsWith('-');
    const unsigned = value.replace(/^[+-]/, '');
    const [whole = '', fraction = ''] = unsigned.split('.');
    const integer = (whole || '0').replace(/^0+(?=\d)/, '');
    const decimal = fraction.replace(/0+$/, '');
    const magnitude = decimal ? `${integer}.${decimal}` : integer;
    return negative && magnitude !== '0' ? `-${magnitude}` : magnitude;
}

function shiftDecimal(value: string, shift: 2 | -2): string {
    const input = value.trim();
    if (!/^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$/.test(input))
        throw new TypeError('Enter a finite decimal percentage.');
    const [mantissa = '', exponent] = input.toLowerCase().split('e');
    if (exponent !== undefined) {
        const power = BigInt(exponent) + BigInt(shift);
        const normalized = normalizeDecimal(mantissa);
        return normalized === '0' || power === BigInt(0) ? normalized : `${normalized}e${power}`;
    }
    const sign = mantissa.startsWith('-') ? '-' : '';
    const [whole = '', fraction = ''] = mantissa.replace(/^[+-]/, '').split('.');
    if (shift === 2)
        return normalizeDecimal(`${sign}${whole}${fraction.slice(0, 2).padEnd(2, '0')}.${fraction.slice(2)}`);
    const padded = whole.padStart(3, '0');
    return normalizeDecimal(`${sign}${padded.slice(0, -2)}.${padded.slice(-2)}${fraction}`);
}

export const ratioToPercentText = (value: string): string => shiftDecimal(value, 2);
export const percentTextToRatio = (value: string): string => shiftDecimal(value, -2);
