import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SWRConfig } from 'swr';
import { FundamentalAnalysisOutput, FundamentalReport } from './fundamental-analysis-output';
import { parseFundamentalServiceArtifact } from '@/types/agents/fundamental-service-facts';
import { projectFundamentalReport } from './fundamental-report-model';
import { calculation, factsOnlyReport, preparationOutcome, reference, uncertaintyReport, valuationReport } from './fundamental-report.test-fixtures';

function model(artifact: unknown) {
    return projectFundamentalReport({ artifact: parseFundamentalServiceArtifact(artifact), reference, threadId: 'thread-1', ticker: 'EXAMPLE' });
}

describe('Fundamental report', () => {
    afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
    it('shows canonical MC values and a distinct deterministic base without a synthetic price curve', () => {
        render(<FundamentalReport report={model(uncertaintyReport())} />);
        screen.getByText('Deterministic base per share');
        screen.getByText('25.1234567890123456789');
        screen.getByText('26.1234567890123456789');
        expect(screen.getAllByText('2500000000.1234567890123456789')).toHaveLength(2);
        screen.getByText('Samples requested 100 · valid 98 · invalid 2');
        screen.getByText(/minimum valid samples 10/);
        screen.getByText('OUT_OF_BOUNDS · 2');
        expect(screen.queryByText(/current price|upside|p25|p75/i)).toBeNull();
        expect(document.querySelector('svg.recharts-surface')).toBeNull();
        expect(screen.queryByRole('button', { name: /recalculate|edit|continue/i })).toBeNull();
    });
    it('displays huge canonical values and missing per-share values honestly', () => {
        render(<FundamentalReport report={model(valuationReport({ service_result: calculation({ intrinsic_value: '1e400', per_share_value: null }) }))} />);
        screen.getByText('1e400');
        screen.getAllByText('Unavailable');
        expect(screen.queryByText('Infinity')).toBeNull();
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
        screen.getByText('USD · USD · source scale 10^6');
        fireEvent.click(screen.getByRole('button', { name: 'Inspect revenue evidence' }));
        expect(selectEvidence).toHaveBeenCalledWith(expect.objectContaining({ value: '1000000.00000000000001', scale: 6, snapshotId: 'snapshot-1', artifactId: 'report-1', artifactUrl: reference.download_url }));
    });
    it('reads the same canonical report from an authenticated persisted artifact without previews', async () => {
        const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
            kind: 'financial_reports', version: 'v1', produced_by: 'fundamental_analysis', created_at: '2026-11-23T00:00:00Z',
            data: { ticker: 'EXAMPLE', model_type: 'fcff_dcf', status: 'done', financial_reports: [], fundamental_service: uncertaintyReport() },
        }), { status: 200 }));
        vi.stubGlobal('fetch', fetchMock);
        await act(async () => render(<SWRConfig value={{ provider: () => new Map() }}><FundamentalAnalysisOutput reference={reference} resolvedTicker="EXAMPLE" status="done" threadId="thread-1" runId="different-run" /></SWRConfig>));
        await screen.findByText('26.1234567890123456789');
        screen.getByText('Previous result');
        expect(fetchMock).toHaveBeenCalledWith(reference.download_url, { credentials: 'include' });
    });
});
