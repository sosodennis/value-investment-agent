import { describe, expect, it } from 'vitest';
import { parseForwardEvidenceReview } from './forward-evidence-api';

const validResponse = {
    result: {
        contract_version: 'fundamental.v1',
        status: 'prepared',
        label: 'forward-looking external evidence',
        policy_version: 'forward-evidence-policy-v1',
        automatic_preparation_digest: 'a'.repeat(64),
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
                    content_hash: 'b'.repeat(64),
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
            elapsed_ms: 20,
        },
        reference_digest: 'c'.repeat(64),
    },
};

describe('parseForwardEvidenceReview', () => {
    it('returns a typed review with nested source provenance', () => {
        const review = parseForwardEvidenceReview(validResponse);
        expect(review.claims[0]?.source.source_url).toBe('https://issuer.example/guidance');
        expect(review.usage.source_fetches).toBe(0);
    });

    it('rejects malformed nested source data', () => {
        expect(() => parseForwardEvidenceReview({
            result: {
                ...validResponse.result,
                claims: [{
                    ...validResponse.result.claims[0],
                    source: {
                        ...validResponse.result.claims[0].source,
                        source_url: 'javascript:alert(1)',
                    },
                }],
            },
        })).toThrow(/http or https URL/);
    });
});
