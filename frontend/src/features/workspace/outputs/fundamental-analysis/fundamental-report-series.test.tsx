import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { parseFundamentalServiceArtifact } from '@/types/agents/fundamental-service-facts';
import { projectFundamentalReport } from './fundamental-report-model';
import { projectForecastSeries, projectHistoricalSeries } from './fundamental-report-series';
import { calculation, canonicalFact, factsOnlyReport, reference, valuationReport } from './fundamental-report.test-fixtures';
import { ValuationForecast, ValuationHistory } from './valuation-series';

function project(artifact: unknown) {
    return projectFundamentalReport({ artifact: parseFundamentalServiceArtifact(artifact), reference, threadId: 'thread-1', ticker: 'EXAMPLE' });
}
function annualFact(year: number, overrides: Parameters<typeof canonicalFact>[0] = {}) {
    const fact = canonicalFact();
    return canonicalFact({
        fact_id: `revenue-${year}`, value: `${year}000000000`, accession_number: `filing-${year}`, filing_version: 'original',
        period_start: `${year}-01-01`, period_end: `${year}-12-31`,
        context: { ...fact.context, start_date: `${year}-01-01`, end_date: `${year}-12-31`, dimensions: [] }, ...overrides,
    });
}
function historicalReport(facts: ReturnType<typeof canonicalFact>[]) {
    const source = factsOnlyReport();
    source.facts.facts = facts;
    source.facts.fact_ids = facts.map((fact) => fact.fact_id);
    source.fact_ids = source.facts.fact_ids;
    return project(source);
}

describe('Fundamental series reading', () => {
    afterEach(cleanup);
    it('uses supplied forecast nodes and leaves a missing middle year as a gap with exact evidence', () => {
        const source = valuationReport();
        const node = calculation().nodes[0];
        if (!node) throw new Error('Expected node fixture.');
        source.service_result = calculation({ nodes: [
            { ...node, node_id: 'revenue_1', value: '331839000000', unit: 'currency' },
            { ...node, node_id: 'revenue_3', value: '30000', unit: 'currency' },
            { ...node, node_id: 'fcff_1', value: '-1000000000', unit: 'currency' },
        ] });
        const report = project(source);
        if (report.kind !== 'valuation') throw new Error('Expected valuation.');
        const series = projectForecastSeries(report);
        expect(series[0]?.points.map((point) => point.value?.raw ?? null)).toEqual(['331839000000', null, '30000', null, null]);
        const onSelectEvidence = vi.fn();
        render(<ValuationForecast report={report} onSelectEvidence={onSelectEvidence} />);
        const chart = screen.getByRole('figure', { name: 'Revenue trend' });
        expect(chart.querySelectorAll('circle')).toHaveLength(2);
        expect(chart.querySelectorAll('g line')).toHaveLength(0);
        screen.getByText('331.839000');
        screen.getByText('0.000030');
        const table = within(screen.getByRole('region', { name: 'Forecast annual values' }));
        expect(table.getAllByRole('row')).toHaveLength(6);
        fireEvent.click(table.getByRole('button', { name: 'Inspect Calculation · revenue_3' }));
        expect(onSelectEvidence).toHaveBeenCalledWith(expect.objectContaining({ value: '30000', unit: 'currency', displayValue: '0.000030 USD B', inputDigest: report.base.binding.inputDigest, resultHash: report.base.binding.resultHash }));
        expect(screen.queryByText('FY2027')).toBeNull();
    });

    it('permits comparable annual history across distinct filing accessions and retains source periods', () => {
        const report = historicalReport([annualFact(2024), annualFact(2025)]);
        const history = projectHistoricalSeries(report)[0];
        expect(history?.kind).toBe('comparable');
        render(<ValuationHistory report={report} />);
        screen.getByRole('figure', { name: 'Revenue trend' });
        screen.getByText('2024-01-01 → 2024-12-31; 2025-01-01 → 2025-12-31', { exact: false });
    });

    it('rejects consistently instant revenue facts rather than treating snapshots as income periods', () => {
        const facts = [2024, 2025].map((year) => {
            const fact = annualFact(year);
            return { ...fact, instant: `${year}-12-31`, context: { ...fact.context, period_type: 'instant', instant: `${year}-12-31`, start_date: null, end_date: null } } satisfies ReturnType<typeof canonicalFact>;
        });
        const history = projectHistoricalSeries(historicalReport(facts))[0];
        expect(history).toMatchObject({ kind: 'unavailable', reasons: expect.arrayContaining(['Revenue and income trends require annual duration periods.']) });
    });
    it.each([
        ['currency', annualFact(2025, { currency: 'EUR' })],
        ['unit', annualFact(2025, { unit: 'shares' })],
        ['dimensions', annualFact(2025, { context: { ...annualFact(2025).context, dimensions: [{ name: 'SegmentAxis', member: 'CloudMember' }] } })],
        ['consolidation', annualFact(2025, { context: { ...annualFact(2025).context, consolidation_scope: 'parent' } })],
        ['issuer', annualFact(2025, { issuer_id: 'other-issuer' })],
        ['filing version', annualFact(2025, { filing_version: null })],
        ['instant', annualFact(2025, { instant: '2025-12-31', context: { ...annualFact(2025).context, period_type: 'instant', instant: '2025-12-31', start_date: null, end_date: null } })],
        ['duration', annualFact(2025, { period_start: '2025-10-01', context: { ...annualFact(2025).context, start_date: '2025-10-01' } })],
        ['amendment', annualFact(2025, { is_amendment: true, amendment_scope: 'unknown' })],
        ['gap', annualFact(2026)],
        ['duplicate period', annualFact(2024, { fact_id: 'alternative-version', filing_version: 'restated' })],
    ] as const)('withholds a trend for incompatible %s and explains why', (_reason, fact) => {
        const report = historicalReport([annualFact(2024), fact]);
        const history = projectHistoricalSeries(report)[0];
        expect(history?.kind).toBe('unavailable');
        render(<ValuationHistory report={report} />);
        expect(screen.queryByRole('figure', { name: 'Revenue trend' })).toBeNull();
        screen.getByText('Revenue · trend unavailable');
        expect(screen.getAllByText(/Full facts remain available below/).length).toBeGreaterThan(0);
        expect(report.facts).toHaveLength(2);
    });
});
