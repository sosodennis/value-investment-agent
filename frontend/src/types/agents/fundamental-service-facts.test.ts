import { describe, expect, it } from 'vitest';
import {
    parseFundamentalFacts,
    parseFundamentalServiceArtifact,
    sortFundamentalFacts,
} from './fundamental-service-facts';

const digest = 'a'.repeat(64);

const fact = (overrides: Record<string, unknown> = {}): Record<string, unknown> => ({
    contract_version: 'fundamental.v1',
    fact_id: 'fact-revenue',
    issuer_id: 'issuer-1',
    concept: 'us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax',
    normalized_field: 'revenue',
    value: '1000000',
    unit: 'USD',
    scale: 0,
    currency: 'USD',
    period_start: '2025-01-01',
    period_end: '2025-09-30',
    context: {
        concept_qname: 'us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax',
        period_type: 'duration',
        start_date: '2025-01-01',
        end_date: '2025-09-30',
        unit_qname: 'iso4217:USD',
        measure: 'iso4217:USD',
        dimensions: [],
        entity_scope: 'issuer-1',
        consolidation_scope: 'consolidated',
        context_id: 'ctx-revenue',
    },
    as_of: '2025-09-30T00:00:00Z',
    available_at: '2025-11-01T00:00:00Z',
    captured_at: '2025-11-02T00:00:00Z',
    taxonomy_version: 'us-gaap-2025',
    source: {
        source_url: 'https://www.sec.gov/Archives/filing.xml',
        content_hash: digest,
        source_role: 'filing',
        captured_at: '2025-11-02T00:00:00Z',
        available_at: '2025-11-01T00:00:00Z',
        filed_at: '2025-11-01T00:00:00Z',
        accession_number: '0000000000-25-000001',
        parser_version: 'arelle-1',
        taxonomy_version: 'us-gaap-2025',
        taxonomy_manifest_digest: digest,
        mapping_version: 'mapping-1',
    },
    quality: 'verified',
    issue_codes: [],
    ...overrides,
});

const result = (
    facts: Record<string, unknown>[],
    family: 'bank' | 'industrial' | 'reit' = 'industrial'
) => ({
    contract_version: 'fundamental.v1',
    snapshot_id: 'snapshot-1',
    data_release_manifest_digest: digest,
    snapshot_manifest_digest: digest,
    identity: {
        issuer_id: 'issuer-1',
        issuer_name: 'Example Corp',
        domicile: 'US',
        reporting_basis: 'us-gaap',
        security_id: 'security-1',
        share_class: 'common',
        currency: 'USD',
        family,
    },
    valuation_timestamp: '2026-11-07T00:00:00Z',
    quality_status: 'verified',
    issue_codes: [],
    facts,
});

const serviceArtifact = (family: 'bank' | 'industrial' | 'reit' = 'industrial') => ({
    projection_type: 'valuation',
    contract_version: 'fundamental.v1',
    snapshot_id: 'snapshot-1',
    snapshot_manifest_digest: digest,
    fact_ids: ['fact-revenue'],
    facts: result([fact({ family })], family),
    valuation_trace: {
        source_selection_policy: 'pit-v1',
        source_selection_policy_version: 'pit-v1',
        snapshot_id: 'snapshot-1',
        snapshot_manifest_digest: digest,
        fact_ids: ['fact-revenue'],
        source_content_hashes: [digest],
        policy_id: 'fcff-dcf-policy-v1',
        policy_version: 'policy-v1',
        policy_digest: digest,
        model_id: 'fcff_dcf',
        model_version: 'fcff_dcf-v1',
        assumptions_digest: digest,
        calculation_version: 'calculator-v1',
    },
    provenance: {
        snapshot_id: 'snapshot-1',
        mapping_version: 'mapping-v1',
        parser_version: 'parser-v1',
        taxonomy_version: 'taxonomy-v1',
        policy_version: 'policy-v1',
    },
    quality: {
        input: { status: 'verified' },
        validation_status: 'verified',
        facts_status: 'verified',
        calculation_status: 'verified',
        issue_codes: [],
    },
    hashes: {
        input_digest: digest,
        result_hash: digest,
        snapshot_manifest_digest: digest,
        source_content_hashes: [digest],
    },
    model_id: 'fcff_dcf',
    model_version: 'fcff_dcf-v1',
    calculation_version: 'calculator-v1',
    calculation_status: 'completed',
    quality_status: 'verified',
    input_digest: digest,
    result_hash: digest,
    evaluated_at: '2026-11-07T00:00:00Z',
    issue_codes: [],
    missing_evidence: [],
});

const factsOnlyArtifact = () => ({
    projection_type: 'facts_only',
    valuation_status: 'not_requested',
    contract_version: 'fundamental.v1',
    snapshot_id: 'snapshot-1',
    snapshot_manifest_digest: digest,
    fact_ids: ['fact-revenue'],
    facts: result([fact()]),
    provenance: {
        snapshot_id: 'snapshot-1',
        fact_ids: ['fact-revenue'],
        mapping_version: 'mapping-v1',
        parser_version: 'parser-v1',
        taxonomy_version: 'taxonomy-v1',
        policy_version: 'pit-v1',
    },
    quality: {
        facts_status: 'verified',
        issue_codes: [],
    },
    hashes: {
        snapshot_manifest_digest: digest,
        data_release_manifest_digest: digest,
        source_content_hashes: [digest],
    },
    issue_codes: [],
});

