import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { parseFundamentalServiceArtifact } from '@/types/agents/fundamental-service-facts';
import { projectFundamentalReport } from './fundamental-report-model';
import { calculation, conditionalQuantileBasis, reference, uncertaintyReport } from './fundamental-report.test-fixtures';
import { ValuationUncertainty } from './valuation-uncertainty';

function project(source: ReturnType<typeof uncertaintyReport>) {
    const report = projectFundamentalReport({ artifact: parseFundamentalServiceArtifact(source), reference, threadId: 'thread-1', ticker: 'EXAMPLE' });
    if (report.kind !== 'valuation' || report.uncertainty.kind !== 'provided') throw new Error('Expected uncertainty fixture.');
    return { report, uncertainty: report.uncertainty };
}

describe('Valuation chart evidence interactions', () => {
    afterEach(cleanup);

    it('reads quantiles on hover and focus and activates their own evidence independently of Base', () => {
        const { report, uncertainty } = project(uncertaintyReport({ base: calculation({ per_share_value: '229.8824253968596' }) }));
        const inspect = vi.fn();
        render(<ValuationUncertainty report={report} onSelectEvidence={inspect} />);
        const chart = within(screen.getByRole('figure', { name: 'Service quantile markers' }));
        const readout = chart.getByRole('status', { name: 'Valuation selected point' });
        const median = chart.getByRole('button', { name: 'Inspect P50 · USD 26.12 / share' });
        fireEvent.mouseEnter(median);
        expect(readout.textContent).toContain('P50');
        expect(readout.textContent).toContain('USD 26.12 / share');
        fireEvent.click(median);
        expect(inspect).toHaveBeenLastCalledWith(uncertainty.quantiles.find((item) => item.label === 'p50')?.evidence);
        const base = chart.getByRole('button', { name: 'Inspect Deterministic base · USD 229.88 / share' });
        fireEvent.focus(base);
        expect(readout.textContent).toContain('Deterministic base');
        fireEvent.click(base);
        expect(inspect).toHaveBeenLastCalledWith(report.base.perShare?.evidence);
        expect(inspect.mock.calls[0][0].resultHash).not.toBe(inspect.mock.calls[1][0].resultHash);
    });

    it('keeps equal zero quantiles independently operable and filters only declared aliases', () => {
        const { report, uncertainty } = project(uncertaintyReport({ base: calculation({ per_share_value: '0' }), quantiles: { p05: '0', p50: '0', p95: '0', lower: '0', median: '0', upper: '0' }, quantile_basis: conditionalQuantileBasis }));
        const inspect = vi.fn();
        render(<ValuationUncertainty report={report} onSelectEvidence={inspect} />);
        const chart = within(screen.getByRole('figure', { name: 'Service quantile markers' }));
        expect(chart.getAllByRole('button')).toHaveLength(4);
        for (const label of ['p05', 'p50', 'p95']) {
            const point = chart.getByRole('button', { name: `Inspect ${label.toUpperCase()} · USD 0.00 / share` });
            fireEvent.focus(point);
            expect(chart.getByRole('status', { name: 'Valuation selected point' }).textContent).toContain(label.toUpperCase());
            fireEvent.click(point);
            expect(inspect).toHaveBeenLastCalledWith(uncertainty.quantiles.find((item) => item.label === label)?.evidence);
        }
        expect(new Set(inspect.mock.calls.map(([evidence]) => evidence.id)).size).toBe(3);
    });

    it('retains a single supplied quantile without inventing a median or range', () => {
        const { report } = project(uncertaintyReport({ quantiles: { p05: '20' } }));
        render(<ValuationUncertainty report={report} onSelectEvidence={vi.fn()} />);
        const chart = within(screen.getByRole('figure', { name: 'Service quantile markers' }));
        chart.getByRole('button', { name: 'Inspect P05 · USD 20.00 / share' });
        expect(chart.queryByRole('button', { name: /P50|P95/ })).toBeNull();
        expect(chart.queryByRole('img', { name: 'Supplied P05–P95 interval' })).toBeNull();
    });
});
