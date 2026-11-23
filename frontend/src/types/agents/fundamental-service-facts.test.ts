import { describe, expect, it } from 'vitest';
import { parseFundamentalAutomaticPreparation, parseFundamentalServiceArtifact } from './fundamental-service-facts';
import { boundFacts, calculation, canonicalFact, factsOnlyReport, preparation, preparationOutcome, rootDigest, rootHash, sourceHash, timestamp, uncertaintyReport, valuationReport } from '@/features/workspace/outputs/fundamental-analysis/fundamental-report.test-fixtures';

describe('Fundamental artifact boundary', () => {
    it('retains the complete MC result, distinct root/base scopes and exact preparation', () => {
        const source = uncertaintyReport();
        const parsed = parseFundamentalServiceArtifact(source);
        expect(parsed).toEqual(source);
        if (parsed.projection_type !== 'valuation' || !('base' in parsed.service_result)) throw new Error('Expected uncertainty fixture.');
        expect(parsed.service_result.input_digest).toBe(rootDigest);
        expect(parsed.service_result.result_hash).toBe(rootHash);
        expect(parsed.service_result.base.input_digest).not.toBe(rootDigest);
        expect(parsed.automatic_preparation).toEqual(source.automatic_preparation);
        expect(parsed.service_result.quantiles?.p50).toBe('26.1234567890123456789');
    });
    it.each([9007199254740992, '1.5', '01', '-0', '+1'])('rejects a noncanonical public seed %s', (seed) => {
        const source = uncertaintyReport();
        expect(() => parseFundamentalServiceArtifact({ ...source, service_result: { ...source.service_result, seed } })).toThrow();
    });
    it('preserves omitted preparation collections', () => {
        const source = preparation();
        delete source.historical_metrics.working_capital_assessments;
        delete source.historical_metrics.working_capital_inputs;
        expect(parseFundamentalAutomaticPreparation(source)).toEqual(source);
        expect(parseFundamentalAutomaticPreparation(source).historical_metrics).not.toHaveProperty('working_capital_inputs');
    });
    it.each(['0', '-0.25', '1e400', '123456789012345678901234567890.123456789'])('preserves canonical Decimal %s without numeric coercion', (value) => {
        const source = valuationReport({ service_result: calculation({ intrinsic_value: value, per_share_value: value }) });
        expect(parseFundamentalServiceArtifact(source)).toEqual(source);
    });
    it('retains valuation evidence even when no canonical fact was selectable', () => {
        const source = valuationReport({
            fact_ids: [],
            facts: {
                ...boundFacts(), facts: [], fact_ids: [], projection_type: 'valuation_evidence', snapshot_timestamp: timestamp,
                model_id: 'fcff_dcf', mapping_version: 'sec-mapping-v3', profile_id: 'industrial-v1', profile_digest: sourceHash,
                data_release_manifest_digest: sourceHash, missing_fields: ['revenue'], rejected_fact_ids: ['rejected-1'],
                provenance: {}, quality: { facts_status: 'degraded', issue_codes: [], missing_fields: ['revenue'], rejected_fact_ids: ['rejected-1'] },
                hashes: { snapshot_manifest_digest: boundFacts().snapshot_manifest_digest, data_release_manifest_digest: sourceHash, source_content_hashes: [] },
            },
        });
        source.valuation_trace.fact_ids = [];
        source.hashes.source_content_hashes = [];
        expect(parseFundamentalServiceArtifact(source)).toEqual(source);
    });
    it('preserves missing, boolean and nonnumeric text facts with period, unit and provenance', () => {
        const source = factsOnlyReport();
        source.facts.facts = [canonicalFact({ value: { status: 'unresolved', reason: 'No verified period.' } }), canonicalFact({ fact_id: 'boolean', value: false }), canonicalFact({ fact_id: 'text', value: 'Not applicable to this class' })];
        source.facts.fact_ids = source.fact_ids = source.facts.facts.map((fact) => fact.fact_id);
        expect(parseFundamentalServiceArtifact(source)).toEqual(source);
    });
    it.each(['requires_input', 'abstained', 'unsupported'] as const)('accepts the typed %s preparation outcome', (status) => {
        expect(parseFundamentalServiceArtifact(preparationOutcome(status))).toEqual(preparationOutcome(status));
    });
    it('accepts an explicit service failure', () => {
        const source = { projection_type: 'degraded', contract_version: 'fundamental.v1', valuation_status: 'service_unavailable', quality_status: 'degraded', issue_codes: ['SERVICE_TIMEOUT'], service_failure: { code: 'SERVICE_TIMEOUT', message: 'Service timed out.', retryable: true } };
        expect(parseFundamentalServiceArtifact(source)).toEqual(source);
    });
    it.each(['input_digest', 'result_hash'] as const)('rejects a mismatched root %s', (key) => {
        const source = uncertaintyReport();
        source[key] = '0'.repeat(64);
        expect(() => parseFundamentalServiceArtifact(source)).toThrow(/identity mismatch/);
    });
    it('rejects a mixed root input digest and base result hash', () => {
        const source = uncertaintyReport();
        if (!('base' in source.service_result)) throw new Error('Expected uncertainty fixture.');
        source.hashes.result_hash = source.service_result.base.result_hash;
        expect(() => parseFundamentalServiceArtifact(source)).toThrow(/hashes.result_hash identity mismatch/);
    });
    it('rejects a snapshot/fact identity mismatch and duplicate facts', () => {
        const source = factsOnlyReport();
        source.snapshot_id = 'wrong-snapshot';
        expect(() => parseFundamentalServiceArtifact(source)).toThrow(/snapshot_id identity mismatch/);
        const duplicate = factsOnlyReport();
        duplicate.facts.facts.push(canonicalFact());
        expect(() => parseFundamentalServiceArtifact(duplicate)).toThrow(/duplicate fact_id/);
    });
    it('rejects truncated preparation markers and malformed Decimal values', () => {
        const source = preparation();
        expect(() => parseFundamentalAutomaticPreparation({ ...source, assumptions_evidence: [{ truncated_count: 1 }] })).toThrow();
        expect(() => parseFundamentalAutomaticPreparation({ ...source, assumptions_evidence: [{ ...source.assumptions_evidence[0], value: 'NaN' }] })).toThrow();
        expect(() => parseFundamentalAutomaticPreparation({ ...source, assumptions_evidence: [{ ...source.assumptions_evidence[0], value: 0.08 }] })).toThrow();
    });
    it('rejects unknown projections, absent service results and flattened numerical fallbacks', () => {
        expect(() => parseFundamentalServiceArtifact({ projection_type: 'unexpected' })).toThrow();
        expect(() => parseFundamentalServiceArtifact({ ...valuationReport(), service_result: undefined })).toThrow();
        expect(() => parseFundamentalServiceArtifact({ ...valuationReport(), intrinsic_value: 123 })).toThrow();
    });
});
