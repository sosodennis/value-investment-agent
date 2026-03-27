import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { FundamentalAnalysisOutput } from './FundamentalAnalysisOutput';
import { ParsedFinancialPreview } from '@/types/agents/fundamental-preview-parser';

const mockUseArtifact = vi.fn();

vi.mock('../../../hooks/useArtifact', () => ({
    useArtifact: (...args: unknown[]) => mockUseArtifact(...args),
}));

vi.mock('./FinancialTable', () => ({
    FinancialTable: () => <div data-testid="financial-table">financial-table</div>,
}));

describe('FundamentalAnalysisOutput', () => {
    beforeEach(() => {
        mockUseArtifact.mockReturnValue({ data: null, isLoading: false });
    });

    const renderComponent = (previewData: ParsedFinancialPreview) => {
        render(
            <FundamentalAnalysisOutput
                reference={null}
                previewData={previewData}
                resolvedTicker="AAPL"
                status="done"
            />
        );
    };

    it('always renders deterministic valuation cards when preview exists and MC is disabled', () => {
        renderComponent({
            ticker: 'AAPL',
            key_metrics: { Revenue: '$10.0B' },
            assumption_breakdown: {
                total_assumptions: 1,
                monte_carlo: { enabled: false },
            },
        });

        expect(screen.queryByText('Intrinsic Value')).not.toBeNull();
        expect(screen.queryByText('Equity Value')).not.toBeNull();
        expect(screen.queryByText('Upside Potential')).not.toBeNull();
        expect(screen.queryByText('Monte Carlo: Disabled')).not.toBeNull();
    });

    it('renders MC diagnostics and quality signals when MC is enabled', () => {
        renderComponent({
            ticker: 'AAPL',
            assumption_risk_level: 'high',
            data_quality_flags: ['defaults_present', 'time_alignment:high_risk'],
            time_alignment_status: 'high_risk',
            forward_signal_summary: {
                signals_total: 3,
                signals_accepted: 2,
                signals_rejected: 1,
                growth_adjustment_basis_points: 45.5,
                margin_adjustment_basis_points: -20,
                calibration_applied: true,
                mapping_version: 'forward_signal_calibration_v2_2026_03_05',
                source_types: ['mda'],
            },
            forward_signal_risk_level: 'medium',
            forward_signal_evidence_count: 4,
            assumption_breakdown: {
                total_assumptions: 2,
                assumptions: [{ statement: 'wacc defaulted to 10%' }],
                monte_carlo: {
                    enabled: true,
                    executed_iterations: 300,
                    effective_window: 100,
                    stopped_early: false,
                    psd_repaired: true,
                    converged: false,
                    median_delta: 0.0032,
                    tolerance: 0.002,
                },
            },
        });

        expect(screen.queryByText('Monte Carlo: Enabled')).not.toBeNull();
        expect(screen.queryByText('Executed: 300')).not.toBeNull();
        expect(screen.queryByText('Window: 100')).not.toBeNull();
        expect(screen.queryByText('Early Stop: No')).not.toBeNull();
        expect(screen.queryByText('PSD Repair: Yes')).not.toBeNull();
        expect(screen.queryByText('Converged: No')).not.toBeNull();
        expect(screen.queryByText('Median Δ: 0.32% / 0.20% tol')).not.toBeNull();
        expect(screen.queryByText('Risk: High')).not.toBeNull();
        expect(screen.queryByText('defaults_present')).not.toBeNull();
        expect(screen.queryByText('time_alignment:high_risk')).not.toBeNull();
        expect(screen.queryByText(/Time Alignment Status/i)).not.toBeNull();
        expect(screen.getAllByText('high_risk').length).toBeGreaterThan(0);
        expect(screen.queryAllByText('Forward Signal Policy').length).toBeGreaterThan(0);
        expect(screen.queryByText('Signals: 3')).not.toBeNull();
        expect(screen.queryByText('Accepted: 2')).not.toBeNull();
        expect(screen.queryByText('Rejected: 1')).not.toBeNull();
        expect(screen.queryByText('Evidence: 4')).not.toBeNull();
        expect(
            screen.queryByText('Growth adjustment: +45.5 basis points')
        ).not.toBeNull();
        expect(
            screen.queryByText('Margin adjustment: -20.0 basis points')
        ).not.toBeNull();
        expect(screen.queryAllByText('Calibration: Applied').length).toBeGreaterThan(0);
        expect(
            screen.queryAllByText(
                'Mapping: forward_signal_calibration_v2_2026_03_05'
            ).length
        ).toBeGreaterThan(0);
        expect(screen.queryByText('Forward Risk: medium')).not.toBeNull();
        expect(screen.queryByText('Source: mda')).not.toBeNull();
    });

    it('renders forward signal cards and evidence table from artifact data', () => {
        mockUseArtifact.mockReturnValue({
            data: {
                ticker: 'AAPL',
                model_type: 'dcf',
                company_name: 'Apple Inc.',
                sector: 'Technology',
                industry: 'Consumer Electronics',
                reasoning: 'Strong cash flow profile',
                status: 'done',
                financial_reports: [],
                valuation_diagnostics: {
                    forward_signal_mapping_version:
                        'forward_signal_calibration_v2_2026_03_05',
                    forward_signal_calibration_applied: true,
                },
                forward_signals: [
                    {
                        signal_id: 'sig-1',
                        source_type: 'mda',
                        metric: 'growth_outlook',
                        direction: 'up',
                        value: 140,
                        unit: 'basis_points',
                        confidence: 0.81,
                        as_of: '2026-02-25T06:07:32.311583+00:00',
                        evidence: [
                            {
                                preview_text:
                                    'Management expects higher revenue and raised guidance by 5%.',
                                full_text:
                                    'Management expects higher revenue and raised guidance by 5%.',
                                source_url:
                                    'https://www.sec.gov/Archives/edgar/data/320193/000032019325000073/0000320193-25-000073-index.html',
                                filing_date: '2025-11-03',
                                accession_number: '0000320193-25-000073',
                                doc_type: '10-Q_focused',
                                period: 'Q4 2025',
                            },
                        ],
                    },
                ],
            },
            isLoading: false,
        });

        render(
            <FundamentalAnalysisOutput
                reference={null}
                previewData={{ ticker: 'AAPL' }}
                resolvedTicker="AAPL"
                status="done"
            />
        );

        expect(screen.queryByText('Forward Signals')).not.toBeNull();
        expect(screen.queryByText('Model: DCF (dcf)')).not.toBeNull();
        expect(screen.queryByText('Growth Outlook')).not.toBeNull();
        expect(screen.getAllByText('Source: mda').length).toBeGreaterThan(0);
        expect(screen.queryAllByText('Calibration: Applied').length).toBeGreaterThan(0);
        expect(
            screen.queryAllByText(
                'Mapping: forward_signal_calibration_v2_2026_03_05'
            ).length
        ).toBeGreaterThan(0);
        expect(screen.queryByText('2025-11-03')).not.toBeNull();
        expect(screen.queryByText('0000320193-25-000073')).not.toBeNull();
        expect(
            screen
                .getByRole('link', { name: /open filing/i })
                .getAttribute('href')
        ).toBe(
            'https://www.sec.gov/Archives/edgar/data/320193/000032019325000073/0000320193-25-000073-index.html'
        );
    });

    it('renders sensitivity summary block when valuation diagnostics are available', () => {
        renderComponent({
            ticker: 'AAPL',
            assumption_breakdown: {
                total_assumptions: 1,
                monte_carlo: { enabled: false },
            },
            valuation_diagnostics: {
                growth_consensus_policy: 'ignored',
                growth_consensus_horizon: 'short_term',
                terminal_anchor_policy: 'policy_default_market_stale',
                terminal_anchor_stale_fallback: true,
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
        });

        expect(screen.queryByText('Sensitivity (One-Way)')).not.toBeNull();
        expect(screen.queryByText('Enabled: Yes')).not.toBeNull();
        expect(screen.queryByText('Scenarios: 16')).not.toBeNull();
        expect(screen.queryByText('Max Upside: +22.0%')).not.toBeNull();
        expect(screen.queryByText('Max Downside: -19.0%')).not.toBeNull();
        expect(screen.queryByText(/wacc -100bp -> \+22.0%/i)).not.toBeNull();
        expect(screen.queryAllByText('Forward Signal Policy').length).toBeGreaterThan(0);
        expect(screen.queryAllByText('Calibration: Applied').length).toBeGreaterThan(0);
        expect(
            screen.queryAllByText(
                'Mapping: forward_signal_calibration_v2_2026_03_05'
            ).length
        ).toBeGreaterThan(0);
        expect(screen.queryAllByText('Growth / Anchor Policy').length).toBeGreaterThan(0);
        expect(screen.queryAllByText('Consensus: Ignored').length).toBeGreaterThan(0);
        expect(screen.queryAllByText('Horizon: short_term').length).toBeGreaterThan(0);
        expect(
            screen.queryAllByText('Terminal Anchor: Policy Default (Market Stale)')
                .length
        ).toBeGreaterThan(0);
        expect(screen.queryAllByText('Stale Fallback: Yes').length).toBeGreaterThan(0);
        expect(
            screen.queryAllByText('Calibration Applied (Diagnostics):').length
        ).toBeGreaterThan(0);
        expect(
            screen.queryAllByText('Calibration Mapping (Diagnostics):').length
        ).toBeGreaterThan(0);
    });

    it('renders base assumption guardrail summary from diagnostics and assumption breakdown fallback', () => {
        renderComponent({
            ticker: 'AAPL',
            assumption_breakdown: {
                total_assumptions: 2,
                monte_carlo: { enabled: false },
                base_assumption_guardrail: {
                    version: 'base_assumption_guardrail_v1_2026_03_05',
                    margin: {
                        applied: true,
                        raw_year1: 0.594,
                        raw_yearN: 0.594,
                        guarded_year1: 0.45,
                        guarded_yearN: 0.35,
                        reasons: ['margin_ceiling_clamp'],
                    },
                },
            },
            valuation_diagnostics: {
                base_growth_guardrail_applied: true,
                base_growth_guardrail_version: 'base_assumption_guardrail_v1_2026_03_05',
                base_growth_raw_year1: 0.668,
                base_growth_raw_yearN: 0.04,
                base_growth_guarded_year1: 0.42,
                base_growth_guarded_yearN: 0.03,
            },
        });

        expect(screen.queryByText('Base Assumption Guardrail')).not.toBeNull();
        expect(screen.queryByText('Growth: Applied')).not.toBeNull();
        expect(
            screen.queryByText(
                'Growth Version: base_assumption_guardrail_v1_2026_03_05'
            )
        ).not.toBeNull();
        expect(screen.queryByText('Growth Y1 Raw: 66.8%')).not.toBeNull();
        expect(screen.queryByText('Growth Y1 Guarded: 42.0%')).not.toBeNull();
        expect(screen.queryByText('Growth YN Raw: 4.0%')).not.toBeNull();
        expect(screen.queryByText('Growth YN Guarded: 3.0%')).not.toBeNull();
        expect(screen.queryByText('Margin: Applied')).not.toBeNull();
        expect(
            screen.queryByText(
                'Margin Version: base_assumption_guardrail_v1_2026_03_05'
            )
        ).not.toBeNull();
        expect(screen.queryByText('Margin Y1 Raw: 59.4%')).not.toBeNull();
        expect(screen.queryByText('Margin Y1 Guarded: 45.0%')).not.toBeNull();
        expect(screen.queryByText('Margin YN Raw: 59.4%')).not.toBeNull();
        expect(screen.queryByText('Margin YN Guarded: 35.0%')).not.toBeNull();
        expect(
            screen.queryByText('Margin Reasons: margin_ceiling_clamp')
        ).not.toBeNull();
    });

    it('toggles evidence preview and full text', () => {
        mockUseArtifact.mockReturnValue({
            data: {
                ticker: 'NVDA',
                model_type: 'dcf_growth',
                company_name: 'NVIDIA Corporation',
                sector: 'Technology',
                industry: 'Semiconductors',
                reasoning: 'Strong demand outlook',
                status: 'done',
                financial_reports: [],
                forward_signals: [
                    {
                        signal_id: 'sig-expand',
                        source_type: 'mda',
                        metric: 'growth_outlook',
                        direction: 'up',
                        value: 80,
                        unit: 'basis_points',
                        confidence: 0.7,
                        as_of: '2026-02-26T00:00:00+00:00',
                        evidence: [
                            {
                                preview_text: 'We expect supply constraints to be a headwind…',
                                full_text:
                                    'We expect supply constraints to be a headwind to Gaming in the first quarter of fiscal 2027 and beyond.',
                                source_url: 'https://www.sec.gov/',
                            },
                        ],
                    },
                ],
            },
            isLoading: false,
        });

        render(
            <FundamentalAnalysisOutput
                reference={null}
                previewData={{ ticker: 'NVDA' }}
                resolvedTicker="NVDA"
                status="done"
            />
        );

        expect(
            screen.queryByText('We expect supply constraints to be a headwind…')
        ).not.toBeNull();
        expect(screen.queryByText('Model: DCF (Growth) (dcf_growth)')).not.toBeNull();
        const expandButton = screen.getByRole('button', { name: 'Expand' });
        fireEvent.click(expandButton);
        expect(
            screen.queryByText(
                'We expect supply constraints to be a headwind to Gaming in the first quarter of fiscal 2027 and beyond.'
            )
        ).not.toBeNull();
        expect(screen.getByRole('button', { name: 'Collapse' })).not.toBeNull();
    });
});
