import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { FundamentalReviewPanel } from './FundamentalReviewPanel';
import type { FundamentalAutomaticPreparation } from '@/types/agents/fundamental-service-facts';
import type { ForwardEvidenceReview } from './forward-evidence-api';

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

    it('runs explicit forward research and applies a cited claim as an override', () => {
        const onResearchForwardEvidence = vi.fn().mockResolvedValue(undefined);
        const onApplyForwardEvidence = vi.fn();
        const forwardPreparation: FundamentalAutomaticPreparation = {
            ...preparation,
            assumptions_evidence: [
                {
                    ...preparation.assumptions_evidence[0]!,
                    path: 'assumptions.forecast.revenue_growth[0]',
                },
                preparation.assumptions_evidence[1]!,
            ],
        };
        const review: ForwardEvidenceReview = {
            contract_version: 'fundamental.v1',
            status: 'prepared',
            label: 'forward-looking external evidence',
            policy_version: 'forward-evidence-policy-v1',
            automatic_preparation_digest: 'c'.repeat(64),
            claims: [
                {
                    claim_id: 'claim-1',
                    issuer_id: 'issuer-aapl',
                    ticker: 'AAPL',
                    model_id: 'fcff_dcf',
                    metric: 'revenue_growth',
                    assumption_path: 'assumptions.forecast.revenue_growth[0]',
                    value: '0.12',
                    unit: 'ratio',
                    fiscal_period: 'FY2027',
                    period_type: 'annual',
                    period_end: '2027-09-30',
                    extraction_method: 'llm_from_source_passage',
                    source: {
                        source_id: 'source-1',
                        source_url: 'https://issuer.example/guidance',
                        publisher: 'Issuer IR',
                        source_type: 'issuer_guidance',
                        retained_passage: 'Management expects revenue growth of 12 percent in fiscal 2027.',
                        content_hash: 'd'.repeat(64),
                        published_at: '2026-10-01T00:00:00Z',
                        retrieved_at: '2026-10-02T00:00:00Z',
                        license_status: 'approved',
                        license_reference: 'issuer-terms-v1',
                    },
                    status: 'accepted',
                    issue_codes: [],
                    exclusion_reasons: [],
                },
            ],
            accepted_claim_ids: ['claim-1'],
            excluded_claim_ids: [],
            issue_codes: [],
            budget: {
                policy_version: 'forward-evidence-policy-v1',
                max_search_queries: 2,
                max_results_per_query: 5,
                max_source_bytes: 120000,
                max_llm_claims: 8,
                max_duration_ms: 15000,
            },
            usage: {
                search_queries: 1,
                search_results: 1,
                source_fetches: 0,
                llm_calls: 1,
                llm_input_bytes: 1000,
                llm_output_tokens: null,
                elapsed_ms: 12,
            },
            reference_digest: 'e'.repeat(64),
        };

        render(
            <FundamentalReviewPanel
                preparation={forwardPreparation}
                ticker="AAPL"
                forwardEvidence={review}
                onResearchForwardEvidence={onResearchForwardEvidence}
                onApplyForwardEvidence={onApplyForwardEvidence}
            />
        );

        fireEvent.change(screen.getByLabelText('Evidence question'), {
            target: { value: 'What is the next annual revenue growth guidance?' },
        });
        fireEvent.click(screen.getByRole('button', { name: 'Research evidence' }));
        expect(onResearchForwardEvidence).toHaveBeenCalledWith(
            'What is the next annual revenue growth guidance?',
            'assumptions.forecast.revenue_growth[0]'
        );

        fireEvent.click(screen.getByRole('button', { name: 'Apply to valuation' }));
        expect(onApplyForwardEvidence).toHaveBeenCalledWith(expect.objectContaining({
            path: 'assumptions.forecast.revenue_growth[0]',
            value: '0.12',
            provenance: expect.objectContaining({
                automatic_preparation_digest: 'c'.repeat(64),
                forward_reference: expect.objectContaining({
                    claim_id: 'claim-1',
                    source_content_hash: 'd'.repeat(64),
                    license_reference: 'issuer-terms-v1',
                }),
            }),
        }));
    });
});
