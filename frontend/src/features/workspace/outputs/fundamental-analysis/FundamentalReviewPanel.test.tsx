import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { FundamentalReviewPanel } from './FundamentalReviewPanel';
import type { FundamentalAutomaticPreparation } from '@/types/agents/fundamental-service-facts';

const preparation: FundamentalAutomaticPreparation = {
    contract_version: 'fundamental.v1',
    status: 'prepared',
    model_id: 'fcff_dcf',
    model_version: 'fcff_dcf-v1',
    profile_id: 'fcff-valuation-requirements-v1',
    profile_digest: 'a'.repeat(64),
    policy_id: 'fcff_dcf-us-gaap-public-v1',
    policy_version: 'fcff-dcf-v1-quality-v1',
    quality_status: 'provisional',
    issue_codes: ['HISTORY_THRESHOLD_UNVALIDATED'],
    missing_evidence: [],
    historical_metrics: {},
    assumptions_evidence: [
        {
            path: 'assumptions.terminal_growth',
            value: '0.02',
            method: 'derived',
            formula: 'terminal_growth_policy_default',
            fact_ids: ['fact-gdp-growth'],
            source_refs: ['macro:gdp-growth'],
            policy_version: 'fcff-dcf-v1-quality-v1',
            as_of: '2026-11-07T00:00:00Z',
            editable: true,
        },
        {
            path: 'assumptions.wacc',
            value: '0.09',
            method: 'manual',
            formula: 'manual_override',
            fact_ids: [],
            source_refs: [],
            policy_version: 'fcff-dcf-v1-quality-v1',
            as_of: '2026-11-07T00:00:00Z',
            editable: true,
            manual_provenance: {
                author: 'workspace-user',
                modified_at: '2026-11-07T00:00:00Z',
                reason: 'Approved by user.',
                automatic_preparation_digest: 'b'.repeat(64),
            },
        },
    ],
    input: { assumptions: { terminal_growth: '0.02' } },
    preparation_digest: 'c'.repeat(64),
};

describe('FundamentalReviewPanel', () => {
    it('renders service-owned evidence and sends a reasoned manual override', () => {
        const onRecalculate = vi.fn();
        render(<FundamentalReviewPanel preparation={preparation} onRecalculate={onRecalculate} />);

        expect(screen.getByText('Automatic valuation preparation')).toBeTruthy();
        expect(screen.getByText('HISTORY_THRESHOLD_UNVALIDATED')).toBeTruthy();
        expect(screen.getByText(/macro:gdp-growth/)).toBeTruthy();
        expect(screen.getByLabelText('assumptions.wacc').hasAttribute('disabled')).toBe(true);

        const recalculateButtons = screen.getAllByRole('button', { name: 'Recalculate' });
        fireEvent.click(recalculateButtons[0]!);
        expect(screen.getByRole('alert').textContent).toContain('Give a reason for the manual override');

        fireEvent.change(screen.getByLabelText('Override reason'), {
            target: { value: 'Updated after reviewing the latest filing.' },
        });
        fireEvent.change(screen.getByLabelText('assumptions.terminal_growth'), {
            target: { value: '0.03' },
        });
        fireEvent.click(screen.getAllByRole('button', { name: 'Recalculate' })[0]!);

        expect(onRecalculate).toHaveBeenCalledWith(expect.objectContaining({
            contract_version: 'fundamental.v1',
            path: 'assumptions.terminal_growth',
            value: '0.03',
            provenance: expect.objectContaining({
                reason: 'Updated after reviewing the latest filing.',
                automatic_preparation_digest: 'c'.repeat(64),
            }),
        }));
    });
});
