import { describe, expect, it } from 'vitest';
import { parseArtifactEnvelope } from './artifact-envelope-parser';

describe('parseArtifactEnvelope', () => {
    it('parses valid envelope and validates expected kind', () => {
        const parsed = parseArtifactEnvelope(
            {
                kind: 'financial_reports',
                version: 'v1',
                produced_by: 'fundamental_analysis.model_selection',
                created_at: '2026-02-12T00:00:00Z',
                data: {
                    financial_reports: [],
                },
            },
            'artifact',
            'financial_reports'
        );

        expect(parsed.kind).toBe('financial_reports');
        expect(parsed.version).toBe('v1');
        expect(parsed.produced_by).toBe('fundamental_analysis.model_selection');
    });

    it('parses ta_feature_pack envelope', () => {
        const parsed = parseArtifactEnvelope(
            {
                kind: 'ta_feature_pack',
                version: 'v1',
                produced_by: 'technical_analysis.feature_compute',
                created_at: '2026-02-12T00:00:00Z',
                data: {
                    ticker: 'AAPL',
                    as_of: '2026-02-12T00:00:00Z',
                    timeframes: {},
                },
            },
            'artifact',
            'ta_feature_pack'
        );

        expect(parsed.kind).toBe('ta_feature_pack');
    });

    it('parses ta_timeseries_bundle envelope', () => {
        const parsed = parseArtifactEnvelope(
            {
                kind: 'ta_timeseries_bundle',
                version: 'v1',
                produced_by: 'technical_analysis.market_data',
                created_at: '2026-02-12T00:00:00Z',
                data: {
                    ticker: 'AAPL',
                    as_of: '2026-02-12T00:00:00Z',
                    frames: {},
                },
            },
            'artifact',
            'ta_timeseries_bundle'
        );

        expect(parsed.kind).toBe('ta_timeseries_bundle');
    });

    it('parses ta_indicator_series envelope', () => {
        const parsed = parseArtifactEnvelope(
            {
                kind: 'ta_indicator_series',
                version: 'v1',
                produced_by: 'technical_analysis.feature_compute',
                created_at: '2026-02-12T00:00:00Z',
                data: {
                    ticker: 'AAPL',
                    as_of: '2026-02-12T00:00:00Z',
                    timeframes: {},
                },
            },
            'artifact',
            'ta_indicator_series'
        );

        expect(parsed.kind).toBe('ta_indicator_series');
    });

    it('parses ta_pattern_pack envelope', () => {
        const parsed = parseArtifactEnvelope(
            {
                kind: 'ta_pattern_pack',
                version: 'v1',
                produced_by: 'technical_analysis.pattern_compute',
                created_at: '2026-02-12T00:00:00Z',
                data: {
                    ticker: 'AAPL',
                    as_of: '2026-02-12T00:00:00Z',
                    timeframes: {},
                },
            },
            'artifact',
            'ta_pattern_pack'
        );

        expect(parsed.kind).toBe('ta_pattern_pack');
    });

    it('parses ta_alerts envelope', () => {
        const parsed = parseArtifactEnvelope(
            {
                kind: 'ta_alerts',
                version: 'v1',
                produced_by: 'technical_analysis.alerts_compute',
                created_at: '2026-02-12T00:00:00Z',
                data: {
                    ticker: 'AAPL',
                    as_of: '2026-02-12T00:00:00Z',
                    alerts: [],
                },
            },
            'artifact',
            'ta_alerts'
        );

        expect(parsed.kind).toBe('ta_alerts');
    });

    it('parses ta_fusion_report envelope', () => {
        const parsed = parseArtifactEnvelope(
            {
                kind: 'ta_fusion_report',
                version: 'v1',
                produced_by: 'technical_analysis.fusion_compute',
                created_at: '2026-02-12T00:00:00Z',
                data: {
                    schema_version: '1.0',
                    ticker: 'AAPL',
                    as_of: '2026-02-12T00:00:00Z',
                    direction: 'BULLISH_EXTENSION',
                    risk_level: 'low',
                },
            },
            'artifact',
            'ta_fusion_report'
        );

        expect(parsed.kind).toBe('ta_fusion_report');
    });

    it('parses ta_verification_report envelope', () => {
        const parsed = parseArtifactEnvelope(
            {
                kind: 'ta_verification_report',
                version: 'v1',
                produced_by: 'technical_analysis.verification_compute',
                created_at: '2026-02-12T00:00:00Z',
                data: {
                    schema_version: '1.0',
                    ticker: 'AAPL',
                    as_of: '2026-02-12T00:00:00Z',
                },
            },
            'artifact',
            'ta_verification_report'
        );

        expect(parsed.kind).toBe('ta_verification_report');
    });

    it('fails on kind mismatch', () => {
        expect(() =>
            parseArtifactEnvelope(
                {
                    kind: 'news_analysis_report',
                    version: 'v1',
                    produced_by: 'financial_news_research.aggregator_node',
                    created_at: '2026-02-12T00:00:00Z',
                    data: { ticker: 'NVDA', news_items: [] },
                },
                'artifact',
                'financial_reports'
            )
        ).toThrowError(/kind must be financial_reports/);
    });

    it('fails on unsupported version', () => {
        expect(() =>
            parseArtifactEnvelope(
                {
                    kind: 'financial_reports',
                    version: 'v2',
                    produced_by: 'fundamental_analysis.model_selection',
                    created_at: '2026-02-12T00:00:00Z',
                    data: {},
                },
                'artifact'
            )
        ).toThrowError(/version must be "v1"/);
    });
});
