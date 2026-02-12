import { describe, expect, it } from 'vitest';
import { StandardAgentOutput } from './index';
import { adaptAgentOutput } from './output-adapter';

const toOutput = (value: unknown): StandardAgentOutput =>
    ({
        summary: 'ok',
        preview: value,
    }) as unknown as StandardAgentOutput;

describe('output adapter', () => {
    it('adapts fundamental output to typed preview', () => {
        const viewModel = adaptAgentOutput(
            'fundamental_analysis',
            {
                summary: 'done',
                reference: {
                    artifact_id: 'artifact_1',
                    download_url: '/api/artifacts/artifact_1',
                    type: 'application/json',
                },
                preview: {
                    ticker: 'AAPL',
                    valuation_score: 72,
                    key_metrics: {
                        ROE: '15.0%',
                    },
                },
            },
            'adapter.fundamental'
        );

        expect(viewModel.kind).toBe('fundamental_analysis');
        if (viewModel.kind !== 'fundamental_analysis') {
            throw new Error('Unexpected view model kind.');
        }
        expect(viewModel.reference?.artifact_id).toBe('artifact_1');
        expect(viewModel.preview?.ticker).toBe('AAPL');
        expect(viewModel.preview?.valuation_score).toBe(72);
    });

    it('adapts news output to typed preview', () => {
        const viewModel = adaptAgentOutput(
            'financial_news_research',
            {
                summary: 'done',
                preview: {
                    sentiment_display: 'Bullish',
                    top_headlines: ['Headline A'],
                },
            },
            'adapter.news'
        );

        expect(viewModel.kind).toBe('financial_news_research');
        if (viewModel.kind !== 'financial_news_research') {
            throw new Error('Unexpected view model kind.');
        }
        expect(viewModel.preview?.sentiment_display).toBe('Bullish');
        expect(viewModel.preview?.top_headlines).toEqual(['Headline A']);
    });

    it('adapts unknown agent to generic preview record', () => {
        const viewModel = adaptAgentOutput(
            'custom_agent',
            toOutput({ custom: 'value' }),
            'adapter.custom'
        );
        expect(viewModel.kind).toBe('generic');
        if (viewModel.kind !== 'generic') {
            throw new Error('Unexpected view model kind.');
        }
        expect(viewModel.preview).toEqual({ custom: 'value' });
    });

    it('rejects invalid generic preview shape', () => {
        expect(() =>
            adaptAgentOutput('custom_agent', toOutput(123), 'adapter.custom')
        ).toThrowError('adapter.custom.preview must be an object.');
    });
});
