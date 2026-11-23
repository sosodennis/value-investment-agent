import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SWRConfig } from 'swr';
import { FundamentalAnalysisOutput, FundamentalReport } from './fundamental-analysis-output';
import { parseFundamentalServiceArtifact } from '@/types/agents/fundamental-service-facts';
import { projectFundamentalReport } from './fundamental-report-model';
import { calculation, conditionalQuantileBasis, factsOnlyReport, preparationOutcome, reference, uncertaintyReport, valuationReport } from './fundamental-report.test-fixtures';
import { editableReport } from './valuation-revision.test-fixtures';

function model(artifact: unknown) {
    return projectFundamentalReport({ artifact: parseFundamentalServiceArtifact(artifact), reference, threadId: 'thread-1', ticker: 'EXAMPLE' });
}

describe('Fundamental report', () => {
    afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
    it.each([true, false])('distinguishes retained and manual terminal-growth sources with application confirmed=%s', (confirmed) => {
        const source = editableReport();
        const automatic = source.automatic_preparation;
        if (!automatic) throw new Error('Expected preparation fixture.');
        const original = automatic.assumptions_evidence[0];
        if (!original) throw new Error('Expected assumption fixture.');
        automatic.input = confirmed ? { assumptions: { terminal_growth: '0.025' } } : {};
        automatic.assumptions_evidence = [
            { ...original, value: '0.0492' },
            { ...original, value: '0.025', method: 'manual', manual_provenance: { author: 'user-1', automatic_preparation_digest: automatic.preparation_digest, modified_at: original.as_of, reason: 'Updated outlook.' } },
        ];
        const report = model(source);
        const selectEvidence = vi.fn();
        render(<FundamentalReport report={report} onSelectEvidence={selectEvidence} />);
        const manualLabel = confirmed ? 'Applied manual assumption' : 'Manual assumption · application unconfirmed';
        screen.getByText('Original retained assumption');
        screen.getByText(manualLabel);
        const allAssumptions = within(screen.getByRole('region', { name: 'Assumptions' }));
        fireEvent.click(allAssumptions.getByRole('button', { name: 'Inspect Original retained assumption · assumptions.terminal_growth' }));
        fireEvent.click(allAssumptions.getByRole('button', { name: `Inspect ${manualLabel} · assumptions.terminal_growth` }));
        if (report.kind !== 'valuation') throw new Error('Expected valuation.');
        const rows = report.preparationSummary?.assumptions;
        expect(selectEvidence.mock.calls.map(([item]) => item)).toEqual(rows?.map((item) => item.evidence));
        expect(selectEvidence.mock.calls[0]?.[0]).toMatchObject({ value: '0.0492', title: 'Original retained assumption · assumptions.terminal_growth' });
        expect(selectEvidence.mock.calls[1]?.[0]).toMatchObject({ value: '0.025', title: `${manualLabel} · assumptions.terminal_growth`, author: 'user-1' });
        expect(selectEvidence.mock.calls[0]?.[0].id).not.toBe(selectEvidence.mock.calls[1]?.[0].id);
    });
    it('keeps identity, key assumptions and preparation limitations visible while folding complete inventories', () => {
        const source = editableReport();
        if (!source.automatic_preparation) throw new Error('Expected preparation.');
        source.automatic_preparation.issue_codes = ['CONDITIONAL_CAPITAL_HYPOTHESES', 'HISTORY_WINDOW_PARTIALLY_UNAVAILABLE'];
        source.automatic_preparation.missing_evidence = ['preferred_claims'];
        source.automatic_preparation.conditional_capital = { policy: { complete_capital_claims: false, complete_award_inventory: false, unknowns: ['complete_award_inventory'] } };
        render(<FundamentalReport report={model(source)} />);
        screen.getByText('EXAMPLE · Class A · USD');
        screen.getByText('Valuation date · 2026-11-23T00:00:00Z');
        screen.getByRole('region', { name: 'Key assumptions' });
        const limitation = screen.getByText(/Capital claims or award inventory are incomplete/);
        expect(limitation.closest('details')).toBeNull();
        expect(screen.getByText(/HISTORY_WINDOW_PARTIALLY_UNAVAILABLE/).closest('details')).toBeNull();
        expect(screen.getByText('Missing evidence · preferred_claims').closest('details')).toBeNull();
        expect(screen.getByText('All assumptions (1)').closest('details')?.open).toBe(false);
        expect(screen.getByText('All financial facts (1)').closest('details')?.open).toBe(false);
    });
    it.each(['history', 'revised'] as const)('keeps the %s report read-only even when the service field is editable', async (mode) => {
        const source = editableReport();
        if (mode === 'revised' && source.automatic_preparation) source.automatic_preparation.input = { ...source.automatic_preparation.input, provenance: { conditional_revision_ref: 'source-revision' } };
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
            kind: 'financial_reports', version: 'v1', produced_by: 'fundamental_analysis', created_at: '2026-11-23T00:00:00Z',
            data: { ticker: 'EXAMPLE', model_type: 'fcff_dcf', status: 'done', financial_reports: [], fundamental_service: source },
        }), { status: 200 })));
        await act(async () => render(<SWRConfig value={{ provider: () => new Map() }}><FundamentalAnalysisOutput reference={reference} resolvedTicker="EXAMPLE" status="done" threadId="thread-1" runId="run-1" revisionControl={mode === 'history' ? { kind: 'read-only', reason: 'Historical reports are read-only.' } : { kind: 'available', isPending: false, attempt: null, onRecalculate: vi.fn() }} /></SWRConfig>));
        await screen.findByText(mode === 'history' ? 'Historical reports are read-only.' : 'Revised and manual reports are read-only. Start from an original automatic report for one revision.');
        expect(screen.queryByLabelText('Terminal growth (%)')).toBeNull();
        expect(screen.queryByRole('button', { name: 'Recalculate' })).toBeNull();
    });
    it('labels conditional quantiles and keeps their binding available for inspection', () => {
        render(<FundamentalReport report={model(uncertaintyReport({ quantile_basis: conditionalQuantileBasis }))} />);
        screen.getByText('Conditional on the retained base hypotheses');
        screen.getByText(/Capital and reinvestment hypotheses remain fixed/);
        screen.getByText(`Joint scenarios digest ${conditionalQuantileBasis.joint_scenarios_digest}`);
    });
    it('announces the readable financial value with each source action', () => {
        render(<FundamentalReport report={model(uncertaintyReport())} onSelectEvidence={() => undefined} />);
        const source = screen.getByRole('button', { name: 'Inspect Deterministic base per share' });
        const descriptionId = source.getAttribute('aria-describedby');
        expect(descriptionId && document.getElementById(descriptionId)?.textContent).toBe('USD 25.12 / share');
    });
    it('formats retained historical ratios and money while preserving their exact evidence', () => {
        const source = valuationReport();
        const preparation = source.automatic_preparation;
        if (!preparation) throw new Error('Expected preparation.');
        const metric = preparation.historical_metrics.metrics[0];
        if (!metric) throw new Error('Expected metric fixture.');
        preparation.historical_metrics.metrics = [
            { ...metric, metric_id: 'operating_margin', value: '0.417728123456789', unit: 'ratio' },
            { ...metric, metric_id: 'nopat', value: '123456789012.123456789', unit: 'currency' },
        ];
        const select = vi.fn();
        render(<FundamentalReport report={model(source)} onSelectEvidence={select} />);
        fireEvent.click(screen.getByText('Historical metrics used in preparation'));
        screen.getByText('41.77%');
        screen.getByText('USD 123.46B');
        fireEvent.click(screen.getByRole('button', { name: 'Inspect Historical metric · operating_margin · FY2025' }));
        expect(select).toHaveBeenCalledWith(expect.objectContaining({ value: '0.417728123456789', displayValue: '41.77%', formula: metric.formula, inputs: metric.fact_ids }));
    });
    it('separates formatted sample counts from the unmodified seed identity', () => {
        render(<FundamentalReport report={model(uncertaintyReport({ requested_samples: 10000, valid_samples: 9998, invalid_samples: 2, seed: '10000' }))} />);
        screen.getByText('Samples requested 10,000 · valid 9,998 · invalid 2');
        screen.getByText(/Seed 10000/);
    });
    it('shows canonical MC values and a distinct deterministic base without a synthetic price curve', () => {
        render(<FundamentalReport report={model(uncertaintyReport())} />);
        screen.getByText('Deterministic base per share');
        screen.getByText('USD 25.12 / share');
        screen.getByText('USD 26.12 / share');
        expect(screen.getAllByText('USD 2.50B')).toHaveLength(2);
        screen.getByText('Samples requested 100 · valid 98 · invalid 2');
        screen.getByText(/minimum valid samples 10/);
        screen.getByText('OUT_OF_BOUNDS · 2');
        expect(screen.queryByText(/current price|upside|p25|p75/i)).toBeNull();
        expect(document.querySelector('svg.recharts-surface')).toBeNull();
        expect(screen.queryByRole('button', { name: /recalculate|edit|continue/i })).toBeNull();
        const markers = screen.getByRole('figure', { name: 'Service quantile markers' });
        expect(markers.querySelectorAll('circle')).toHaveLength(3);
        expect(markers.querySelectorAll('path')).toHaveLength(1);
        expect(markers.querySelectorAll('circle title')[1]?.textContent).toBe('p50: 26.1234567890123456789');
    });
    it('keeps the base marker outside P95 and retains equal canonical quantiles while removing contract aliases', () => {
        const source = uncertaintyReport({
            base: calculation({ per_share_value: '229.8824253968596' }),
            quantiles: { p05: '144.665049', p50: '173.100589', p95: '197.999837', lower: '144.665049', median: '173.100589', upper: '197.999837' },
            quantile_basis: conditionalQuantileBasis,
        });
        const { rerender } = render(<FundamentalReport report={model(source)} />);
        screen.getByText('USD 229.88 / share');
        screen.getByText('USD 173.10 / share');
        const markers = screen.getByRole('figure', { name: 'Service quantile markers' });
        const quantilePositions = [...markers.querySelectorAll('circle')].map((circle) => Number(circle.getAttribute('cx')));
        const basePosition = Number(markers.querySelector('path')?.getAttribute('d')?.split(' ')[1]);
        expect(basePosition).toBeGreaterThan(Math.max(...quantilePositions));
        expect(basePosition).toBeLessThanOrEqual(92);
        expect(screen.queryByText('Model quantile LOWER')).toBeNull();
        rerender(<FundamentalReport report={model(uncertaintyReport({ quantiles: { p05: '20', p50: '20', p95: '20' } }))} />);
        screen.getByText('Model quantile P05');
        screen.getByText('Monte Carlo median · P50');
        screen.getByText('Model quantile P95');
        expect(screen.getAllByText('USD 20.00 / share')).toHaveLength(3);
    });
    it('displays huge canonical values and missing per-share values honestly', () => {
        render(<FundamentalReport report={model(valuationReport({ service_result: calculation({ intrinsic_value: '1e400', per_share_value: null }) }))} />);
        screen.getByText('USD 1.00e+400');
        screen.getAllByText('Unavailable');
        expect(screen.queryByText('Infinity')).toBeNull();
    });
    it('keeps a valid base visible with a partial abstaining uncertainty result and no inferred markers', () => {
        render(<FundamentalReport report={model(uncertaintyReport({ status: 'abstain', quantiles: { p05: '1e400' } }))} />);
        screen.getByText('USD 25.12 / share');
        screen.getByText('USD 1.00e+400 / share');
        screen.getAllByText('abstain');
        expect(screen.queryByRole('figure')).toBeNull();
        expect(screen.queryByText('Model quantile p50')).toBeNull();
    });
    it('renders zero-sample scenarios without labeling the result Monte Carlo', () => {
        render(<FundamentalReport report={model(uncertaintyReport({ requested_samples: 0, valid_samples: 0, invalid_samples: 0, quantiles: {}, scenario_results: [calculation()] }))} />);
        screen.getByText('Scenario and sensitivity results · no Monte Carlo samples requested in this result');
        screen.getByText('Scenario 1 · completed · provisional');
        expect(screen.queryByRole('figure')).toBeNull();
        expect(screen.queryByText('Monte Carlo sampling')).toBeNull();
    });
    it('keeps the loading layout visible until the artifact body arrives', () => {
        vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(() => undefined)));
        render(<SWRConfig value={{ provider: () => new Map() }}><FundamentalAnalysisOutput reference={reference} resolvedTicker="EXAMPLE" status="done" /></SWRConfig>);
        expect(screen.getByRole('status', { name: 'Loading Fundamental report' }).getAttribute('aria-busy')).toBe('true');
        expect(screen.queryByRole('article')).toBeNull();
    });
    it.each(['requires_input', 'abstained', 'unsupported'] as const)('renders %s reasons without a fake resume or calculation result', (status) => {
        render(<FundamentalReport report={model(preparationOutcome(status))} />);
        screen.getByText('Calculation skipped.');
        screen.getByText('Share count evidence is unavailable.');
        screen.getByText(/Missing evidence · shares_outstanding/);
        expect(screen.queryByText('Valuation result')).toBeNull();
        expect(screen.queryByRole('button', { name: /continue|approve|recalculate/i })).toBeNull();
    });
    it('shows facts-only values and selects the exact source evidence', () => {
        const selectEvidence = vi.fn();
        render(<FundamentalReport report={model(factsOnlyReport())} onSelectEvidence={selectEvidence} />);
        screen.getByText('Valuation not requested');
        screen.getByText('USD · source scale 10^6');
        fireEvent.click(screen.getByRole('button', { name: 'Inspect Service fact · revenue' }));
        expect(selectEvidence).toHaveBeenCalledWith(expect.objectContaining({ value: '1000000.00000000000001', scale: 6, snapshotId: 'snapshot-1', artifactId: 'report-1', artifactUrl: reference.download_url }));
    });
    it('reads the same canonical report from an authenticated persisted artifact without previews', async () => {
        const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
            kind: 'financial_reports', version: 'v1', produced_by: 'fundamental_analysis', created_at: '2026-11-23T00:00:00Z',
            data: { ticker: 'EXAMPLE', model_type: 'fcff_dcf', status: 'done', financial_reports: [], fundamental_service: uncertaintyReport() },
        }), { status: 200 }));
        vi.stubGlobal('fetch', fetchMock);
        const inventory = vi.fn();
        await act(async () => render(<SWRConfig value={{ provider: () => new Map() }}><FundamentalAnalysisOutput reference={reference} resolvedTicker="EXAMPLE" status="done" threadId="thread-1" runId="different-run" onEvidenceInventory={inventory} /></SWRConfig>));
        await screen.findByText('USD 26.12 / share');
        screen.getByText('Previous result');
        expect(fetchMock).toHaveBeenCalledWith(reference.download_url, { credentials: 'include' });
        expect(inventory).toHaveBeenCalledWith(expect.objectContaining({ items: expect.arrayContaining([
            expect.objectContaining({ title: 'Service fact · revenue' }),
            expect.objectContaining({ title: 'Assumption · assumptions.wacc' }),
            expect.objectContaining({ title: 'Calculation · equity_value' }),
        ]) }));
    });
});
