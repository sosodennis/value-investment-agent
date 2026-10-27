import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { FundamentalAnalysisOutput } from './FundamentalAnalysisOutput';
import { ParsedFinancialPreview } from '@/types/agents/fundamental-preview-parser';

const mockUseArtifact = vi.fn();

vi.mock('../../../../hooks/useArtifact', () => ({
    useArtifact: (...args: unknown[]) => mockUseArtifact(...args),
}));

vi.mock('./FinancialTable', () => ({
    FinancialTable: () => <div data-testid="financial-table">financial-table</div>,
}));

describe('FundamentalAnalysisOutput', () => {
    afterEach(() => {
        cleanup();
    });

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

        screen.getByText('Intrinsic Value');
        screen.getByText('Equity Value');
        screen.getByText('Upside Potential');
        screen.getByRole('group', { name: 'Monte Carlo: Disabled' });
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

        screen.getByRole('group', { name: 'Monte Carlo: Enabled' });
        screen.getByText('Executed: 300');
        screen.getByText('Window: 100');
        screen.getByText('Early Stop: No');
        screen.getByText('PSD Repair: Yes');
        screen.getByText('Converged: No');
        screen.getByText('Median Δ: 0.32% / 0.20% tol');
        screen.getByText('Risk: High');
        screen.getByText('defaults_present');
        screen.getByText('time_alignment:high_risk');
        screen.getByRole('group', { name: 'Time Alignment: high_risk' });
        screen.getAllByText('Forward Signal Policy');
        screen.getByText('Signals: 3');
        screen.getByText('Accepted: 2');
        screen.getByText('Rejected: 1');
        screen.getByText('Evidence: 4');
        screen.getByText('Growth adjustment: +45.5 basis points');
        screen.getByText('Margin adjustment: -20.0 basis points');
        screen.getAllByText('Calibration: Applied');
        screen.getAllByText('Mapping:', { exact: true });
        screen.getAllByText('forward_signal_calibration_v2_2026_03_05', {
            exact: true,
        });
        screen.getByText('Forward Risk: medium');
        screen.getByText('Source: mda');
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
                reference={{
                    artifact_id: 'test-artifact',
                    download_url: '/artifacts/test-artifact',
                    type: 'application/json',
                }}
                previewData={{ ticker: 'AAPL' }}
                resolvedTicker="AAPL"
                status="done"
            />
        );

        screen.getByText('Forward Signals');
        screen.getByText('Model: DCF (dcf)');
        screen.getByText('Growth Outlook');
        screen.getAllByText('Source: mda');
        const growthAnchorPolicy = screen.getByRole('group', {
            name: 'Growth / Anchor Policy',
        });
        within(growthAnchorPolicy).getByText('Calibration:', { exact: true });
        within(growthAnchorPolicy).getByText('Applied', { exact: true });
        within(growthAnchorPolicy).getByText(/Mapping:/);
        within(growthAnchorPolicy).getByText(
            'forward_signal_calibration_v2_2026_03_05',
            { exact: true }
        );
        screen.getByText('2025-11-03');
        screen.getByText('0000320193-25-000073');
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

        screen.getByText('Sensitivity (One-Way)');
        screen.getByText('Enabled: Yes');
        screen.getByText('Scenarios: 16');
        screen.getByText('Max Upside: +22.0%');
        screen.getByText('Max Downside: -19.0%');
        screen.getByText(/wacc -100bp -> \+22.0%/i);
        screen.getAllByText('Forward Signal Policy');
        screen.getAllByText('Calibration: Applied');
        const growthAnchorPolicy = screen.getByRole('group', {
            name: 'Growth / Anchor Policy',
        });
        within(growthAnchorPolicy).getByText('Calibration:', { exact: true });
        within(growthAnchorPolicy).getByText('Applied', { exact: true });
        within(growthAnchorPolicy).getByText(/Mapping:/);
        within(growthAnchorPolicy).getByText(
            'forward_signal_calibration_v2_2026_03_05',
            { exact: true }
        );
        screen.getAllByText('Consensus: Ignored');
        screen.getAllByText('Horizon: short_term');
        screen.getAllByText('Terminal Anchor: Policy Default (Market Stale)');
        screen.getAllByText('Stale Fallback: Yes');
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

        screen.getByText('Base Assumption Guardrail');
        const growthGuardrail = screen.getByRole('group', {
            name: 'Growth base assumption guardrail',
        });
        within(growthGuardrail).getByText('Growth', { exact: true });
        within(growthGuardrail).getByText('Applied');
        within(growthGuardrail).getByText(
            'Version: base_assumption_guardrail_v1_2026_03_05'
        );
        within(growthGuardrail).getByText('Y1 Raw: 66.8%');
        within(growthGuardrail).getByText('Y1 Guarded: 42.0%');
        within(growthGuardrail).getByText('YN Raw: 4.0%');
        within(growthGuardrail).getByText('YN Guarded: 3.0%');

        const marginGuardrail = screen.getByRole('group', {
            name: 'Margin base assumption guardrail',
        });
        within(marginGuardrail).getByText('Margin', { exact: true });
        within(marginGuardrail).getByText('Applied');
        within(marginGuardrail).getByText(
            'Version: base_assumption_guardrail_v1_2026_03_05'
        );
        within(marginGuardrail).getByText('Y1 Raw: 59.4%');
        within(marginGuardrail).getByText('Y1 Guarded: 45.0%');
        within(marginGuardrail).getByText('YN Raw: 59.4%');
        within(marginGuardrail).getByText('YN Guarded: 35.0%');
        within(marginGuardrail).getByText('Reasons: margin_ceiling_clamp');
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

        screen.getByText('We expect supply constraints to be a headwind…');
        screen.getByText('Model: DCF (Growth) (dcf_growth)');
        const expandButton = screen.getByRole('button', { name: 'Expand' });
        fireEvent.click(expandButton);
        screen.getByText(
            'We expect supply constraints to be a headwind to Gaming in the first quarter of fiscal 2027 and beyond.'
        );
        screen.getByRole('button', { name: 'Collapse' });
    });
});
