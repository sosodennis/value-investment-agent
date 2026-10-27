import { describe, expect, it } from 'vitest';

import {
    applyTechnicalObservabilityDatePreset,
    buildTechnicalObservabilitySearchParams,
    createDefaultTechnicalObservabilityFilters,
    parseFilterListInput,
    parseTechnicalMonitoringEventDetailResponse,
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

    it('keeps the optional run scope on event details', () => {
        const detail = parseTechnicalMonitoringEventDetailResponse({
            event_id: 'event-1',
            event_time: '2026-03-20T00:00:00Z',
            ticker: 'AAPL',
            agent_source: 'technical_analysis',
            timeframe: '1d',
            horizon: '1d',
            direction: 'bullish',
            logic_version: 'v1',
            feature_contract_version: 'technical_feature_contract_v1',
            run_type: 'workflow',
            full_report_artifact_id: 'report-1',
            source_artifact_refs: { feature_pack: 'source-1' },
            context_payload: {},
            data_quality_flags: [],
            run_id: 'run-1',
        });

        expect(detail.run_id).toBe('run-1');
        expect(
            parseTechnicalMonitoringEventDetailResponse({
                ...detail,
                run_id: undefined,
            }).run_id
        ).toBeUndefined();
    });
});