describe('parseFundamentalFacts', () => {
    it('parses service facts and preserves numeric zero, negative values, and provenance', () => {
        const parsed = parseFundamentalFacts(
            result([
                fact({ fact_id: 'fact-zero', normalized_field: 'cash', value: 0 }),
                fact({ fact_id: 'fact-negative', normalized_field: 'liabilities', value: '-12.5' }),
            ])
        );

        expect(parsed.identity.family).toBe('industrial');
        expect(parsed.facts.map((item) => item.fact_id)).toEqual([
            'fact-negative',
            'fact-zero',
        ]);
        expect(parsed.facts[0]?.value).toEqual({
            kind: 'numeric',
            raw: '-12.5',
            numeric: -12.5,
        });
        expect(parsed.facts[1]?.value).toEqual({
            kind: 'numeric',
            raw: '0',
            numeric: 0,
        });
        expect(parsed.facts[0]?.source.source_hash).toBe(digest);
        expect(parsed.facts[0]?.source.mapping_version).toBe('mapping-1');
    });

    it('distinguishes instant and duration periods and missing values', () => {
        const parsed = parseFundamentalFacts(
            result([
                fact({
                    fact_id: 'fact-instant',
                    normalized_field: 'assets',
                    value: {
                        status: 'unresolved',
                        reason: 'The service could not select a point-in-time fact.',
                    },
                    period_start: undefined,
                    period_end: '2025-09-30',
                    context: {
                        concept_qname: 'us-gaap:Assets',
                        period_type: 'instant',
                        instant: '2025-09-30',
                        unit_qname: 'iso4217:USD',
                        measure: 'iso4217:USD',
                        dimensions: [],
                        entity_scope: 'issuer-1',
                        consolidation_scope: 'consolidated',
                        context_id: 'ctx-assets',
                    },
                }),
            ])
        );

        expect(parsed.facts[0]?.period).toEqual({
            kind: 'instant',
            end: '2025-09-30',
            instant: '2025-09-30',
        });
        expect(parsed.facts[0]?.value).toEqual({
            kind: 'missing',
            status: 'unresolved',
            reason: 'The service could not select a point-in-time fact.',
        });
    });

    it('sorts by period end, start, kind, and fact id without mutating input', () => {
        const first = parseFundamentalFacts(result([
            fact({ fact_id: 'b', period_start: '2024-01-01', period_end: '2024-12-31' }),
            fact({ fact_id: 'a', period_start: '2025-01-01', period_end: '2025-09-30' }),
        ])).facts;
        const sorted = sortFundamentalFacts(first);
        expect(sorted.map((item) => item.fact_id)).toEqual(['a', 'b']);
        expect(first.map((item) => item.fact_id)).toEqual(['a', 'b']);
    });

    it('rejects a malformed digest and duplicate fact identity', () => {
        expect(() =>
            parseFundamentalFacts(
                result([
                    fact({
                        source: {
                            source_url: 'https://www.sec.gov/Archives/filing.xml',
                            content_hash: 'bad',
                            source_role: 'filing',
                            captured_at: '2025-11-02T00:00:00Z',
                            available_at: '2025-11-01T00:00:00Z',
                            parser_version: 'arelle-1',
                        },
                    }),
                ])
            )
        ).toThrowError('fundamental_service.facts[0].source.content_hash must be a lowercase SHA-256 digest.');

        expect(() =>
            parseFundamentalFacts(result([fact(), fact()]))
        ).toThrowError('fundamental_service.facts contains duplicate fact_id fact-revenue.');
    });
});

describe('parseFundamentalServiceArtifact', () => {
    it.each(['bank', 'industrial', 'reit'] as const)(
        'keeps typed %s family metadata and service facts as the source of truth',
        (family) => {
            const parsed = parseFundamentalServiceArtifact(serviceArtifact(family));

            if (parsed.projection_type !== 'valuation') {
                throw new Error('Expected a valuation projection.');
            }
            expect(parsed.facts.identity.family).toBe(family);
            expect(parsed.fact_ids).toEqual(['fact-revenue']);
            expect(parsed.valuation_trace.fact_ids).toEqual(['fact-revenue']);
            expect(parsed.hashes.snapshot_manifest_digest).toBe(digest);
            expect(parsed.facts.facts[0]?.value).toEqual({
                kind: 'numeric',
                raw: '1000000',
                numeric: 1000000,
            });
        }
    );

    it('rejects a projection whose snapshot binding changes between sections', () => {
        const payload = serviceArtifact();
        payload.valuation_trace.snapshot_id = 'other-snapshot';

        expect(() => parseFundamentalServiceArtifact(payload)).toThrowError(
            'fundamental_service snapshot_id is not bound to facts and valuation_trace.'
        );
    });

    it('rejects a projection whose trace fact IDs do not match selected facts', () => {
        const payload = serviceArtifact();
        payload.valuation_trace.fact_ids = ['fact-other'];

        expect(() => parseFundamentalServiceArtifact(payload)).toThrowError(
            'fundamental_service.fact_ids are not bound to facts and valuation_trace.'
        );
    });

    it('parses facts-only projections without creating valuation trace data', () => {
        const parsed = parseFundamentalServiceArtifact(factsOnlyArtifact());

        expect(parsed).toHaveProperty('projection_type', 'facts_only');
        expect(parsed).toHaveProperty('valuation_status', 'not_requested');
        expect(parsed.snapshot_id).toBe(parsed.facts.snapshot_id);
        expect(parsed.fact_ids).toEqual(['fact-revenue']);
        expect('valuation_trace' in parsed).toBe(false);
    });

    it('rejects valuation fields on a facts-only projection', () => {
        const payload: Record<string, unknown> = factsOnlyArtifact();
        payload.valuation_trace = serviceArtifact().valuation_trace;

        expect(() => parseFundamentalServiceArtifact(payload)).toThrowError(
            'fundamental_service facts-only projection cannot include valuation data.'
        );
    });
});
