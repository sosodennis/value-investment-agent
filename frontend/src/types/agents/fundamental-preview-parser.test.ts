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
            key_metrics: {
                ROE: '16.5%',
            },
            signal_state: {
                risk_level: 'low',
                z_score: 2.1,
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
        expect(parsed?.key_metrics?.ROE).toBe('16.5%');
        expect(parsed?.signal_state?.risk_level).toBe('low');
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
