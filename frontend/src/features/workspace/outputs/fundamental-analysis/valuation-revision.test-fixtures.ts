import type { ForwardEvidenceReview } from './forward-evidence-api';
import { preparation, snapshotDigest, timestamp, valuationReport } from './fundamental-report.test-fixtures';
import type { ValuationRevisionContext } from './valuation-revision';

export function revisionContext(runId = 'run-1'): ValuationRevisionContext {
    const source = { thread_id: 'thread-1', run_id: runId, artifact_id: `report-${runId}`, preparation_digest: snapshotDigest };
    return { source, sourceKey: JSON.stringify(source), savedValue: '0.02', ticker: 'EXAMPLE', issuerId: 'issuer-1', modelId: 'fcff_dcf', valuationTimestamp: timestamp, canApplyResearch: true };
}

export function editableReport() {
    const automatic = preparation();
    const original = automatic.assumptions_evidence[0];
    if (!original) throw new Error('Expected assumption fixture.');
    automatic.assumptions_evidence = [{ ...original, path: 'assumptions.terminal_growth', value: '0.02' }];
    return valuationReport({ automatic_preparation: automatic });
}

export function forwardReview(): ForwardEvidenceReview {
    return {
        contract_version: 'fundamental.v1', status: 'prepared', label: 'forward-looking external evidence',
        policy_version: 'forward-policy-v1', automatic_preparation_digest: snapshotDigest,
        claims: [{ claim_id: 'claim-1', issuer_id: 'issuer-1', ticker: 'EXAMPLE', model_id: 'fcff_dcf', metric: 'terminal_growth', assumption_path: 'assumptions.terminal_growth', value: '0.03', unit: 'ratio', fiscal_period: 'FY2030', period_type: 'annual', period_end: '2030-12-31', extraction_method: 'llm_from_source_passage', status: 'accepted', issue_codes: [], exclusion_reasons: [], source: {
            source_id: 'source-1', source_url: 'https://issuer.example/outlook', publisher: 'Example Investor Relations', source_type: 'issuer_guidance',
            retained_passage: 'The published long-term growth outlook is three percent.', content_hash: 'f'.repeat(64),
            published_at: timestamp, retrieved_at: timestamp, license_status: 'approved', license_reference: 'issuer-terms-v1',
        } }],
        accepted_claim_ids: ['claim-1'], excluded_claim_ids: [], issue_codes: [],
        budget: { policy_version: 'forward-policy-v1', max_search_queries: 2, max_results_per_query: 5, max_source_bytes: 120000, max_llm_claims: 8, max_duration_ms: 15000 },
        usage: { search_queries: 1, search_results: 1, source_fetches: 1, llm_calls: 1, llm_input_bytes: 1000, llm_output_tokens: null, elapsed_ms: 20 },
        reference_digest: 'a'.repeat(64),
        review_ref: { artifact_id: `forward-review-v1-${'b'.repeat(64)}`, content_hash: 'b'.repeat(64), media_type: 'application/json' },
    };
}

export function deferred<T>() {
    let resolve!: (value: T | PromiseLike<T>) => void;
    let reject!: (reason?: unknown) => void;
    const promise = new Promise<T>((onResolve, onReject) => { resolve = onResolve; reject = onReject; });
    return { promise, resolve, reject };
}
