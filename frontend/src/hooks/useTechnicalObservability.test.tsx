import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
    createDefaultTechnicalObservabilityFilters,
} from '@/types/technical-observability';

import {
    useTechnicalObservability,
    useTechnicalObservabilityEventDetail,
} from './useTechnicalObservability';

describe('useTechnicalObservability', () => {
    const fetchMock = vi.fn();

    beforeEach(() => {
        fetchMock.mockReset();
        vi.stubGlobal('fetch', fetchMock);
    });

    afterEach(() => {
        vi.unstubAllGlobals();
    });

    it('loads aggregate row and calibration payloads from the observability API', async () => {
        fetchMock
            .mockResolvedValueOnce(
                new Response(JSON.stringify([{ timeframe: '1d', horizon: '1d', logic_version: 'v1', event_count: 1, labeled_event_count: 1, unresolved_event_count: 0 }]), {
                    status: 200,
                    headers: { 'Content-Type': 'application/json' },
                })
            )
            .mockResolvedValueOnce(
                new Response(JSON.stringify([{ event_id: 'evt-1', event_time: '2026-03-20T00:00:00Z', ticker: 'AAPL', agent_source: 'technical_analysis', timeframe: '1d', horizon: '1d', direction: 'bullish', logic_version: 'v1', run_type: 'workflow', data_quality_flags: [] }]), {
                    status: 200,
                    headers: { 'Content-Type': 'application/json' },
                })
            )
            .mockResolvedValueOnce(
                new Response(JSON.stringify({ row_count: 2, usable_row_count: 1, dropped_row_count: 1, dropped_reasons: { missing_outcome_path: 1 } }), {
                    status: 200,
                    headers: { 'Content-Type': 'application/json' },
                })
            );

        const { result } = renderHook(() =>
            useTechnicalObservability(
                createDefaultTechnicalObservabilityFilters(
                    new Date('2026-03-21T00:00:00Z')
                )
            )
        );

        await waitFor(() => {
            expect(result.current.isLoading).toBe(false);
        });

        expect(result.current.aggregates).toHaveLength(1);
        expect(result.current.rows).toHaveLength(1);
        expect(result.current.calibrationReadiness?.usable_row_count).toBe(1);
        expect(fetchMock).toHaveBeenCalledTimes(3);
    });

    it('loads event detail by event id', async () => {
        fetchMock
            .mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'temporary failure' }), { status: 503 }))
            .mockResolvedValueOnce(
                new Response(JSON.stringify({
                    event_id: 'evt-1',
                    event_time: '2026-03-20T00:00:00Z',
                    ticker: 'AAPL',
                    agent_source: 'technical_analysis',
                    timeframe: '1d',
                    horizon: '1d',
                    direction: 'bullish',
                    logic_version: 'v1',
                    feature_contract_version: 'technical_feature_contract_v1',
                    run_type: 'workflow',
                    full_report_artifact_id: 'art-1',
                    source_artifact_refs: {},
                    context_payload: {},
                    data_quality_flags: [],
                }),
                {
                    status: 200,
                    headers: { 'Content-Type': 'application/json' },
                }
            ));

        const { result } = renderHook(() =>
            useTechnicalObservabilityEventDetail(
                'evt-1',
                'technical_outcome_labeling.v1'
            )
        );

        await waitFor(() => {
            expect(result.current.isLoading).toBe(false);
        });

        expect(result.current.error).toBeTruthy();
        await act(async () => {
            await result.current.retry();
        });
        await waitFor(() => {
            expect(result.current.detail?.event_id).toBe('evt-1');
        });
        expect(result.current.detail?.event_id).toBe('evt-1');
        expect(fetchMock).toHaveBeenCalledTimes(2);
    });

    it('retries only the failed query and retains successful sibling responses', async () => {
        let rowAttempts = 0;
        fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
            const url = String(input);
            if (url.includes('/monitoring/rows?')) {
                rowAttempts += 1;
                if (rowAttempts === 1) {
                    return new Response(JSON.stringify({ detail: 'rows temporarily unavailable' }), { status: 503 });
                }
                return new Response(JSON.stringify([{ event_id: 'retry-row', event_time: '2026-03-20T00:00:00Z', ticker: 'MSFT', agent_source: 'technical_analysis', timeframe: '1d', horizon: '1d', direction: 'bullish', logic_version: 'v1', run_type: 'workflow', data_quality_flags: [] }]), { status: 200 });
            }
            if (url.includes('/monitoring/aggregates?')) {
                return new Response(JSON.stringify([{ timeframe: '1d', horizon: '1d', logic_version: 'v1', event_count: 2, labeled_event_count: 1, unresolved_event_count: 1 }]), { status: 200 });
            }
            return new Response(JSON.stringify({ row_count: 2, usable_row_count: 1, dropped_row_count: 1, dropped_reasons: { missing_outcome_path: 1 } }), { status: 200 });
        });

        const filters = createDefaultTechnicalObservabilityFilters(new Date('2026-03-21T00:00:00Z'));
        filters.tickers = ['RETRYTEST'];
        const { result } = renderHook(() => useTechnicalObservability(filters));

        await waitFor(() => {
            expect(result.current.rowsError).toBeTruthy();
            expect(result.current.aggregates).toHaveLength(1);
            expect(result.current.calibrationReadiness?.usable_row_count).toBe(1);
        });
        await act(async () => {
            await result.current.retryRows();
        });
        await waitFor(() => {
            expect(result.current.rowsError).toBeNull();
            expect(result.current.rows[0]?.event_id).toBe('retry-row');
        });

        expect(fetchMock).toHaveBeenCalledTimes(4);
        expect(result.current.aggregates[0]?.event_count).toBe(2);
        expect(result.current.calibrationReadiness?.usable_row_count).toBe(1);
    });
});
