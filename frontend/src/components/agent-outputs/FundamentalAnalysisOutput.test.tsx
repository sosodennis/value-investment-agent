import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { FundamentalAnalysisOutput } from './FundamentalAnalysisOutput';
import { ParsedFinancialPreview } from '@/types/agents/fundamental-preview-parser';

vi.mock('../../hooks/useArtifact', () => ({
    useArtifact: () => ({ data: null, isLoading: false }),
}));

vi.mock('../FinancialTable', () => ({
    FinancialTable: () => <div data-testid="financial-table">financial-table</div>,
}));

describe('FundamentalAnalysisOutput', () => {
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
                growth_adjustment_bps: 45.5,
                margin_adjustment_bps: -20,
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
        expect(screen.queryByText('Growth Adj: +45.5 bps')).not.toBeNull();
        expect(screen.queryByText('Margin Adj: -20.0 bps')).not.toBeNull();
        expect(screen.queryByText('Forward Risk: medium')).not.toBeNull();
        expect(screen.queryByText('Source: mda')).not.toBeNull();
    });
});
