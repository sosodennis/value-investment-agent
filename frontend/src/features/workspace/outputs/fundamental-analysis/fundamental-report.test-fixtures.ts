import type { components } from '@/types/generated/api-contract';

type Contracts = components['schemas'];
export const rootDigest = 'a'.repeat(64);
export const rootHash = 'b'.repeat(64);
export const baseDigest = 'c'.repeat(64);
export const baseHash = 'd'.repeat(64);
export const snapshotDigest = 'e'.repeat(64);
export const sourceHash = 'f'.repeat(64);
export const timestamp = '2026-11-23T00:00:00Z';

export const identity: Contracts['FundamentalIdentityV1'] = {
    issuer_id: 'issuer-1', issuer_name: 'Example Corp', domicile: 'US', reporting_basis: 'us-gaap',
    security_id: 'security-1', share_class: 'Class A', currency: 'USD',
};
export function canonicalFact(overrides: Partial<Contracts['FundamentalCanonicalFactV1']> = {}): Contracts['FundamentalCanonicalFactV1'] {
    return {
        contract_version: 'fundamental.v1', fact_id: 'revenue-1', issuer_id: 'issuer-1',
        concept: 'us-gaap:Revenue', normalized_field: 'revenue', value: '1000000.00000000000001',
        unit: 'USD', scale: 6, currency: 'USD', period_start: '2025-01-01', period_end: '2025-12-31',
        context: {
            concept_qname: 'us-gaap:Revenue', period_type: 'duration', start_date: '2025-01-01', end_date: '2025-12-31',
            unit_qname: 'iso4217:USD', measure: 'iso4217:USD', dimensions: [{ name: 'SegmentAxis', member: 'CloudMember' }],
            entity_scope: 'issuer-1', consolidation_scope: 'consolidated', context_id: 'context-1',
        },
        as_of: timestamp, available_at: timestamp, captured_at: timestamp, is_amendment: false,
        taxonomy_version: 'us-gaap-2025',
        source: {
            source_url: 'https://www.sec.gov/Archives/example.xml', content_hash: sourceHash, source_role: 'filing',
            captured_at: timestamp, available_at: timestamp, parser_version: 'parser-1',
        },
        quality: 'provisional', issue_codes: ['SELECTED_FACTS_ONLY'], rejected_candidates: [], rejected_candidate_reasons: [],
        ...overrides,
    };
}
export function boundFacts(): Contracts['FundamentalBoundFactsV1'] {
    return {
        contract_version: 'fundamental.v1', snapshot_id: 'snapshot-1', snapshot_manifest_digest: snapshotDigest,
        data_release_manifest_digest: sourceHash, identity, valuation_timestamp: timestamp,
        quality_status: 'provisional', issue_codes: [], facts: [canonicalFact()], fact_ids: ['revenue-1'],
    };
}
export function calculation(overrides: Partial<Contracts['FundamentalCalculationResultV1']> = {}): Contracts['FundamentalCalculationResultV1'] {
    return {
        contract_version: 'fundamental.v1', calculation_version: 'calculator-1', calculation_status: 'completed',
        quality_status: 'provisional', input_digest: baseDigest, result_hash: baseHash,
        intrinsic_value: '2500000000.1234567890123456789', per_share_value: '25.1234567890123456789',
        nodes: [{ node_id: 'equity_value', value: '2500000000.1234567890123456789', unit: 'USD', formula: 'enterprise_value + cash - debt', inputs: ['enterprise_value', 'cash', 'debt'], trace: { source_refs: ['revenue-1'], source_ids: [], source_uris: [], source_versions: [], terms_references: [], inputs: ['enterprise_value', 'cash', 'debt'] } }],
        assumptions: { wacc: '0.08', currency: 'USD' }, model_version: 'fcff-v1',
        artifact_references: [{ artifact_id: 'calculation-evidence', artifact_type: 'calculation_evidence', content_hash: baseHash, media_type: 'application/json' }],
        issue_codes: ['UNCALIBRATED'], missing_evidence: [], snapshot_id: 'snapshot-1',
        valuation_timestamp: timestamp, evaluated_at: timestamp, correlation_id: 'correlation-1', ...overrides,
    };
}
export function preparation(overrides: Partial<Contracts['FundamentalValuationPreparationResultV1']> = {}): Contracts['FundamentalValuationPreparationResultV1'] {
    return {
        contract_version: 'fundamental.v1', status: 'prepared', model_id: 'fcff_dcf', model_version: 'fcff-v1',
        profile_id: 'industrial-v1', profile_digest: snapshotDigest, policy_id: 'policy-1', policy_version: 'policy-v1',
        quality_status: 'provisional', issue_codes: ['UNCALIBRATED'], missing_evidence: [],
        historical_metrics: {
            profile_id: 'industrial-v1', profile_digest: snapshotDigest, quality_status: 'provisional', issue_codes: [], missing_evidence: [],
            metrics: [{ metric_id: 'revenue', fiscal_year: 2025, value: '1000000.00000000000001', unit: 'USD', formula: 'selected_revenue', fact_ids: ['revenue-1'], source_refs: [], period_end: '2025-12-31' }],
            working_capital_assessments: [], working_capital_inputs: [],
        },
        assumptions_evidence: [{ path: 'assumptions.wacc', value: '0.08', method: 'approved_policy', formula: 'policy.wacc', fact_ids: ['revenue-1'], source_refs: ['policy-1'], policy_version: 'policy-v1', as_of: timestamp, editable: true }],
        input: { snapshot_id: 'snapshot-1', assumptions: { wacc: '0.08' }, retained: { optional: null, amount: '1e400' } },
        conditional_capital: { retained: [{ instrument_id: 'instrument-1', amount: '123.4567890123456789' }] },
        preparation_digest: snapshotDigest, ...overrides,
    };
}
export function valuationReport(overrides: Partial<Contracts['FundamentalValuationReportV1']> = {}): Contracts['FundamentalValuationReportV1'] {
    return {
        projection_type: 'valuation', contract_version: 'fundamental.v1', calculation_version: 'calculator-1',
        calculation_status: 'completed', quality_status: 'provisional', input_digest: baseDigest, result_hash: baseHash,
        service_result: calculation(), correlation_id: 'correlation-1', facts: boundFacts(),
        snapshot_id: 'snapshot-1', snapshot_manifest_digest: snapshotDigest, fact_ids: ['revenue-1'],
        valuation_trace: {
            valuation_timestamp: timestamp, fiscal_period_selector: { version: 'fundamental.fiscal-period-selector.v1', mode: 'latest_complete', count: 1, periods: [] }, resolved_fiscal_periods: [],
            source_selection_policy: 'pit', source_selection_policy_version: 'pit-v1', snapshot_id: 'snapshot-1',
            snapshot_manifest_digest: snapshotDigest, fact_ids: ['revenue-1'], source_content_hashes: [sourceHash],
            policy_id: 'policy-1', policy_version: 'policy-v1', policy_digest: snapshotDigest,
            model_id: 'fcff_dcf', model_version: 'fcff-v1', assumptions_digest: baseDigest, calculation_version: 'calculator-1',
        },
        provenance: { snapshot_id: 'snapshot-1', fact_ids: ['revenue-1'] },
        quality: { input: { status: 'provisional' }, validation_status: 'provisional', facts_status: 'provisional', calculation_status: 'provisional', issue_codes: ['UNCALIBRATED'] },
        hashes: { input_digest: baseDigest, result_hash: baseHash, snapshot_manifest_digest: snapshotDigest, data_release_manifest_digest: sourceHash, source_content_hashes: [sourceHash] },
        valuation_input: { currency: 'USD' }, automatic_preparation: preparation(), ...overrides,
    };
}
export function uncertaintyReport(overrides: Partial<Contracts['FundamentalUncertaintyResultV1']> = {}): Contracts['FundamentalValuationReportV1'] {
    const result: Contracts['FundamentalUncertaintyResultV1'] = {
        status: 'provisional', input_digest: rootDigest, result_hash: rootHash, base: calculation(), scenario_results: [],
        sensitivity: { 'assumptions.wacc': ['24.1234567890123', '25.9876543210123'] },
        requested_samples: 100, valid_samples: 98, invalid_samples: 2, invalid_reasons: { OUT_OF_BOUNDS: 2 },
        seed: '0', sampler_version: 'sampler-v1', invalid_draw_policy: 'discard',
        quantiles: { p05: '20.1234567890123456789', p50: '26.1234567890123456789', p95: '33.1234567890123456789' },
        quantile_contract: { bear: 'p05', base: 'p50', bull: 'p95' },
        convergence_diagnostics: { minimum_valid_samples: 10, invalid_ratio: '0.02', converged: true },
        dominant_drivers: ['assumptions.wacc'], artifact_references: [{ artifact_id: 'uncertainty-evidence', artifact_type: 'uncertainty_evidence', content_hash: rootHash, media_type: 'application/json' }], ...overrides,
    };
    return valuationReport({
        input_digest: rootDigest, result_hash: rootHash, quality_status: result.status, service_result: result,
        hashes: { input_digest: rootDigest, result_hash: rootHash, snapshot_manifest_digest: snapshotDigest, data_release_manifest_digest: sourceHash, source_content_hashes: [sourceHash] },
    });
}
export function factsOnlyReport(): Contracts['FundamentalFactsOnlyReportV1'] {
    return {
        projection_type: 'facts_only', contract_version: 'fundamental.v1', valuation_status: 'not_requested',
        snapshot_id: 'snapshot-1', snapshot_timestamp: timestamp, snapshot_manifest_digest: snapshotDigest, fact_ids: ['revenue-1'], facts: boundFacts(),
        snapshot_selector: { snapshot_id: 'snapshot-1' }, provenance: {}, quality: { facts_status: 'provisional', issue_codes: [], missing_fields: [], rejected_fact_ids: [] },
        hashes: { snapshot_manifest_digest: snapshotDigest, data_release_manifest_digest: sourceHash, source_content_hashes: [sourceHash] }, issue_codes: [],
    };
}
export function preparationOutcome(status: 'requires_input' | 'abstained' | 'unsupported' = 'requires_input'): Contracts['FundamentalPreparationOutcomeV1'] {
    return {
        projection_type: 'preparation_outcome', contract_version: 'fundamental.v1', valuation_status: status,
        quality_status: 'unsupported', automatic_preparation: preparation({ status, input: null }),
        identity, snapshot_selector: { snapshot_id: 'snapshot-1' }, issue_codes: ['MISSING_SHARES'],
        missing_evidence: ['shares_outstanding'], reason: 'Share count evidence is unavailable.',
    };
}
export const reference = { artifact_id: 'report-1', download_url: '/api/v1/artifacts/report-1?run_id=run-1', type: 'financial_reports' };
