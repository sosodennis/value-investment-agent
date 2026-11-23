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
        expect(parseFundamentalServiceArtifact(source)).toEqual(source);
    });
    it('retains the complete calculation source scope with repeated non-fact sources', () => {
        const source = uncertaintyReport();
        const hashes = [sourceHash, '1'.repeat(64), '1'.repeat(64), '2'.repeat(64)];
        source.valuation_trace.source_content_hashes = hashes;
        source.hashes.source_content_hashes = [...hashes];
        expect(parseFundamentalServiceArtifact(source)).toEqual(source);
    });
    it.each([
        { hashes: [sourceHash, '1'.repeat(64)] },
        { hashes: ['1'.repeat(64), sourceHash, '1'.repeat(64)] },
    ])('rejects a changed calculation source hash sequence $hashes', ({ hashes }) => {
        const source = uncertaintyReport();
        source.valuation_trace.source_content_hashes = [sourceHash, '1'.repeat(64), '1'.repeat(64)];
        source.hashes.source_content_hashes = hashes;
        expect(() => parseFundamentalServiceArtifact(source)).toThrow(/hashes.source_content_hashes identity mismatch/);
    });
    it('rejects calculation evidence that omits a selected fact source', () => {
        const source = valuationReport();
        source.hashes.source_content_hashes = source.valuation_trace.source_content_hashes = ['1'.repeat(64)];
        expect(() => parseFundamentalServiceArtifact(source)).toThrow(/missing a selected fact source hash/);
    });
    it('rejects additional source hashes in the facts-only scope', () => {
        const source = factsOnlyReport();
        source.hashes.source_content_hashes.push('1'.repeat(64));
        expect(() => parseFundamentalServiceArtifact(source)).toThrow(/hashes.source_content_hashes identity mismatch/);
    });
    it('preserves missing, boolean and nonnumeric text facts with period, unit and provenance', () => {
        const source = factsOnlyReport();
        const textFact = canonicalFact({ fact_id: 'text', normalized_field: 'issuer_description', unit: 'text', currency: null, value: 'Not applicable to this class' });
        textFact.context.unit_qname = textFact.context.measure = 'text';
        source.facts.facts = [canonicalFact({ value: { status: 'unresolved', reason: 'No verified period.' } }), canonicalFact({ fact_id: 'boolean', value: false }), textFact];
        source.facts.fact_ids = source.fact_ids = source.facts.facts.map((fact) => fact.fact_id);
        expect(parseFundamentalServiceArtifact(source)).toEqual(source);
    });
    it.each(['NaN', 'Infinity', '', 'not-a-number', '1,000', 42])('rejects malformed numeric fact value %s at the artifact boundary', (value) => {
        const source = factsOnlyReport();
        const fact = source.facts.facts[0];
        expect(() => parseFundamentalServiceArtifact({ ...source, facts: { ...source.facts, facts: [{ ...fact, value }] } })).toThrow(TypeError);
    });
    it.each(['2025-99-99', '2025-02-29', '2024-02-30', '2025-04-31', '2025-00-01'])('rejects invalid calendar date %s before history projection', (period) => {
        const source = factsOnlyReport();
        source.facts.facts = [canonicalFact({ period_end: period, context: { ...canonicalFact().context, end_date: period } })];
        expect(() => parseFundamentalServiceArtifact(source)).toThrow(/valid ISO calendar date/);
    });
    it('accepts a valid leap day and rejects impossible timestamp calendar days', () => {
        const source = factsOnlyReport();
        source.facts.facts = [canonicalFact({ period_end: '2024-02-29', context: { ...canonicalFact().context, end_date: '2024-02-29' } })];
        expect(parseFundamentalServiceArtifact(source)).toEqual(source);
        source.facts.facts = [canonicalFact({ available_at: '2025-02-29T12:00:00Z' })];
        expect(() => parseFundamentalServiceArtifact(source)).toThrow(/valid ISO calendar date/);
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
