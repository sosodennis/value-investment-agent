import { describe, expect, it } from 'vitest';
import { parseFinancialPreview } from './fundamental-preview-parser';

const buildBase = () => ({
    fiscal_year: null,
    fiscal_period: null,
    period_end_date: null,
    currency: null,
    company_name: null,
    cik: null,
    sic_code: null,
    shares_outstanding: null,
    total_revenue: null,
    net_income: null,
    income_tax_expense: null,
    total_assets: null,
    total_liabilities: null,
    total_equity: null,
    cash_and_equivalents: null,
    operating_cash_flow: null,
});

describe('parseFinancialPreview', () => {
    it('parses valid preview payload', () => {
        const parsed = parseFinancialPreview({
            ticker: 'AAPL',
            valuation_score: 82,
            equity_value: 1230000000000,
            intrinsic_value: 210.5,
            upside_potential: 0.182,
            key_metrics: {
                ROE: '16.5%',
            },
            signal_state: {
                risk_level: 'low',
                z_score: 2.1,
            },
            distribution_summary: {
                summary: {
                    percentile_5: 120,
                    percentile_25: 138,
                    median: 150,
                    percentile_75: 168,
                    percentile_95: 190,
                },
                diagnostics: {
                    converged: true,
                    iterations: 10000,
                },
            },
            distribution_scenarios: {
                bear: { label: 'P5 (Bear)', price: 120 },
                base: { label: 'P50 (Base)', price: 150 },
                bull: { label: 'P95 (Bull)', price: 190 },
            },
            assumption_breakdown: {
                total_assumptions: 2,
                assumptions: [
                    {
                        statement: 'wacc defaulted to 10.00%',
                        category: 'default',
                        severity: 'high',
                    },
                ],
                key_parameters: {
                    wacc: 0.1,
                    terminal_growth: 0.03,
                },
                monte_carlo: {
                    enabled: true,
                    iterations: 10000,
                    executed_iterations: 5000,
                    effective_window: 250,
                    stopped_early: true,
                },
            },
            data_freshness: {
                financial_statement: {
                    fiscal_year: 2025,
                    period_end_date: '2025-12-31',
                },
                market_data: {
                    provider: 'yfinance',
                    as_of: '2026-02-20T00:00:00Z',
                    missing_fields: ['target_mean_price'],
                },
                shares_outstanding_source: 'market_data',
            },
            financial_reports: [
                {
                    base: buildBase(),
                    extension_type: null,
                    extension: null,
                },
            ],
        });

        expect(parsed?.ticker).toBe('AAPL');
        expect(parsed?.valuation_score).toBe(82);
        expect(parsed?.equity_value).toBe(1230000000000);
        expect(parsed?.intrinsic_value).toBe(210.5);
        expect(parsed?.upside_potential).toBe(0.182);
        expect(parsed?.key_metrics?.ROE).toBe('16.5%');
        expect(parsed?.signal_state?.risk_level).toBe('low');
        expect(parsed?.distribution_summary?.summary.median).toBe(150);
        expect(parsed?.distribution_summary?.summary.percentile_25).toBe(138);
        expect(parsed?.distribution_summary?.summary.percentile_75).toBe(168);
        expect(parsed?.distribution_scenarios?.bull?.price).toBe(190);
        expect(parsed?.assumption_breakdown?.total_assumptions).toBe(2);
        expect(parsed?.assumption_breakdown?.monte_carlo?.executed_iterations).toBe(5000);
        expect(parsed?.assumption_breakdown?.monte_carlo?.effective_window).toBe(250);
        expect(parsed?.assumption_breakdown?.monte_carlo?.stopped_early).toBe(true);
        expect(parsed?.data_freshness?.market_data?.provider).toBe('yfinance');
        expect(parsed?.financial_reports).toHaveLength(1);
    });

    it('rejects invalid key_metrics values', () => {
        expect(() =>
            parseFinancialPreview({
                key_metrics: {
                    ROE: 16.5,
                },
            })
        ).toThrowError('preview.key_metrics.ROE must be a string.');
    });

    it('accepts null valuation_score as absent value', () => {
        const parsed = parseFinancialPreview({
            ticker: 'AAPL',
            valuation_score: null,
        });

        expect(parsed?.ticker).toBe('AAPL');
        expect(parsed?.valuation_score).toBeUndefined();
    });

    it('accepts nullable ticker as absent value', () => {
        const parsed = parseFinancialPreview({
            ticker: null,
            valuation_score: 80,
        });

        expect(parsed?.ticker).toBeUndefined();
        expect(parsed?.valuation_score).toBe(80);
    });

    it('accepts nullable and non-finite diagnostics values by skipping them', () => {
        const parsed = parseFinancialPreview({
            distribution_summary: {
                summary: {
                    percentile_5: 120,
                    median: 150,
                    percentile_95: 190,
                },
                diagnostics: {
                    converged: false,
                    iterations: 300,
                    median_delta: null,
                    tolerance: Number.NaN,
                },
            },
        });

        expect(parsed?.distribution_summary?.diagnostics?.converged).toBe(false);
        expect(parsed?.distribution_summary?.diagnostics?.iterations).toBe(300);
        expect(parsed?.distribution_summary?.diagnostics?.median_delta).toBeUndefined();
        expect(parsed?.distribution_summary?.diagnostics?.tolerance).toBeUndefined();
    });

    it('accepts backend report shape without period_end_date/currency and with industry_type', () => {
        const base = buildBase();
        const { period_end_date, currency, ...backendLikeBase } = base;
        void period_end_date;
        void currency;

        const parsed = parseFinancialPreview({
            financial_reports: [
                {
                    base: backendLikeBase,
                    industry_type: 'Financial',
                    extension: {
                        loans_and_leases: null,
                        deposits: null,
                        allowance_for_credit_losses: null,
                        interest_income: null,
                        interest_expense: null,
                        provision_for_loan_losses: null,
                    },
                },
            ],
        });

        expect(parsed?.financial_reports?.[0]?.base.period_end_date).toBeNull();
        expect(parsed?.financial_reports?.[0]?.base.currency).toBeNull();
        expect(parsed?.financial_reports?.[0]?.extension_type).toBe('FinancialServices');
    });

    it('rejects financial report missing required base fields', () => {
        const base = buildBase();
        const { total_revenue, ...invalidBase } = base;
        void total_revenue;

        expect(() =>
            parseFinancialPreview({
                financial_reports: [
                    {
                        base: invalidBase,
                    },
                ],
            })
        ).toThrowError(
            'preview.financial_reports[0].base.total_revenue must be an object.'
        );
    });

    it('rejects invalid signal_state risk level', () => {
        expect(() =>
            parseFinancialPreview({
                signal_state: {
                    risk_level: 'extreme',
                    z_score: 1.2,
                },
            })
        ).toThrowError(
            'preview.signal_state.risk_level must be low | medium | high.'
        );
    });
});
