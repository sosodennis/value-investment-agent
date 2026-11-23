import { describe, expect, it } from 'vitest';
import { parseFundamentalServiceArtifact } from '@/types/agents/fundamental-service-facts';
import { projectFundamentalReport } from './fundamental-report-model';
import { baseDigest, baseHash, calculation, factsOnlyReport, preparationOutcome, reference, rootDigest, rootHash, uncertaintyReport, valuationReport } from './fundamental-report.test-fixtures';

function project(artifact: unknown) {
    return projectFundamentalReport({ artifact: parseFundamentalServiceArtifact(artifact), reference, threadId: 'thread-1', ticker: 'EXAMPLE' });
}

describe('Fundamental report projection', () => {
    it('keeps deterministic base, median, root/base bindings and identities independent', () => {
        const report = project(uncertaintyReport());
        if (report.kind !== 'valuation' || report.uncertainty.kind !== 'provided') throw new Error('Expected valuation.');
        expect(report.identity).toMatchObject({ threadId: 'thread-1', runId: 'run-1', artifactId: 'report-1' });
        expect(report.reportBinding).toEqual({ inputDigest: rootDigest, resultHash: rootHash });
        expect(report.base.binding).toEqual({ inputDigest: baseDigest, resultHash: baseHash });
        expect(report.base.equity?.basis).toBe('equity-total');
        expect(report.base.perShare?.raw).toBe('25.1234567890123456789');
        expect(report.uncertainty.quantiles.find((item) => item.label === 'p50')?.value.raw).toBe('26.1234567890123456789');
        expect(report.uncertainty.evidenceReferences[0]?.artifact_type).toBe('uncertainty_evidence');
        expect(report.base.evidenceReferences[0]?.artifact_type).toBe('calculation_evidence');
        expect(report.uncertainty.seed).toBe('0');
        expect(report.facts[0]?.value).toBe('1000000.00000000000001');
        expect(report.facts[0]?.scale).toBe(6);
        expect(report.facts[0]?.dimensions).toEqual([{ name: 'SegmentAxis', member: 'CloudMember' }]);
    });
    it.each(['0', '-0.25', '1e400'])('retains exact amount %s even when plotting is unavailable', (raw) => {
        const report = project(valuationReport({ service_result: calculation({ intrinsic_value: raw, per_share_value: null }) }));
        if (report.kind !== 'valuation') throw new Error('Expected valuation.');
        expect(report.base.equity?.raw).toBe(raw);
        expect(report.base.equity?.coordinate).toBe(raw === '1e400' ? null : Number(raw));
        expect(report.base.perShare).toBeNull();
    });
    it.each(['9007199254740993', '-18446744073709551615'])('keeps the exact seed %s through parsing and projection', (seed) => {
        const report = project(uncertaintyReport({ seed }));
        if (report.kind !== 'valuation' || report.uncertainty.kind !== 'provided') throw new Error('Expected uncertainty.');
        expect(report.uncertainty.seed).toBe(seed);
    });
    it('identifies zero-sample results as scenarios rather than Monte Carlo', () => {
        const report = project(uncertaintyReport({ requested_samples: 0, valid_samples: 0, invalid_samples: 0, quantiles: {} }));
        if (report.kind !== 'valuation' || report.uncertainty.kind !== 'provided') throw new Error('Expected uncertainty.');
        expect(report.uncertainty.mode).toBe('scenarios');
        expect(report.uncertainty.quantiles).toEqual([]);
        expect(report.base.perShare?.raw).toBe('25.1234567890123456789');
    });
    it('keeps a valid base visible when uncertainty abstains and supplies partial quantiles', () => {
        const report = project(uncertaintyReport({ status: 'abstain', quantiles: { p05: '10.123' }, valid_samples: 1, invalid_samples: 99 }));
        if (report.kind !== 'valuation' || report.uncertainty.kind !== 'provided') throw new Error('Expected uncertainty.');
        expect(report.quality).toBe('abstain');
        expect(report.base.status).toBe('completed');
        expect(report.base.perShare?.raw).toBe('25.1234567890123456789');
        expect(report.uncertainty.quantiles.map((item) => item.label)).toEqual(['p05']);
        expect(report.uncertainty.sensitivity[0]?.values.map((value) => value.raw)).toEqual(['24.1234567890123', '25.9876543210123']);
    });
    it('distinguishes facts-only and preparation refusals from execution', () => {
        expect(project(factsOnlyReport()).kind).toBe('facts-only');
        const report = project(preparationOutcome());
        expect(report).toMatchObject({ kind: 'preparation-outcome', outcome: 'requires_input', reason: 'Share count evidence is unavailable.', missingEvidence: ['shares_outstanding'] });
        expect(report).not.toHaveProperty('base');
    });
});
