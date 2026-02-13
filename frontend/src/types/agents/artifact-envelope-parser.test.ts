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
