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
                    sampler_type: 'sobol',
                },
            },
            distribution_scenarios: {
                bear: { label: 'P5 (Bear)', price: 120 },
                base: { label: 'P50 (Base)', price: 150 },
                bull: { label: 'P95 (Bull)', price: 190 },
            },
            valuation_diagnostics: {
                growth_rates_converged: [0.12, 0.1, 0.08],
                terminal_growth_effective: 0.0135,
                growth_consensus_policy: 'ignored',
                growth_consensus_horizon: 'short_term',
                terminal_anchor_policy: 'policy_default_market_stale',
                terminal_anchor_stale_fallback: true,
                base_growth_guardrail_applied: true,
                base_growth_guardrail_version:
                    'base_assumption_guardrail_v1_2026_03_05',
                base_growth_raw_year1: 0.8,
                base_growth_raw_yearN: 0.02,
                base_growth_guarded_year1: 0.55,
                base_growth_guarded_yearN: 0.014,
                base_margin_guardrail_applied: true,
                base_margin_guardrail_version:
                    'base_assumption_guardrail_v1_2026_03_05',
                base_margin_raw_year1: 0.5943,
                base_margin_raw_yearN: 0.5943,
                base_margin_guarded_year1: 0.5943,
                base_margin_guarded_yearN: 0.42,
                forward_signal_mapping_version:
                    'forward_signal_calibration_v2_2026_03_05',
                forward_signal_calibration_applied: true,
                sensitivity_summary: {
                    enabled: true,
                    scenario_count: 16,
                    max_upside_delta_pct: 0.22,
                    max_downside_delta_pct: -0.19,
                    top_drivers: [
                        {
                            shock_dimension: 'wacc',
                            shock_value_bp: -100,
                            delta_pct_vs_base: 0.22,
                        },
                    ],
                },
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
                assumption_risk_level: 'high',
                data_quality_flags: [
                    'defaults_present',
                    'time_alignment:high_risk',
                ],
                time_alignment_status: 'high_risk',
                forward_signal_summary: {
                    signals_total: 3,
                    signals_accepted: 2,
                    signals_rejected: 1,
                    evidence_count: 4,
                    growth_adjustment_basis_points: 45.5,
                    margin_adjustment_basis_points: -20.0,
                    calibration_applied: true,
                    mapping_version: 'forward_signal_calibration_v2_2026_03_05',
                    risk_level: 'medium',
                    source_types: ['mda', 'press_release'],
                    decisions: [{ signal_id: 'sig-1' }],
                },
                forward_signal_risk_level: 'medium',
                forward_signal_evidence_count: 4,
                base_assumption_guardrail: {
                    version: 'base_assumption_guardrail_v1_2026_03_05',
                    growth: {
                        applied: true,
                        raw_year1: 0.8,
                        raw_yearN: 0.02,
                        guarded_year1: 0.55,
                        guarded_yearN: 0.014,
                        reasons: [
                            'growth_year1_capped',
                            'growth_terminal_aligned_to_long_run_target',
                        ],
                    },
                    margin: {
                        applied: true,
                        raw_year1: 0.5943,
                        raw_yearN: 0.5943,
                        guarded_year1: 0.5943,
                        guarded_yearN: 0.42,
                        reasons: ['margin_terminal_converged_to_normalized_band'],
                    },
                },
            },
            assumption_risk_level: 'high',
            data_quality_flags: [
                'defaults_present',
                'time_alignment:high_risk',
            ],
            time_alignment_status: 'high_risk',
            forward_signal_summary: {
                signals_total: 3,
                signals_accepted: 2,
                signals_rejected: 1,
                evidence_count: 4,
                growth_adjustment_basis_points: 45.5,
                margin_adjustment_basis_points: -20.0,
                calibration_applied: true,
                mapping_version: 'forward_signal_calibration_v2_2026_03_05',
                risk_level: 'medium',
                source_types: ['mda', 'press_release'],
                decisions: [{ signal_id: 'sig-1' }],
            },
            forward_signal_risk_level: 'medium',
            forward_signal_evidence_count: 4,
            data_freshness: {
                financial_statement: {
                    fiscal_year: 2025,
                    period_end_date: '2025-12-31',
                },
                market_data: {
                    provider: 'yfinance',
                    as_of: '2026-02-20T00:00:00Z',
                    missing_fields: ['target_mean_price'],
                    quality_flags: ['risk_free_rate:defaulted'],
                    license_note: 'test license note',
                    market_datums: {
                        risk_free_rate: {
                            value: 0.042,
                            source: 'policy_default',
                            as_of: '2026-02-20T00:00:00Z',
                            quality_flags: ['defaulted'],
                            license_note: 'internal default',
                        },
                    },
                },
                shares_outstanding_source: 'market_data',
                time_alignment: {
                    status: 'high_risk',
                    policy: 'warn',
                    lag_days: 420,
                    threshold_days: 365,
                    market_as_of: '2026-02-20T00:00:00+00:00',
                    filing_period_end: '2024-12-31',
                },
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
        expect(parsed?.distribution_summary?.diagnostics?.sampler_type).toBe('sobol');
        expect(parsed?.distribution_scenarios?.bull?.price).toBe(190);
        expect(parsed?.valuation_diagnostics?.growth_rates_converged).toEqual([
            0.12,
            0.1,
            0.08,
        ]);
        expect(parsed?.valuation_diagnostics?.terminal_growth_effective).toBe(0.0135);
        expect(parsed?.valuation_diagnostics?.growth_consensus_policy).toBe('ignored');
        expect(parsed?.valuation_diagnostics?.growth_consensus_horizon).toBe('short_term');
        expect(parsed?.valuation_diagnostics?.terminal_anchor_policy).toBe(
            'policy_default_market_stale'
        );
        expect(parsed?.valuation_diagnostics?.terminal_anchor_stale_fallback).toBe(true);
        expect(parsed?.valuation_diagnostics?.base_growth_guardrail_applied).toBe(true);
        expect(parsed?.valuation_diagnostics?.base_growth_guardrail_version).toBe(
            'base_assumption_guardrail_v1_2026_03_05'
        );
        expect(parsed?.valuation_diagnostics?.base_growth_guarded_yearN).toBe(0.014);
        expect(parsed?.valuation_diagnostics?.base_margin_guardrail_applied).toBe(true);
        expect(parsed?.valuation_diagnostics?.base_margin_guarded_yearN).toBe(0.42);
        expect(parsed?.valuation_diagnostics?.forward_signal_mapping_version).toBe(
            'forward_signal_calibration_v2_2026_03_05'
        );
        expect(parsed?.valuation_diagnostics?.forward_signal_calibration_applied).toBe(
            true
        );
        expect(parsed?.valuation_diagnostics?.sensitivity_summary?.enabled).toBe(true);
        expect(parsed?.valuation_diagnostics?.sensitivity_summary?.scenario_count).toBe(
            16
        );
        expect(
            parsed?.valuation_diagnostics?.sensitivity_summary?.top_drivers?.[0]
                ?.shock_dimension
        ).toBe('wacc');
        expect(parsed?.assumption_breakdown?.total_assumptions).toBe(2);
        expect(parsed?.assumption_breakdown?.monte_carlo?.executed_iterations).toBe(5000);
        expect(parsed?.assumption_breakdown?.monte_carlo?.effective_window).toBe(250);
        expect(parsed?.assumption_breakdown?.monte_carlo?.stopped_early).toBe(true);
        expect(parsed?.assumption_breakdown?.assumption_risk_level).toBe('high');
        expect(parsed?.assumption_breakdown?.data_quality_flags).toEqual([
            'defaults_present',
            'time_alignment:high_risk',
        ]);
        expect(parsed?.assumption_breakdown?.time_alignment_status).toBe('high_risk');
        expect(parsed?.assumption_breakdown?.base_assumption_guardrail?.version).toBe(
            'base_assumption_guardrail_v1_2026_03_05'
        );
        expect(
            parsed?.assumption_breakdown?.base_assumption_guardrail?.growth
                ?.guarded_year1
        ).toBe(0.55);
        expect(
            parsed?.assumption_breakdown?.base_assumption_guardrail?.margin
                ?.guarded_yearN
        ).toBe(0.42);
        expect(parsed?.assumption_risk_level).toBe('high');
        expect(parsed?.data_quality_flags).toEqual([
            'defaults_present',
            'time_alignment:high_risk',
        ]);
        expect(parsed?.time_alignment_status).toBe('high_risk');
        expect(parsed?.forward_signal_summary?.signals_total).toBe(3);
        expect(parsed?.forward_signal_summary?.source_types).toEqual([
            'mda',
            'press_release',
        ]);
        expect(parsed?.forward_signal_summary?.calibration_applied).toBe(true);
        expect(parsed?.forward_signal_summary?.mapping_version).toBe(
            'forward_signal_calibration_v2_2026_03_05'
        );
        expect(parsed?.forward_signal_summary?.decision_count).toBe(1);
        expect(parsed?.forward_signal_risk_level).toBe('medium');
        expect(parsed?.forward_signal_evidence_count).toBe(4);
        expect(parsed?.data_freshness?.market_data?.provider).toBe('yfinance');
        expect(parsed?.data_freshness?.market_data?.quality_flags).toEqual([
            'risk_free_rate:defaulted',
        ]);
        expect(parsed?.data_freshness?.market_data?.license_note).toBe('test license note');
        expect(
            parsed?.data_freshness?.market_data?.market_datums?.risk_free_rate?.source
        ).toBe('policy_default');
        expect(parsed?.data_freshness?.time_alignment?.status).toBe('high_risk');
        expect(parsed?.data_freshness?.time_alignment?.lag_days).toBe(420);
        expect(parsed?.financial_reports).toHaveLength(1);
    });

    it('falls back to assumption breakdown quality fields when top-level fields are absent', () => {
        const parsed = parseFinancialPreview({
            assumption_breakdown: {
                assumption_risk_level: 'medium',
                data_quality_flags: ['defaults_present'],
                time_alignment_status: 'warning',
                forward_signal_summary: {
                    signals_total: 2,
                    source_types: ['mda'],
                    decisions: [{ signal_id: 'sig-1' }, { signal_id: 'sig-2' }],
                },
                forward_signal_risk_level: 'high',
                forward_signal_evidence_count: 5,
            },
        });

        expect(parsed?.assumption_risk_level).toBe('medium');
        expect(parsed?.data_quality_flags).toEqual(['defaults_present']);
        expect(parsed?.time_alignment_status).toBe('warning');
        expect(parsed?.forward_signal_summary?.signals_total).toBe(2);
        expect(parsed?.forward_signal_summary?.decision_count).toBe(2);
        expect(parsed?.forward_signal_risk_level).toBe('high');
        expect(parsed?.forward_signal_evidence_count).toBe(5);
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
