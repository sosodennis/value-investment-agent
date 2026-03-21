import { describe, expect, it } from 'vitest';

import {
    applyTechnicalObservabilityDatePreset,
    buildTechnicalObservabilitySearchParams,
    createDefaultTechnicalObservabilityFilters,
    parseFilterListInput,
} from './technical-observability';

describe('technical observability types', () => {
    it('builds query params from filter state', () => {
        const filters = createDefaultTechnicalObservabilityFilters(
            new Date('2026-03-21T00:00:00Z')
        );

        const params = buildTechnicalObservabilitySearchParams({
            ...filters,
            tickers: ['AAPL', 'MSFT'],
            directions: ['bullish'],
            limit: 50,
        });

        expect(params.getAll('tickers')).toEqual(['AAPL', 'MSFT']);
        expect(params.getAll('directions')).toEqual(['bullish']);
        expect(params.get('limit')).toBe('50');
        expect(params.get('labeling_method_version')).toBe(
            'technical_outcome_labeling.v1'
        );
    });

    it('updates date windows from preset helper', () => {
        const next = applyTechnicalObservabilityDatePreset(
            'last_7d',
            new Date('2026-03-21T00:00:00Z')
        );

        expect(next.datePreset).toBe('last_7d');
        expect(next.eventTimeStart).toBe('2026-03-14T00:00:00.000Z');
        expect(next.eventTimeEnd).toBeNull();
    });

    it('normalizes ticker list input', () => {
        expect(parseFilterListInput(' aapl, msft ,, nvda ')).toEqual([
            'AAPL',
            'MSFT',
            'NVDA',
        ]);
    });
});
