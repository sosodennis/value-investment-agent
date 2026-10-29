import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { TechnicalObservabilityFilters } from '@/types/technical-observability';

const mocks = vi.hoisted(() => ({ query: vi.fn(), detail: vi.fn(), applied: null as TechnicalObservabilityFilters | null }));
vi.mock('@/hooks/useTechnicalObservability', () => ({
    useTechnicalObservability: mocks.query,
    useTechnicalObservabilityEventDetail: mocks.detail,
}));

import { TechnicalObservabilityPage } from './technical-observability-page';

const row = {
    event_id: 'evt-1', event_time: '2026-10-24T12:00:00Z', ticker: 'AAPL',
    agent_source: 'technical_analysis', timeframe: '1d', horizon: '1wk',
    direction: 'bullish', logic_version: 'v2', run_type: 'workflow',
    confidence: 0.8, raw_score: 0.72, forward_return: 0.12,
    realized_volatility: 0.15, mfe: 0.18, mae: -0.04,
    reliability_level: 'high', resolved_at: '2026-10-24T13:00:00Z',
    data_quality_flags: [],
};

function defaultQuery(overrides: Record<string, unknown> = {}) {
    return {
        aggregates: [{ timeframe: '1d', horizon: '1wk', logic_version: 'v2', event_count: 1, labeled_event_count: 1, unresolved_event_count: 0, avg_confidence: 0.8, avg_raw_score: 0.72, avg_forward_return: 0.12, avg_realized_volatility: 0.15, avg_mfe: 0.18, avg_mae: -0.04 }],
        rows: [row], calibrationReadiness: { row_count: 1, usable_row_count: 1, dropped_row_count: 0, dropped_reasons: {}, observations: [{ direction: 'bullish', timeframe: '1d', horizon: '1wk', raw_score: 0.72, target_outcome: 0.12 }] },
        isLoading: false, aggregatesError: null, rowsError: null, calibrationError: null,
        aggregatesLoading: false, rowsLoading: false, calibrationLoading: false,
        aggregatesValidating: false, rowsValidating: false, calibrationValidating: false,
        retryAggregates: vi.fn(), retryRows: vi.fn(), retryCalibration: vi.fn(),
        ...overrides,
    };
}

function activateTab(name: string) {
    const tab = screen.getByRole('tab', { name });
    fireEvent.mouseDown(tab, { button: 0 });
    fireEvent.click(tab);
}

