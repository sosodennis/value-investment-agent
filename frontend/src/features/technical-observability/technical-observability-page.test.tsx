import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ query: vi.fn(), detail: vi.fn(), applied: null as null | { tickers: string[] } }));
vi.mock('@/hooks/useTechnicalObservability', () => ({
    useTechnicalObservability: mocks.query,
    useTechnicalObservabilityEventDetail: mocks.detail,
}));

import { TechnicalObservabilityPage } from './technical-observability-page';

const row = {
    event_id: 'evt-1', event_time: '2026-10-24T12:00:00Z', ticker: 'AAPL',
    agent_source: 'technical_analysis', timeframe: '1d', horizon: '1wk',
    direction: 'bullish', logic_version: 'v2', run_type: 'workflow',
    data_quality_flags: [], forward_return: 0.12,
};

function defaultQuery(overrides: Record<string, unknown> = {}) {
    return {
        aggregates: [{ timeframe: '1d', horizon: '1wk', logic_version: 'v2', event_count: 1, labeled_event_count: 1, unresolved_event_count: 0, avg_confidence: 0.8, avg_forward_return: 0.12 }],
        rows: [row], calibrationReadiness: { row_count: 1, usable_row_count: 1, dropped_row_count: 0, dropped_reasons: {} },
        isLoading: false, aggregatesError: null, rowsError: null, calibrationError: null,
        ...overrides,
    };
}

describe('TechnicalObservabilityPage', () => {
    afterEach(() => { cleanup(); vi.clearAllMocks(); });

    it('applies draft filters and resets them to defaults', () => {
        mocks.query.mockImplementation((filters) => { mocks.applied = filters; return defaultQuery(); });
        mocks.detail.mockReturnValue({ detail: null, isLoading: false, error: null });
        render(<TechnicalObservabilityPage />);
        fireEvent.change(screen.getByLabelText('Tickers'), { target: { value: 'MSFT' } });
        fireEvent.click(screen.getByRole('button', { name: 'Apply filters' }));
        expect(mocks.applied.tickers).toEqual(['MSFT']);
        fireEvent.click(screen.getByRole('button', { name: 'Reset' }));
        expect(mocks.applied.tickers).toEqual([]);
    });

    it('shows a query-specific error while retaining successful overview data', () => {
        mocks.query.mockReturnValue(defaultQuery({ rowsError: new Error('Rows service unavailable') }));
        mocks.detail.mockReturnValue({ detail: null, isLoading: false, error: null });
        render(<TechnicalObservabilityPage />);
        screen.getByText('Rows service unavailable');
        screen.getByText('Event volume by cohort');
        expect(screen.getAllByText('1').length).toBeGreaterThan(0);
    });

    it('loads and displays details for a selected event', async () => {
        mocks.query.mockReturnValue(defaultQuery());
        mocks.detail.mockImplementation((eventId: string | null) => ({
            detail: eventId ? { ...row, feature_contract_version: 'contract-v1', full_report_artifact_id: 'artifact-1', context_payload: { close: 200 }, source_artifact_refs: {} } : null,
            isLoading: false, error: null,
        }));
        render(<TechnicalObservabilityPage />);
        const eventsTab = screen.getByRole('tab', { name: 'Events' });
        fireEvent.mouseDown(eventsTab, { button: 0 });
        fireEvent.click(eventsTab);
        await waitFor(() => expect(screen.getByRole('button', { name: 'Open event evt-1' })).toBeTruthy());
        fireEvent.click(screen.getByRole('button', { name: 'Open event evt-1' }));
        await waitFor(() => screen.getByText('artifact-1'));
        expect(screen.getByText((_content, element) => element?.tagName === 'DD' && element.textContent?.includes('"close": 200') === true)).toBeTruthy();
        expect(mocks.detail).toHaveBeenLastCalledWith('evt-1', 'technical_outcome_labeling.v1');
    });
});
