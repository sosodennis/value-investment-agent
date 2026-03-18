import { describe, expect, it } from 'vitest';
import {
    parseDebateArtifact,
    parseFundamentalArtifact,
    parseNewsArtifact,
    parseTechnicalArtifact,
    parseTechnicalAlertsArtifact,
    parseTechnicalChartData,
    parseTechnicalFeaturePackArtifact,
    parseTechnicalFusionReportArtifact,
    parseTechnicalDirectionScorecardArtifact,
    parseTechnicalIndicatorSeriesArtifact,
    parseTechnicalPatternPackArtifact,
    parseTechnicalTimeseriesBundleArtifact,
    parseTechnicalVerificationReportArtifact,
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
            forward_signals: [
                {
                    signal_id: 'sig-1',
                    source_type: 'mda',
                    metric: 'growth_outlook',
                    direction: 'up',
                    value: 120,
                    unit: 'basis_points',
                    confidence: 0.74,
                    as_of: '2026-02-25T06:07:32.311583+00:00',
                    evidence: [
                        {
                            preview_text:
                                'Management expects higher revenue and raised guidance.',
                            full_text:
                                'Management expects higher revenue and raised guidance.',
                            source_url:
                                'https://www.sec.gov/Archives/edgar/data/320193/000032019325000073/0000320193-25-000073-index.html',
                            filing_date: '2025-11-03',
                            accession_number: '0000320193-25-000073',
                        },
                    ],
                },
            ],
            valuation_diagnostics: {
                forward_signal_mapping_version:
                    'forward_signal_calibration_v2_2026_03_05',
                forward_signal_calibration_applied: true,
            },
        });

        expect(parsed.ticker).toBe('AAPL');
        expect(parsed.status).toBe('done');
        expect(parsed.financial_reports).toHaveLength(1);
        expect(parsed.forward_signals).toHaveLength(1);
        expect(parsed.forward_signals?.[0]?.metric).toBe('growth_outlook');
        expect(parsed.forward_signals?.[0]?.evidence[0]?.accession_number).toBe(
            '0000320193-25-000073'
        );
        expect(parsed.valuation_diagnostics?.forward_signal_mapping_version).toBe(
            'forward_signal_calibration_v2_2026_03_05'
        );
        expect(
            parsed.valuation_diagnostics?.forward_signal_calibration_applied
        ).toBe(true);
    });

    it('normalizes nullable textual fields in fundamental artifact', () => {
        const parsed = parseFundamentalArtifact({
            ticker: 'AAPL',
            model_type: 'dcf',
            company_name: null,
            sector: null,
            industry: null,
            reasoning: null,
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

        expect(parsed.company_name).toBe('AAPL');
        expect(parsed.sector).toBe('Unknown');
        expect(parsed.industry).toBe('Unknown');
        expect(parsed.reasoning).toBe('');
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

    it('rejects invalid forward signals shape in fundamental artifact', () => {
        expect(() =>
            parseFundamentalArtifact({
                ticker: 'AAPL',
                model_type: 'dcf',
                company_name: 'Apple Inc.',
                sector: 'Technology',
                industry: 'Consumer Electronics',
                reasoning: 'Strong cash flow profile',
                status: 'done',
                financial_reports: [],
                forward_signals: {},
            })
        ).toThrowError('fundamental artifact.forward_signals must be an array.');
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

    it('accepts nullable optional fields in debate artifact', () => {
        const parsed = parseDebateArtifact({
            scenario_analysis: {
                bull_case: {
                    probability: 50,
                    outcome_description: 'Upside',
                    price_implication: 'SURGE',
                },
                bear_case: {
                    probability: 20,
                    outcome_description: 'Downside',
                    price_implication: 'CRASH',
                },
                base_case: {
                    probability: 30,
                    outcome_description: 'Base',
                    price_implication: 'FLAT',
                },
            },
            risk_profile: 'GROWTH_TECH',
            final_verdict: 'NEUTRAL',
            winning_thesis: 'Balanced view',
            primary_catalyst: 'Execution',
            primary_risk: 'Macro uncertainty',
            supporting_factors: ['Cash flow resilience'],
            debate_rounds: 2,
            rr_ratio: null,
            alpha: null,
            risk_free_benchmark: null,
            raw_ev: null,
            conviction: null,
            analysis_bias: null,
            model_summary: null,
            data_quality_warning: null,
            history: [
                {
                    name: null,
                    role: null,
                    content: 'Agent message',
                },
            ],
            facts: [
                {
                    fact_id: 'F1',
                    source_type: 'financials',
                    source_weight: 'HIGH',
                    summary: 'Revenue stable',
                    value: null,
                    units: null,
                    period: null,
                },
                {
                    fact_id: 'V1',
                    source_type: 'valuation',
                    source_weight: 'MEDIUM',
                    summary: 'Intrinsic value indicates upside',
                    value: 12.4,
                    units: '%',
                    period: 'FY2025',
                },
            ],
        });

        expect(parsed.history?.[0]?.name).toBeUndefined();
        expect(parsed.history?.[0]?.role).toBeUndefined();
        expect(parsed.facts?.[0]?.value).toBeUndefined();
        expect(parsed.facts?.[0]?.period).toBeUndefined();
        expect(parsed.facts?.[0]?.units).toBeUndefined();
        expect(parsed.facts?.[1]?.source_type).toBe('valuation');
        expect(parsed.rr_ratio).toBeUndefined();
        expect(parsed.analysis_bias).toBeUndefined();
        expect(parsed.data_quality_warning).toBeUndefined();
    });

    it('parses technical artifact', () => {
        const parsed = parseTechnicalArtifact({
            schema_version: 'v2',
            ticker: 'AAPL',
            as_of: '2026-02-12T00:00:00Z',
            direction: 'BULLISH_EXTENSION',
            risk_level: 'low',
            confidence: 0.78,
            confidence_raw: 0.62,
            confidence_calibrated: 0.78,
            confidence_calibration: {
                mapping_source: 'default_artifact',
                mapping_path: '/tmp/technical_direction_calibration.json',
                degraded_reason: null,
                mapping_version: 'technical_direction_calibration_v1_2026_03_16',
                calibration_applied: true,
            },
            momentum_extremes: {
                timeframe: '1d',
                source: 'indicator_series',
                rsi_value: 34.55,
                rsi_bias: 'BEARISH_BIAS',
                fd_z_score: -2.12,
                fd_label: 'EXTREME',
                fd_polarity: 'NEGATIVE',
                fd_risk_hint: 'MEAN_REVERSION_RISK',
            },
            analyst_perspective: {
                stance: 'BEARISH_WATCH',
                stance_summary: 'Bearish watch with low risk.',
                rationale_summary:
                    'Signals align toward downside continuation, but confirmation is still needed.',
                plain_language_summary:
                    'Trend pressure is slightly negative, but this still looks more like a watchlist setup than a decisive breakdown.',
                signal_explainers: [
                    {
                        signal: 'FD_OPTIMAL_D',
                        plain_name: '分數差分強度',
                        value_text: '0.600',
                        timeframe: '1d',
                        what_it_means_now:
                            'This shows how much trend memory needs to be removed to make the series more stable.',
                        why_it_matters_now:
                            'A moderate-to-high reading suggests the market still carries some persistent structure instead of pure noise.'
                    }
                ],
                top_evidence: [
                    {
                        label: 'MACD',
                        value_text: '-2.61',
                        timeframe: '1d',
                        rationale: 'Momentum remains negative.'
                    }
                ],
                trigger_condition: 'Break below support near 180',
                invalidation_condition:
                    'Recovery back above resistance near 190 invalidates the watch.',
                invalidation_level: 190,
                validation_note: 'Verification is stable.',
                confidence_note: 'Calibrated confidence is 78%.',
                decision_posture: 'CONFIRMATION_NEEDED'
            },
            artifact_refs: {
                feature_pack_id: 'feature-123',
                regime_pack_id: 'regime-123',
                alerts_id: 'alerts-789',
                fusion_report_id: 'fusion-456',
            },
            summary_tags: ['momentum', 'trend'],
            regime_summary: {
                dominant_regime: 'BULL_TREND',
                timeframe_count: 1,
            },
            volume_profile_summary: {
                timeframe: '1d',
                level_count: 2,
            },
            structure_confluence_summary: {
                confluence_state: 'strong',
                confluence_score: 0.74,
            },
            diagnostics: {
                is_degraded: true,
                degraded_reasons: ['HOURLY_DATA_MISSING'],
            },
        });

        expect(parsed.ticker).toBe('AAPL');
        expect('schema_version' in parsed).toBe(true);
        if (!('schema_version' in parsed)) {
            throw new Error('Expected technical analysis report.');
        }
        expect(parsed.risk_level).toBe('low');
        expect(parsed.artifact_refs.feature_pack_id).toBe('feature-123');
        expect(parsed.artifact_refs.regime_pack_id).toBe('regime-123');
        expect(parsed.artifact_refs.alerts_id).toBe('alerts-789');
        expect(parsed.confidence_raw).toBe(0.62);
        expect(parsed.confidence_calibrated).toBe(0.78);
        expect(parsed.confidence_calibration?.mapping_source).toBe('default_artifact');
        expect(parsed.momentum_extremes?.fd_label).toBe('EXTREME');
        expect(parsed.momentum_extremes?.rsi_bias).toBe('BEARISH_BIAS');
        expect(parsed.analyst_perspective?.stance).toBe('BEARISH_WATCH');
        expect(parsed.analyst_perspective?.plain_language_summary).toContain('watchlist');
        expect(parsed.analyst_perspective?.signal_explainers?.[0]?.signal).toBe('FD_OPTIMAL_D');
        expect(parsed.analyst_perspective?.top_evidence?.[0]?.label).toBe('MACD');
        expect(parsed.regime_summary?.dominant_regime).toBe('BULL_TREND');
        expect(parsed.volume_profile_summary?.timeframe).toBe('1d');
        expect(parsed.structure_confluence_summary?.confluence_state).toBe('strong');
        expect(parsed.diagnostics?.is_degraded).toBe(true);
        expect(parsed.summary_tags).toContain('momentum');
    });

    it('accepts nullable analyst_perspective in technical artifact', () => {
        const parsed = parseTechnicalArtifact({
            schema_version: 'v2',
            ticker: 'AAPL',
            as_of: '2026-02-12T00:00:00Z',
            direction: 'BULLISH_EXTENSION',
            risk_level: 'low',
            artifact_refs: {
                feature_pack_id: 'feature-123',
            },
            summary_tags: ['momentum'],
            analyst_perspective: null,
        });

        expect(parsed.analyst_perspective).toBeUndefined();
    });

    it('parses technical chart data artifact', () => {
        const parsed = parseTechnicalChartData({
            fracdiff_series: {
                '2026-02-10': 0.12,
                '2026-02-11': null,
            },
            z_score_series: {
                '2026-02-10': 1.2,
                '2026-02-11': -0.5,
            },
            indicators: {
                bollinger: { upper: 2.1 },
            },
        });

        expect(parsed.fracdiff_series['2026-02-10']).toBe(0.12);
        expect(parsed.fracdiff_series['2026-02-11']).toBeNull();
        expect(parsed.z_score_series['2026-02-11']).toBe(-0.5);
        expect(parsed.indicators.bollinger).toEqual({ upper: 2.1 });
    });

    it('parses technical timeseries bundle artifact', () => {
        const parsed = parseTechnicalTimeseriesBundleArtifact({
            ticker: 'AAPL',
            as_of: '2026-02-12T00:00:00Z',
            frames: {
                daily: {
                    timeframe: 'daily',
                    start: '2026-02-01T00:00:00Z',
                    end: '2026-02-12T00:00:00Z',
                    open_series: {
                        '2026-02-10': 180.5,
                        '2026-02-11': null,
                    },
                    high_series: {
                        '2026-02-10': 184.1,
                        '2026-02-11': 183.2,
                    },
                    low_series: {
                        '2026-02-10': 178.9,
                        '2026-02-11': 179.4,
                    },
                    close_series: {
                        '2026-02-10': 182.4,
                        '2026-02-11': 181.2,
                    },
                    price_series: {
                        '2026-02-10': 182.4,
                        '2026-02-11': 181.2,
                    },
                    volume_series: {
                        '2026-02-10': 1223000,
                        '2026-02-11': 1104500,
                    },
                    timezone: 'UTC',
                    metadata: {
                        source: 'yfinance',
                    },
                },
            },
            degraded_reasons: ['HOURLY_DATA_MISSING'],
        });

        expect(parsed.ticker).toBe('AAPL');
        expect(parsed.frames.daily.open_series['2026-02-10']).toBe(180.5);
        expect(parsed.frames.daily.open_series['2026-02-11']).toBeNull();
        expect(parsed.frames.daily.timezone).toBe('UTC');
        expect(parsed.degraded_reasons).toContain('HOURLY_DATA_MISSING');
    });

    it('parses technical indicator series artifact', () => {
        const parsed = parseTechnicalIndicatorSeriesArtifact({
            ticker: 'AAPL',
            as_of: '2026-02-12T00:00:00Z',
            timeframes: {
                daily: {
                    timeframe: '1d',
                    start: '2026-02-01T00:00:00Z',
                    end: '2026-02-12T00:00:00Z',
                    series: {
                        RSI_14: {
                            '2026-02-10': 45.0,
                            '2026-02-11': null,
                        },
                        MACD: {
                            '2026-02-10': 1.2,
                        },
                    },
                    timezone: 'UTC',
                    metadata: { source_points: 2, downsample_step: 1 },
                },
            },
            degraded_reasons: ['QUANT_SKIPPED'],
        });

        expect(parsed.ticker).toBe('AAPL');
        expect(parsed.timeframes.daily.series.RSI_14['2026-02-11']).toBeNull();
        expect(parsed.timeframes.daily.timezone).toBe('UTC');
        expect(parsed.degraded_reasons).toContain('QUANT_SKIPPED');
    });

    it('parses technical feature pack artifact', () => {
        const parsed = parseTechnicalFeaturePackArtifact({
            ticker: 'AAPL',
            as_of: '2026-02-12T00:00:00Z',
            timeframes: {
                daily: {
                    classic_indicators: {
                        rsi: { name: 'RSI', value: 45.2, state: 'neutral' },
                    },
                    quant_features: {
                        fracdiff_rsi: { name: 'FracDiff RSI', value: 0.12 },
                    },
                },
            },
            degraded_reasons: ['HOURLY_DATA_MISSING'],
        });

        expect(parsed.ticker).toBe('AAPL');
        expect(parsed.timeframes.daily.classic_indicators.rsi.name).toBe('RSI');
        expect(parsed.degraded_reasons).toContain('HOURLY_DATA_MISSING');
    });

    it('parses technical pattern pack artifact', () => {
        const parsed = parseTechnicalPatternPackArtifact({
            ticker: 'AAPL',
            as_of: '2026-02-12T00:00:00Z',
            timeframes: {
                daily: {
                    support_levels: [
                        { price: 120.5, strength: 0.8, touches: 3, label: 's1' },
                    ],
                    resistance_levels: [
                        { price: 135.2, strength: 0.6, touches: 2, label: 'r1' },
                    ],
                    volume_profile_levels: [
                        { price: 128.0, strength: 0.9, touches: 5, label: 'HVN' },
                    ],
                    volume_profile_summary: {
                        poc: 128.0,
                        vah: 130.0,
                        val: 126.0,
                        profile_method: 'daily_bar_approx',
                        profile_fidelity: 'low',
                    },
                    breakouts: [{ name: 'breakout_up', confidence: 0.7 }],
                    trendlines: [{ name: 'uptrend', confidence: 0.65 }],
                    pattern_flags: [{ name: 'higher_lows', confidence: 0.55 }],
                    confluence_metadata: { confluence_state: 'strong' },
                    confidence_scores: { support_confidence: 0.7 },
                },
            },
            degraded_reasons: ['WEEKLY_DATA_MISSING'],
        });

        expect(parsed.ticker).toBe('AAPL');
        expect(parsed.timeframes.daily.support_levels[0]?.price).toBe(120.5);
        expect(parsed.timeframes.daily.volume_profile_levels[0]?.label).toBe('HVN');
        expect(parsed.timeframes.daily.volume_profile_summary?.poc).toBe(128.0);
        expect(parsed.timeframes.daily.confluence_metadata?.confluence_state).toBe(
            'strong'
        );
        expect(parsed.timeframes.daily.breakouts[0]?.name).toBe('breakout_up');
        expect(parsed.degraded_reasons).toContain('WEEKLY_DATA_MISSING');
    });

    it('parses technical alerts artifact', () => {
        const parsed = parseTechnicalAlertsArtifact({
            ticker: 'AAPL',
            as_of: '2026-02-12T00:00:00Z',
            alerts: [
                {
                    code: 'RSI_OVERBOUGHT',
                    severity: 'warning',
                    timeframe: '1d',
                    title: 'RSI Overbought',
                    message: 'RSI above threshold',
                    value: 72.4,
                    threshold: 70,
                    direction: 'above',
                    triggered_at: '2026-02-12T00:00:00Z',
                    source: 'indicator_series',
                },
            ],
            summary: {
                total: 1,
                severity_counts: { warning: 1, critical: 0, info: 0 },
                generated_at: '2026-02-12T00:00:00Z',
            },
            degraded_reasons: ['PATTERN_PACK_MISSING'],
            source_artifacts: { indicator_series_id: 'series-1' },
        });

        expect(parsed.ticker).toBe('AAPL');
        expect(parsed.alerts).toHaveLength(1);
        expect(parsed.alerts[0]?.severity).toBe('warning');
        expect(parsed.summary?.total).toBe(1);
        expect(parsed.degraded_reasons).toContain('PATTERN_PACK_MISSING');
        expect(parsed.source_artifacts?.indicator_series_id).toBe('series-1');
    });

    it('parses technical fusion report artifact', () => {
        const parsed = parseTechnicalFusionReportArtifact({
            schema_version: '1.0',
            ticker: 'AAPL',
            as_of: '2026-02-12T00:00:00Z',
            direction: 'BULLISH_EXTENSION',
            risk_level: 'low',
            confidence: 0.62,
            confidence_raw: 0.48,
            confidence_calibrated: 0.62,
            confidence_calibration: {
                mapping_source: 'default_artifact',
                mapping_path: '/tmp/technical_direction_calibration.json',
                degraded_reason: null,
                mapping_version: 'technical_direction_calibration_v1_2026_03_16',
                calibration_applied: true,
            },
            confluence_matrix: {
                daily: {
                    classic: 'bullish',
                    quant: 'neutral',
                    pattern: 'bullish',
                    classic_score: 0.9,
                    quant_score: 0.1,
                    pattern_score: 0.6,
                },
            },
            conflict_reasons: ['daily:CLASSIC_BULLISH_VS_QUANT_NEUTRAL'],
            alignment_report: { anchor_timeframe: 'daily' },
            source_artifacts: { feature_pack_id: 'feature-123' },
            degraded_reasons: ['DAILY_PATTERN_FRAME_MISSING'],
        });

        expect(parsed.ticker).toBe('AAPL');
        expect(parsed.risk_level).toBe('low');
        expect(parsed.confluence_matrix?.daily?.classic).toBe('bullish');
        expect(parsed.conflict_reasons).toContain('daily:CLASSIC_BULLISH_VS_QUANT_NEUTRAL');
        expect(parsed.degraded_reasons).toContain('DAILY_PATTERN_FRAME_MISSING');
        expect(parsed.confidence_calibrated).toBe(0.62);
        expect(parsed.confidence_raw).toBe(0.48);
        expect(parsed.confidence_calibration?.mapping_version).toBe(
            'technical_direction_calibration_v1_2026_03_16'
        );
    });

    it('parses technical direction scorecard artifact', () => {
        const parsed = parseTechnicalDirectionScorecardArtifact({
            schema_version: '1.0',
            ticker: 'AAPL',
            as_of: '2026-02-12T00:00:00Z',
            direction: 'BEARISH_EXTENSION',
            risk_level: 'medium',
            confidence: 0.55,
            neutral_threshold: 0.5,
            overall_score: -0.8,
            model_version: 'ta_fusion_v1',
            timeframes: {
                '1d': {
                    timeframe: '1d',
                    classic_score: -1.0,
                    quant_score: -0.5,
                    pattern_score: 0.0,
                    total_score: -1.5,
                    classic_label: 'bearish',
                    quant_label: 'bearish',
                    pattern_label: 'neutral',
                    contributions: {
                        classic: [
                            {
                                name: 'RSI_14',
                                value: 72.4,
                                state: 'OVERBOUGHT',
                                contribution: -1.0,
                            },
                        ],
                        quant: [],
                        pattern: [],
                    },
                },
            },
            conflict_reasons: ['1d:CLASSIC_BEARISH_VS_PATTERN_NEUTRAL'],
            degraded_reasons: [],
            source_artifacts: { fusion_report_id: 'fusion-1' },
        });

        expect(parsed.ticker).toBe('AAPL');
        expect(parsed.timeframes['1d']?.classic_score).toBe(-1.0);
        expect(parsed.timeframes['1d']?.contributions.classic[0]?.name).toBe('RSI_14');
        expect(parsed.overall_score).toBe(-0.8);
    });

    it('parses technical verification report artifact', () => {
        const parsed = parseTechnicalVerificationReportArtifact({
            schema_version: '1.0',
            ticker: 'AAPL',
            as_of: '2026-02-12T00:00:00Z',
            backtest_summary: {
                strategy_name: 'baseline',
                win_rate: 0.55,
                profit_factor: 1.4,
                sharpe_ratio: 0.8,
                max_drawdown: 0.12,
                total_trades: 42,
            },
            wfa_summary: {
                wfa_sharpe: 0.5,
                wfe_ratio: 0.7,
                wfa_max_drawdown: 0.15,
                period_count: 6,
            },
            robustness_flags: ['LOW_SAMPLE'],
            baseline_gates: {
                min_trades: true,
                sharpe_threshold: false,
            },
            source_artifacts: {
                fusion_report_id: 'fusion-123',
            },
            degraded_reasons: ['WFA_DATA_MISSING'],
        });

        expect(parsed.ticker).toBe('AAPL');
        expect(parsed.backtest_summary?.win_rate).toBe(0.55);
        expect(parsed.wfa_summary?.period_count).toBe(6);
        expect(parsed.robustness_flags).toContain('LOW_SAMPLE');
        expect(parsed.baseline_gates?.min_trades).toBe(true);
        expect(parsed.degraded_reasons).toContain('WFA_DATA_MISSING');
    });

    it('rejects non-json value for unknown artifact parser', () => {
        expect(() => parseUnknownArtifact(undefined)).toThrowError(
            'artifact must be valid JSON value.'
        );
    });
});
