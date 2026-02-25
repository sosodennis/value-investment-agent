import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { FundamentalAnalysisOutput } from './FundamentalAnalysisOutput';
import { ParsedFinancialPreview } from '@/types/agents/fundamental-preview-parser';

const mockUseArtifact = vi.fn();

vi.mock('../../hooks/useArtifact', () => ({
    useArtifact: (...args: unknown[]) => mockUseArtifact(...args),
}));

vi.mock('../FinancialTable', () => ({
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
                },
            },
        });

        expect(screen.queryByText('Monte Carlo: Enabled')).not.toBeNull();
        expect(screen.queryByText('Executed: 300')).not.toBeNull();
        expect(screen.queryByText('Window: 100')).not.toBeNull();
        expect(screen.queryByText('Early Stop: No')).not.toBeNull();
        expect(screen.queryByText('PSD Repair: Yes')).not.toBeNull();
        expect(screen.queryByText('Risk: High')).not.toBeNull();
        expect(screen.queryByText('defaults_present')).not.toBeNull();
        expect(screen.queryByText('time_alignment:high_risk')).not.toBeNull();
        expect(screen.queryByText(/Time Alignment Status/i)).not.toBeNull();
        expect(screen.getAllByText('high_risk').length).toBeGreaterThan(0);
        expect(screen.queryByText('Forward Signal Policy')).not.toBeNull();
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
                                text_snippet:
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
        expect(screen.queryByText('Growth Outlook')).not.toBeNull();
        expect(screen.getAllByText('Source: mda').length).toBeGreaterThan(0);
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
});
