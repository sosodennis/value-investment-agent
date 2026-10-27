import { describe, expect, it } from 'vitest';
import { parseCapabilities, parseMarketMovers, parseRecentAnalyses } from './home-parsers';

describe('home dashboard parsers', () => {
    it('parses recent runs and keeps the cursor optional', () => {
        expect(parseRecentAnalyses({
            items: [{
                thread_id: 'thread-1', run_id: 'run-1', status: 'completed',
                started_at: '2026-10-24T10:00:00Z', updated_at: '2026-10-24T10:05:00Z',
                ticker: 'AAPL', company_name: 'Apple Inc.',
            }],
            next_cursor: 'cursor-2',
        })).toEqual({
            items: [{
                thread_id: 'thread-1', run_id: 'run-1', status: 'completed',
                started_at: '2026-10-24T10:00:00Z', updated_at: '2026-10-24T10:05:00Z',
                ticker: 'AAPL', company_name: 'Apple Inc.', summary: undefined,
            }],
            next_cursor: 'cursor-2',
        });
        expect(parseRecentAnalyses({ items: [] })).toEqual({ items: [] });
    });

    it('rejects malformed or identity-incomplete recent runs', () => {
        expect(() => parseRecentAnalyses(null)).toThrow(/must be an object/);
        expect(() => parseRecentAnalyses({ items: {} })).toThrow(/must be an array/);
        expect(() => parseRecentAnalyses({ items: [{ thread_id: 'thread-1' }] })).toThrow(/run_id/);
        expect(() => parseRecentAnalyses({ items: [], next_cursor: null })).toThrow(/next_cursor/);
    });

    it('parses market freshness and quote values', () => {
        expect(parseMarketMovers({
            source: 'Yahoo Finance', as_of: '2026-10-24T10:00:00Z', fetched_at: '2026-10-24T10:01:00Z',
            status: 'stale', items: [{
                symbol: 'AAPL', name: 'Apple Inc.', price: 250, change_absolute: -2.5,
                change_percent: -0.99, currency: 'USD', market_state: 'REGULAR', quote_time: '2026-10-24T10:00:00Z',
            }],
        })).toMatchObject({ status: 'stale', source: 'Yahoo Finance', items: [{ symbol: 'AAPL', price: 250 }] });
    });

    it('rejects invalid quote numbers and unknown freshness states', () => {
        const base = { source: 'feed', as_of: 'now', fetched_at: 'now', status: 'fresh', items: [] };
        expect(() => parseMarketMovers({ ...base, status: 'delayed' })).toThrow(/status is invalid/);
        expect(() => parseMarketMovers({ ...base, items: [{
            symbol: 'AAPL', name: 'Apple', price: Number.NaN, change_absolute: 1,
            change_percent: 1, currency: 'USD', market_state: 'OPEN', quote_time: 'now',
        }] })).toThrow(/finite number/);
    });

    it('parses capabilities and rejects unsupported statuses', () => {
        expect(parseCapabilities({ checked_at: 'now', items: [{
            id: 'sec', label: 'SEC EDGAR', status: 'operational', source: 'health check', checked_at: 'now',
        }] }).items[0]?.status).toBe('operational');
        expect(() => parseCapabilities({ checked_at: 'now', items: [{
            id: 'sec', label: 'SEC EDGAR', status: 'online', source: 'health check', checked_at: 'now',
        }] })).toThrow(/status is invalid/);
    });
});
