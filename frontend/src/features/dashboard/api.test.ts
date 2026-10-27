import { afterEach, describe, expect, it, vi } from 'vitest';

import {
    getMarketMovers,
    getRecentAnalyses,
    parseDashboardCapabilities,
    parseMarketMovers,
    parseRecentAnalyses,
} from './api';

afterEach(() => vi.unstubAllGlobals());

describe('dashboard API boundary', () => {
    it('parses nullable metadata without substituting identifiers or invented content', () => {
        const response = parseRecentAnalyses({
            source: 'analysis_runtime',
            fetched_at: '2026-10-25T12:00:00Z',
            next_cursor: null,
            items: [{
                thread_id: 'thread-1',
                run_id: 'run-1',
                status: 'running',
                started_at: null,
                updated_at: null,
                ticker: null,
                company_name: null,
                summary: null,
            }],
        });

        expect(response.items[0]).toEqual({
            threadId: 'thread-1',
            runId: 'run-1',
            status: 'running',
            startedAt: null,
            updatedAt: null,
            ticker: null,
            companyName: null,
            summary: null,
        });
    });

    it('rejects unsupported source, status, and malformed timestamps', () => {
        const base = {
            source: 'analysis_runtime',
            fetched_at: '2026-10-25T12:00:00Z',
            next_cursor: null,
            items: [{ thread_id: 'thread-1', run_id: 'run-1', status: 'running' }],
        };
        expect(() => parseRecentAnalyses({ ...base, source: 'local_storage' })).toThrow(/source/);
        expect(() => parseRecentAnalyses({ ...base, items: [{ ...base.items[0], status: 'new' }] })).toThrow(/status/);
        expect(() => parseRecentAnalyses({ ...base, fetched_at: 'not-a-date' })).toThrow(/date-time/);
    });

    it('parses market source status and nullable quote fields from the API schema', () => {
        const response = parseMarketMovers({
            source: 'yahoo_finance',
            status: 'stale',
            fetched_at: '2026-10-25T12:00:00Z',
            error_code: null,
            items: [{
                symbol: 'AAPL',
                name: 'Apple Inc.',
                price: 250,
                change_absolute: -1.5,
                change_percent: -0.6,
                currency: null,
                market_state: null,
                quote_time: null,
            }],
        });
        expect(response).toEqual({
            source: 'yahoo_finance',
            status: 'stale',
            fetchedAt: '2026-10-25T12:00:00Z',
            errorCode: null,
            items: [{
                symbol: 'AAPL',
                name: 'Apple Inc.',
                price: 250,
                changeAbsolute: -1.5,
                changePercent: -0.6,
                currency: null,
                marketState: null,
                quoteTime: null,
            }],
        });
        expect(() => parseMarketMovers({ source: 'yahoo_finance', status: 'fresh', items: [{ symbol: 'AAPL', name: 'Apple', price: Number.NaN, change_absolute: 0, change_percent: 0 }] })).toThrow(/finite number/);
    });

    it('parses service capabilities and rejects unsupported capability states', () => {
        const response = parseDashboardCapabilities({
            status: 'degraded',
            checked_at: '2026-10-25T12:00:00Z',
            capabilities: [{
                id: 'analysis_runtime',
                status: 'operational',
                source: 'readiness_probe',
                checked_at: '2026-10-25T12:00:00Z',
                detail: null,
            }],
        });
        expect(response.capabilities[0]?.checkedAt).toBe('2026-10-25T12:00:00Z');
        expect(response.capabilities[0]?.detail).toBeNull();
        expect(() => parseDashboardCapabilities({ status: 'healthy', checked_at: '2026-10-25T12:00:00Z', capabilities: [] })).toThrow(/status/);
    });

    it('uses the authenticated dashboard paths and sends a cursor only when one exists', async () => {
        const response = {
            source: 'analysis_runtime',
            fetched_at: '2026-10-25T12:00:00Z',
            items: [],
            next_cursor: null,
        };
        const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify(response), { status: 200 })));
        vi.stubGlobal('fetch', fetchMock);

        await getRecentAnalyses({ limit: 10 });
        expect(fetchMock).toHaveBeenCalledWith(
            expect.stringMatching(/\/api\/v1\/dashboard\/recent-analyses\?limit=10$/),
            expect.objectContaining({ credentials: 'include' }),
        );

        await getRecentAnalyses({ limit: 10, next_cursor: 'cursor+/=' });
        expect(fetchMock).toHaveBeenLastCalledWith(
            expect.stringContaining('next_cursor=cursor%2B%2F%3D'),
            expect.objectContaining({ credentials: 'include' }),
        );

        fetchMock.mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ source: 'yahoo_finance', status: 'fresh', items: [] }), { status: 200 })));
        await getMarketMovers();
        expect(fetchMock).toHaveBeenLastCalledWith(
            expect.stringMatching(/\/api\/v1\/dashboard\/market-movers\?limit=3$/),
            expect.objectContaining({ credentials: 'include' }),
        );
    });
});