describe('TechnicalObservabilityPage', () => {
    afterEach(() => { cleanup(); vi.clearAllMocks(); });

    it('applies draft filters and resets them to defaults', () => {
        mocks.query.mockImplementation((filters) => { mocks.applied = filters; return defaultQuery(); });
        mocks.detail.mockReturnValue({ detail: null, isLoading: false, error: null });
        render(<TechnicalObservabilityPage />);
        fireEvent.change(screen.getByLabelText('Tickers'), { target: { value: 'MSFT' } });
        fireEvent.click(screen.getByRole('button', { name: 'Apply filters' }));
        expect(mocks.applied?.tickers).toEqual(['MSFT']);
        fireEvent.click(screen.getByRole('button', { name: 'Reset' }));
        expect(mocks.applied?.tickers).toEqual([]);
    });

    it('applies all supported filter dimensions, select values, and explicit date bounds', async () => {
        mocks.query.mockImplementation((filters) => { mocks.applied = filters; return defaultQuery(); });
        mocks.detail.mockReturnValue({ detail: null, isLoading: false, error: null });
        render(<TechnicalObservabilityPage />);
        Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { value: vi.fn(), configurable: true });

        fireEvent.click(screen.getByRole('combobox', { name: 'Timeframe' }));
        fireEvent.click(await screen.findByRole('option', { name: '1W' }));
        fireEvent.click(screen.getByRole('combobox', { name: 'Direction' }));
        fireEvent.click(await screen.findByRole('option', { name: 'Bullish' }));
        fireEvent.click(screen.getByRole('combobox', { name: 'Row limit' }));
        fireEvent.click(await screen.findByRole('option', { name: '500 rows' }));
        fireEvent.change(screen.getByLabelText('Agent sources'), { target: { value: 'technical_analysis' } });
        fireEvent.change(screen.getByLabelText('Logic versions'), { target: { value: 'v3' } });
        fireEvent.change(screen.getByLabelText('Run types'), { target: { value: 'workflow' } });
        fireEvent.change(screen.getByLabelText('Reliability levels'), { target: { value: 'high' } });
        fireEvent.change(screen.getByLabelText('Event start'), { target: { value: '2026-10-01' } });
        fireEvent.change(screen.getByLabelText('Event end'), { target: { value: '2026-10-20' } });
        fireEvent.change(screen.getByLabelText('Resolved start'), { target: { value: '2026-10-05' } });
        fireEvent.change(screen.getByLabelText('Resolved end'), { target: { value: '2026-10-22' } });
        fireEvent.change(screen.getByLabelText('Labeling method'), { target: { value: 'method.v2' } });
        fireEvent.click(screen.getByRole('button', { name: 'Apply filters' }));

        expect(mocks.applied).toMatchObject({
            timeframes: ['1wk'],
            directions: ['bullish'],
            limit: 500,
            agentSources: ['TECHNICAL_ANALYSIS'],
            logicVersions: ['V3'],
            runTypes: ['WORKFLOW'],
            reliabilityLevels: ['HIGH'],
            eventTimeStart: '2026-10-01T00:00:00.000Z',
            eventTimeEnd: '2026-10-20T23:59:59.000Z',
            resolvedTimeStart: '2026-10-05T00:00:00.000Z',
            resolvedTimeEnd: '2026-10-22T23:59:59.000Z',
            labelingMethodVersion: 'method.v2',
        });
    });

    it('shows a query-specific error while retaining successful overview data', () => {
        mocks.query.mockReturnValue(defaultQuery({ rowsError: new Error('Rows service unavailable') }));
        mocks.detail.mockReturnValue({ detail: null, isLoading: false, error: null });
        render(<TechnicalObservabilityPage />);
        screen.getByText('Rows service unavailable');
        screen.getByText('Event volume by cohort');
        expect(screen.getAllByText('1').length).toBeGreaterThan(0);
    });

    it('keeps aggregate data available while exposing a retry for failed rows', () => {
        const query = defaultQuery({ rowsError: new Error('Rows service unavailable') });
        mocks.query.mockReturnValue(query);
        mocks.detail.mockReturnValue({ detail: null, isLoading: false, isValidating: false, error: null, retry: vi.fn() });
        render(<TechnicalObservabilityPage />);

        expect(screen.getByText('Event volume by cohort')).toBeTruthy();
        activateTab('Events');
        expect(screen.getByText('Rows service unavailable')).toBeTruthy();
        fireEvent.click(screen.getByRole('button', { name: 'Retry prediction events' }));
        expect(query.retryRows).toHaveBeenCalledOnce();
    });

    it('shows raw cohort and calibration data while explaining missing approved snapshots', () => {
        mocks.query.mockReturnValue(defaultQuery());
        mocks.detail.mockReturnValue({ detail: null, isLoading: false, isValidating: false, error: null, retry: vi.fn() });
        render(<TechnicalObservabilityPage />);

        activateTab('Cohorts');
        expect(screen.getByText('Avg raw score')).toBeTruthy();
        expect(screen.getByText('Avg realized vol')).toBeTruthy();
        fireEvent.click(screen.getByRole('radio', { name: 'Approved snapshots' }));
        screen.getByText(/does not provide a snapshot-backed cohort or calibration read model/i);
        activateTab('Calibration');
        screen.getByText(/does not provide a snapshot-backed cohort or calibration read model/i);
        fireEvent.click(screen.getByRole('radio', { name: 'Raw outcomes' }));
        expect(screen.getByText('Raw score')).toBeTruthy();
        expect(screen.getByText('Target outcome')).toBeTruthy();
    });

    it('loads and displays details for a selected event', async () => {
        mocks.query.mockReturnValue(defaultQuery());
        const retryDetail = vi.fn();
        mocks.detail.mockImplementation((eventId: string | null) => ({
            detail: eventId ? { ...row, feature_contract_version: 'contract-v1', full_report_artifact_id: 'artifact /?1', source_artifact_refs: { feature_pack: 'source-2' }, context_payload: { close: 200 }, run_id: 'run-observability-1' } : null,
            isLoading: false, isValidating: false, error: null, retry: retryDetail,
        }));
        render(<TechnicalObservabilityPage />);
        const eventsTab = screen.getByRole('tab', { name: 'Events' });
        fireEvent.mouseDown(eventsTab, { button: 0 });
        fireEvent.click(eventsTab);
        await waitFor(() => expect(screen.getByRole('button', { name: 'Open event evt-1' })).toBeTruthy());
        screen.getByRole('columnheader', { name: 'Confidence' });
        screen.getByRole('columnheader', { name: 'Forward return' });
        fireEvent.click(screen.getByRole('button', { name: 'Open event evt-1' }));
        const reportLink = await screen.findByRole('link', { name: /Full report:/ });
        expect(reportLink.getAttribute('href')).toBe('/api/v1/artifacts/artifact%20%2F%3F1?run_id=run-observability-1');
        const sourceLink = screen.getByRole('link', { name: /feature pack: source-2/ });
        expect(sourceLink.getAttribute('href')).toBe('/api/v1/artifacts/source-2?run_id=run-observability-1');
        expect(screen.getAllByText('80.00%').length).toBeGreaterThanOrEqual(1);
        expect(screen.getByText((_content, element) => element?.tagName === 'DD' && element.textContent?.includes('"close": 200') === true)).toBeTruthy();
        expect(mocks.detail).toHaveBeenLastCalledWith('evt-1', 'technical_outcome_labeling.v1');
    });

    it('offers an event-detail retry without changing the selected event', () => {
        mocks.query.mockReturnValue(defaultQuery());
        const retryDetail = vi.fn();
        mocks.detail.mockImplementation((eventId: string | null) => ({
            detail: null,
            isLoading: false,
            isValidating: false,
            error: eventId ? new Error('Event detail unavailable') : null,
            retry: retryDetail,
        }));
        render(<TechnicalObservabilityPage />);
        activateTab('Events');
        fireEvent.click(screen.getByRole('button', { name: 'Open event evt-1' }));
        fireEvent.click(screen.getByRole('button', { name: 'Retry event detail' }));
        expect(retryDetail).toHaveBeenCalledOnce();
        expect(mocks.detail).toHaveBeenLastCalledWith('evt-1', 'technical_outcome_labeling.v1');
    });
});
