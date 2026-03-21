import { renderHook, waitFor } from '@testing-library/react';
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
        fetchMock.mockResolvedValueOnce(
            new Response(
                JSON.stringify({
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
            )
        );

        const { result } = renderHook(() =>
            useTechnicalObservabilityEventDetail(
                'evt-1',
                'technical_outcome_labeling.v1'
            )
        );

        await waitFor(() => {
            expect(result.current.isLoading).toBe(false);
        });

        expect(result.current.detail?.event_id).toBe('evt-1');
        expect(fetchMock).toHaveBeenCalledTimes(1);
    });
});
