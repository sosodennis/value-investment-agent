import { describe, expect, it } from 'vitest';
import { parseFundamentalServiceArtifact } from '@/types/agents/fundamental-service-facts';
import { buildFundamentalEvidenceInventory, fundamentalReportSourceKey, projectFundamentalReport } from './fundamental-report-model';
import { baseDigest, baseHash, calculation, canonicalFact, conditionalQuantileBasis, factsOnlyReport, preparation, preparationOutcome, reference, rootDigest, rootHash, uncertaintyReport, valuationReport } from './fundamental-report.test-fixtures';

function project(artifact: unknown) {
    return projectFundamentalReport({ artifact: parseFundamentalServiceArtifact(artifact), reference, threadId: 'thread-1', ticker: 'EXAMPLE' });
}

describe('Fundamental report projection', () => {
    it('retains typed missing values and the metadata needed to assess historical comparability', () => {
        const source = factsOnlyReport();
        source.facts.facts = [canonicalFact({ value: { status: 'not_applicable', reason: 'No inventory for this issuer.' }, filing_version: 'original', accession_number: 'accession-1' })];
        const fact = project(source).facts[0];
        expect(fact?.normalizedField).toBe('revenue');
        expect(fact?.value).toEqual({ kind: 'unavailable', status: 'not_applicable', reason: 'No inventory for this issuer.' });
        expect(fact?.evidence.displayValue).toBe('Not applicable · No inventory for this issuer.');
        expect(fact?.context).toMatchObject({ issuerId: 'issuer-1', entityScope: 'issuer-1', consolidationScope: 'consolidated', periodType: 'duration', start: '2025-01-01', end: '2025-12-31', unitQname: 'iso4217:USD', accession: 'accession-1', filingVersion: 'original' });
    });

    it('marks only the service contract aliases while retaining equal canonical quantiles and all evidence', () => {
        const quantiles = { p05: '20', p50: '20', p95: '20', lower: '20', median: '20', upper: '20' };
        const report = project(uncertaintyReport({ quantiles, quantile_basis: conditionalQuantileBasis }));
        if (report.kind !== 'valuation' || report.uncertainty.kind !== 'provided') throw new Error('Expected uncertainty.');
        expect(report.uncertainty.quantiles.filter((item) => item.aliasOf === null).map((item) => item.label)).toEqual(['p05', 'p50', 'p95']);
        expect(buildFundamentalEvidenceInventory(report).items.filter((item) => item.title.startsWith('Model quantile'))).toHaveLength(6);
        const unbound = project(uncertaintyReport({ quantiles }));
        if (unbound.kind !== 'valuation' || unbound.uncertainty.kind !== 'provided') throw new Error('Expected uncertainty.');
        expect(unbound.uncertainty.quantiles.every((item) => item.aliasOf === null)).toBe(true);
    });

    it('binds result actions to their own base or scenario calculation and keeps manual origin', () => {
        const source = uncertaintyReport({ scenario_results: [calculation({ input_digest: rootDigest, result_hash: rootHash })] });
        const automatic = preparation();
        const original = automatic.assumptions_evidence[0];
        if (!original) throw new Error('Expected assumption.');
        automatic.assumptions_evidence = [{ ...original, method: 'manual', manual_provenance: { author: 'user-1', automatic_preparation_digest: baseDigest, modified_at: original.as_of, reason: 'Retained origin.' } }];
        source.automatic_preparation = automatic;
        const report = project(source);
        if (report.kind !== 'valuation' || report.uncertainty.kind !== 'provided') throw new Error('Expected valuation.');
        expect(report.base.perShare?.evidence).toMatchObject({ value: '25.1234567890123456789', displayValue: 'USD 25.12 / share', inputDigest: baseDigest, resultHash: baseHash });
        expect(report.uncertainty.scenarios[0]?.perShare?.evidence).toMatchObject({ title: 'Service scenario 1 per share', inputDigest: rootDigest, resultHash: rootHash });
        expect(report.base.perShare?.evidence.id).not.toBe(report.uncertainty.scenarios[0]?.perShare?.evidence.id);
        expect(report.preparationSummary?.assumptions[0]?.originalPreparationDigest).toBe(baseDigest);
    });
    it('preserves service conditional quantile provenance and rejects changes to its sampled paths', () => {
        const source = uncertaintyReport({ quantile_basis: conditionalQuantileBasis });
        const report = project(source);
        if (report.kind !== 'valuation' || report.uncertainty.kind !== 'provided') throw new Error('Expected uncertainty.');
        expect(report.uncertainty.quantileBasis).toEqual(conditionalQuantileBasis);
        expect(() => project({ ...source, service_result: { ...source.service_result, quantile_basis: { ...conditionalQuantileBasis, sampled_paths: [] } } })).toThrow();
    });
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
        expect(report.facts[0]?.value).toEqual({ kind: 'number', raw: '1000000.00000000000001', semantic: { kind: 'money', currency: 'USD' } });
        expect(report.facts[0]?.evidence.displayValue).toBe('USD 1.00M');
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
    it('builds one inventory with distinct automatic/manual and base/scenario evidence scopes', () => {
        const automatic = preparation();
        const assumption = automatic.assumptions_evidence[0];
        if (!assumption) throw new Error('Expected assumption fixture.');
        automatic.assumptions_evidence.push({ ...assumption, method: 'manual', value: '0.09', manual_provenance: {
            author: 'user-1', automatic_preparation_digest: automatic.preparation_digest, modified_at: assumption.as_of, reason: 'Updated expectation.',
            forward_reference: { claim_id: 'claim-1', source_url: 'https://source.example/outlook', source_content_hash: rootHash, citation: 'The exact retained passage used for this revision.', license_reference: 'issuer-terms-v1' },
        } });
        const source = uncertaintyReport({ scenario_results: [calculation(), calculation()] });
        source.automatic_preparation = automatic;
        const report = project(source);
        const inventory = buildFundamentalEvidenceInventory(report);
        expect(inventory.sourceKey).toBe(fundamentalReportSourceKey({ threadId: 'thread-1', reference }));
        expect(new Set(inventory.items.map((item) => item.id)).size).toBe(inventory.items.length);
        expect(inventory.items.filter((item) => item.title.startsWith('Assumption'))).toHaveLength(2);
        expect(inventory.items.find((item) => item.author === 'user-1')).toMatchObject({ source: 'https://source.example/outlook', sourceHash: rootHash, citation: 'The exact retained passage used for this revision.', licenseReference: 'issuer-terms-v1', rationale: 'Updated expectation.' });
        expect(inventory.items.filter((item) => item.title.startsWith('Calculation'))).toHaveLength(3);
        expect(inventory.items.find((item) => item.title.startsWith('Calculation'))).toMatchObject({
            inputs: ['enterprise_value', 'cash', 'debt'], source: 'revenue-1', inputDigest: baseDigest, resultHash: baseHash,
        });
        expect(inventory.items.find((item) => item.title === 'Model quantile · p50')).toMatchObject({ value: '26.1234567890123456789', inputDigest: rootDigest, resultHash: rootHash });
        expect(inventory.items.every((item) => item.threadId === 'thread-1' && item.runId === 'run-1' && item.artifactId === 'report-1')).toBe(true);
        if (report.kind !== 'valuation') throw new Error('Expected valuation.');
        expect(report.preparationSummary?.assumptions[1]).toMatchObject({ editable: true, method: 'manual', isManual: true });
    });
    it('never reuses fact selection keys across thread or run identities', () => {
        const artifact = parseFundamentalServiceArtifact(factsOnlyReport());
        const first = project(artifact);
        const next = projectFundamentalReport({ artifact, reference: { ...reference, download_url: '/api/v1/artifacts/report-1?run_id=run-2' }, threadId: 'thread-2', ticker: 'EXAMPLE' });
        expect(first.facts[0]?.evidence.id).not.toBe(next.facts[0]?.evidence.id);
    });
    it.each([
        { input: { assumptions: { terminal_growth: '0.025' } }, label: 'Applied manual assumption' },
        { input: { assumptions: { terminal_growth: '0.0250' } }, label: 'Manual assumption · application unconfirmed' },
        { input: { assumptions: { terminal_growth: 0.025 } }, label: 'Manual assumption · application unconfirmed' },
        { input: {}, label: 'Manual assumption · application unconfirmed' },
    ])('confirms each terminal-growth manual value against exact preparation input $input', ({ input, label }) => {
        const automatic = preparation({ input });
        const original = automatic.assumptions_evidence[0];
        if (!original) throw new Error('Expected assumption fixture.');
        automatic.assumptions_evidence = [
            { ...original, path: 'assumptions.terminal_growth', value: '0.0492' },
            { ...original, path: 'assumptions.terminal_growth', method: 'manual', value: '0.025', manual_provenance: { author: 'user-1', automatic_preparation_digest: automatic.preparation_digest, modified_at: original.as_of, reason: 'Updated outlook.' } },
        ];
        const report = project(valuationReport({ automatic_preparation: automatic }));
        if (report.kind !== 'valuation') throw new Error('Expected valuation.');
        const rows = report.preparationSummary?.assumptions;
        expect(rows?.map((item) => [item.value.raw, item.revisionLabel])).toEqual([
            ['0.0492', 'Original retained assumption'], ['0.025', label],
        ]);
        expect(rows?.[0]?.evidence.title).toBe('Original retained assumption · assumptions.terminal_growth');
        expect(rows?.[1]?.evidence.title).toBe(`${label} · assumptions.terminal_growth`);
        expect(rows?.map((item) => JSON.parse(item.evidence.id).slice(-2))).toEqual([
            ['assumption', 'assumptions.terminal_growth:0'], ['assumption', 'assumptions.terminal_growth:1'],
        ]);
    });
    it('confirms matching manual evidence independently of order and leaves other paths unchanged', () => {
        const automatic = preparation({ input: { assumptions: { terminal_growth: '0.025' } } });
        const original = automatic.assumptions_evidence[0];
        if (!original) throw new Error('Expected assumption fixture.');
        const manual = { ...original, path: 'assumptions.terminal_growth', method: 'manual', manual_provenance: { author: 'user-1', automatic_preparation_digest: automatic.preparation_digest, modified_at: original.as_of, reason: 'Updated outlook.' } } satisfies typeof original;
        automatic.assumptions_evidence = [original, { ...original, path: 'assumptions.terminal_growth' }, { ...manual, value: '0.025' }, { ...manual, value: '0.03' }];
        const report = project(valuationReport({ automatic_preparation: automatic }));
        if (report.kind !== 'valuation') throw new Error('Expected valuation.');
        expect(report.preparationSummary?.assumptions.map((item) => item.revisionLabel)).toEqual([
            null, 'Original retained assumption', 'Applied manual assumption', 'Manual assumption · application unconfirmed',
        ]);
        expect(report.preparationSummary?.assumptions[0]?.evidence.title).toBe('Assumption · assumptions.wacc');
    });
    it('leaves an original terminal-growth assumption unchanged when no manual evidence exists', () => {
        const automatic = preparation();
        automatic.assumptions_evidence = automatic.assumptions_evidence.map((item) => ({ ...item, path: 'assumptions.terminal_growth' }));
        const report = project(valuationReport({ automatic_preparation: automatic }));
        if (report.kind !== 'valuation') throw new Error('Expected valuation.');
        expect(report.preparationSummary?.assumptions[0]).toMatchObject({ revisionLabel: null, evidence: { title: 'Assumption · assumptions.terminal_growth' } });
    });
    it('keeps manual application unconfirmed when a preparation outcome has no input', () => {
        const source = preparationOutcome();
        const automatic = source.automatic_preparation;
        const original = automatic.assumptions_evidence[0];
        if (!original) throw new Error('Expected assumption fixture.');
        automatic.assumptions_evidence = [{ ...original, path: 'assumptions.terminal_growth', method: 'manual', value: '0.025', manual_provenance: { author: 'user-1', automatic_preparation_digest: automatic.preparation_digest, modified_at: original.as_of, reason: 'Updated outlook.' } }];
        const report = project(source);
        if (report.kind !== 'preparation-outcome') throw new Error('Expected preparation outcome.');
        expect(report.preparationSummary.assumptions[0]?.revisionLabel).toBe('Manual assumption · application unconfirmed');
    });
});
