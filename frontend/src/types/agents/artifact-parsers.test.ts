import { describe, expect, it } from 'vitest';
import {
    parseDebateArtifact,
    parseFundamentalArtifact,
    parseNewsArtifact,
    parseTechnicalArtifact,
    parseUnknownArtifact,
} from './artifact-parsers';

describe('artifact parsers', () => {
    it('parses fundamental artifact', () => {
        const parsed = parseFundamentalArtifact({
            ticker: 'AAPL',
            model_type: 'dcf',
            company_name: 'Apple Inc.',
            sector: 'Technology',
            industry: 'Consumer Electronics',
            reasoning: 'Strong cash flow profile',
            status: 'done',
            financial_reports: [
                {
                    base: {
                        fiscal_year: { value: '2024' },
                        fiscal_period: { value: 'FY' },
                        period_end_date: { value: '2024-09-30' },
                        currency: { value: 'USD' },
                        company_name: { value: 'Apple Inc.' },
                        cik: { value: '0000320193' },
                        sic_code: { value: '3571' },
                        shares_outstanding: { value: 1000 },
                        total_revenue: { value: 100 },
                        net_income: { value: 10 },
                        income_tax_expense: { value: 1 },
                        total_assets: { value: 200 },
                        total_liabilities: { value: 100 },
                        total_equity: { value: 100 },
                        cash_and_equivalents: { value: 40 },
                        operating_cash_flow: { value: 20 },
                    },
                },
            ],
        });

        expect(parsed.ticker).toBe('AAPL');
        expect(parsed.status).toBe('done');
        expect(parsed.financial_reports).toHaveLength(1);
    });

    it('rejects invalid fundamental status', () => {
        expect(() =>
            parseFundamentalArtifact({
                ticker: 'AAPL',
                model_type: 'dcf',
                company_name: 'Apple Inc.',
                sector: 'Technology',
                industry: 'Consumer Electronics',
                reasoning: 'Strong cash flow profile',
                status: 'running',
                financial_reports: [],
            })
        ).toThrowError('fundamental artifact.status must be done.');
    });

    it('parses news artifact', () => {
        const parsed = parseNewsArtifact({
            ticker: 'AAPL',
            news_items: [
                {
                    id: 'n1',
                    url: 'https://example.com/1',
                    fetched_at: '2026-02-12T00:00:00Z',
                    title: 'Headline',
                    snippet: 'Snippet',
                    source: {
                        name: 'Example',
                        domain: 'example.com',
                        reliability_score: 0.9,
                    },
                    related_tickers: [
                        {
                            ticker: 'AAPL',
                            company_name: 'Apple Inc.',
                            relevance_score: 0.8,
                        },
                    ],
                    categories: ['general'],
                    tags: ['market'],
                },
            ],
            overall_sentiment: 'bullish',
            sentiment_score: 0.7,
            key_themes: ['growth'],
        });

        expect(parsed.news_items).toHaveLength(1);
        expect(parsed.overall_sentiment).toBe('bullish');
    });

    it('rejects invalid news sentiment', () => {
        expect(() =>
            parseNewsArtifact({
                ticker: 'AAPL',
                news_items: [],
                overall_sentiment: 'unknown',
                sentiment_score: 0.7,
                key_themes: [],
            })
        ).toThrowError(
            'news artifact.overall_sentiment must be bullish | bearish | neutral.'
        );
    });

    it('parses debate artifact', () => {
        const parsed = parseDebateArtifact({
            scenario_analysis: {
                bull_case: {
                    probability: 40,
                    outcome_description: 'Upside',
                    price_implication: 'MODERATE_UP',
                },
                bear_case: {
                    probability: 20,
                    outcome_description: 'Downside',
                    price_implication: 'MODERATE_DOWN',
                },
                base_case: {
                    probability: 40,
                    outcome_description: 'Flat',
                    price_implication: 'FLAT',
                },
            },
            risk_profile: 'GROWTH_TECH',
            final_verdict: 'LONG',
            winning_thesis: 'Execution quality',
            primary_catalyst: 'AI demand',
            primary_risk: 'Valuation',
            supporting_factors: ['Margin expansion'],
            debate_rounds: 3,
        });

        expect(parsed.final_verdict).toBe('LONG');
        expect(parsed.debate_rounds).toBe(3);
    });

    it('parses technical artifact', () => {
        const parsed = parseTechnicalArtifact({
            ticker: 'AAPL',
            timestamp: '2026-02-12T00:00:00Z',
            frac_diff_metrics: {
                optimal_d: 0.4,
                window_length: 120,
                adf_statistic: -3.2,
                adf_pvalue: 0.02,
                memory_strength: 'balanced',
            },
            signal_state: {
                z_score: 1.2,
                statistical_state: 'deviating',
                direction: 'up',
                risk_level: 'medium',
                confluence: {
                    bollinger_state: 'inside',
                    macd_momentum: 'positive',
                    obv_state: 'rising',
                    statistical_strength: 0.7,
                },
            },
            semantic_tags: ['momentum'],
            raw_data: {
                z_score_series: {
                    '2026-02-10': 1.1,
                },
            },
        });

        expect(parsed.signal_state.risk_level).toBe('medium');
        expect(parsed.raw_data?.z_score_series?.['2026-02-10']).toBe(1.1);
    });

    it('rejects non-json value for unknown artifact parser', () => {
        expect(() => parseUnknownArtifact(undefined)).toThrowError(
            'artifact must be valid JSON value.'
        );
    });
});
