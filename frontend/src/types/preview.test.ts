import { describe, expect, it } from 'vitest';
import { parseDebatePreview } from './agents/debate-preview-parser';
import { parseNewsPreview } from './agents/news-preview-parser';
import { parseTechnicalPreview } from './agents/technical-preview-parser';

describe('preview parsers', () => {
    it('parses valid news preview', () => {
        const parsed = parseNewsPreview({
            sentiment_display: 'Bullish',
            top_headlines: ['Headline A', 'Headline B'],
        });
        expect(parsed?.sentiment_display).toBe('Bullish');
        expect(parsed?.top_headlines).toHaveLength(2);
    });

    it('rejects invalid top_headlines', () => {
        expect(() =>
            parseNewsPreview({
                top_headlines: ['ok', 2],
            })
        ).toThrowError('news preview.top_headlines must be an array of strings.');
    });

    it('parses valid debate preview', () => {
        const parsed = parseDebatePreview({
            verdict_display: 'LONG',
            thesis_display: 'Strong catalyst',
        });
        expect(parsed?.verdict_display).toBe('LONG');
        expect(parsed?.thesis_display).toBe('Strong catalyst');
    });

    it('rejects invalid debate preview fields', () => {
        expect(() =>
            parseDebatePreview({
                verdict_display: 123,
            })
        ).toThrowError('debate preview.verdict_display must be a string | undefined.');
    });

    it('parses valid technical preview', () => {
        const parsed = parseTechnicalPreview({
            ticker: 'AAPL',
            signal_display: 'BULLISH',
        });
        expect(parsed?.ticker).toBe('AAPL');
        expect(parsed?.signal_display).toBe('BULLISH');
    });

    it('accepts nullable technical ticker as absent value', () => {
        const parsed = parseTechnicalPreview({
            ticker: null,
            signal_display: 'BULLISH',
        });
        expect(parsed?.ticker).toBeUndefined();
        expect(parsed?.signal_display).toBe('BULLISH');
    });

    it('rejects invalid technical preview fields', () => {
        expect(() =>
            parseTechnicalPreview({
                z_score_display: 1.23,
            })
        ).toThrowError(
            'technical preview.z_score_display must be a string | undefined.'
        );
    });
});
