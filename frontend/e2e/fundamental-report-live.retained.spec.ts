import { createHash } from 'node:crypto';
import { readFile, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { expect, test, type TestInfo } from '@playwright/test';
import { parseArtifactEnvelope } from '../src/types/agents/artifact-envelope-parser';
import { parseFundamentalArtifact } from '../src/types/agents/artifact-parsers';
import { parseWorkflowActivitySnapshot } from '../src/features/workflow/workflow-activity';
import { buildFundamentalEvidenceInventory, projectFundamentalReport } from '../src/features/workspace/outputs/fundamental-analysis/fundamental-report-model';
import { formatReportDatum, formatReportNumber, type NumberSemantic } from '../src/features/workspace/outputs/fundamental-analysis/fundamental-number-format';
import { projectForecastSeries, projectHistoricalSeries } from '../src/features/workspace/outputs/fundamental-analysis/fundamental-report-series';

const fixtures = {
    base: {
        stem: 'post-merge-manual-base',
        artifactSha256: '192c54598fc4cd88fc79c8dfc3a6ac8870aa9ccdd28eb35793a7ada26798549c',
        snapshotSha256: '5ccf46df43adf87e7e23399abc18fc7b4290d5d69dd3b2aadb81e9095ea68a68',
        threadId: 'thread_4c616328-3308-4662-ad27-b0fc2e6a5b67',
        runId: 'bacbf333-83c7-450b-bc23-4e0e06dcf224',
        artifactId: '505feae3-faf5-4f68-a4ca-e05c136884d5',
    },
    revision: {
        stem: 'final-revision-success',
        artifactSha256: '09c39098a5a673a81a73eff756688a40a1ab931345dd41a84659e574494ea2e1',
        snapshotSha256: 'b4d9bdb6aa3b89cb062b3798b614d7b795a9578139bb9afeeea561ae45a0f8ad',
        threadId: 'thread_68e1931a-d1be-44bc-b1d0-2833805f9cbb',
        runId: 'e45bb96f-1162-400d-9004-5c6b20ed7afb',
        artifactId: 'b35d7e0e-2f4a-46d9-a0f8-dd247aa641f0',
    },
    refusal: {
        stem: 'final-policy-refusal',
        artifactSha256: '8933403ec7631ebca2b6833fca13b6244e37699f514a09403c10cc37bb665449',
        snapshotSha256: '864a730ed6ebe332eef7640a18fb00f53d54a69d8e51a3fca27a79fe27d96ea1',
        threadId: 'thread_6192b5c9-ad8a-40f4-b99d-f3661f89e3e9',
        runId: '2acd0736-c6de-43be-a056-109645dc31d6',
        artifactId: 'a32cc9d2-7965-41a1-834a-7767da88c6fb',
    },
};
const originalPreparation = 'a8a5da8d918dabb5aeb4479d4dd3be0528f36962f51b8503db2e53578e18a5dd';
const perShare: NumberSemantic = { kind: 'per-share', currency: 'USD' };

async function loadRetained(name: keyof typeof fixtures) {
    const directory = process.env.FUNDAMENTAL_RETAINED_DIR;
    if (!directory) throw new Error('FUNDAMENTAL_RETAINED_DIR must point to the complete retained artifacts and snapshots.');
    const fixture = fixtures[name];
    const [artifactText, snapshotText] = await Promise.all([
        readFile(join(directory, `${fixture.stem}-artifact.json`), 'utf8'),
        readFile(join(directory, `${fixture.stem}-snapshot.json`), 'utf8'),
    ]);
    expect(createHash('sha256').update(artifactText).digest('hex')).toBe(fixture.artifactSha256);
    expect(createHash('sha256').update(snapshotText).digest('hex')).toBe(fixture.snapshotSha256);
    const snapshotPayload: unknown = JSON.parse(snapshotText);
    const snapshot = parseWorkflowActivitySnapshot(snapshotPayload);
    expect(snapshot.thread_id).toBe(fixture.threadId);
    expect(snapshot.run_id).toBe(fixture.runId);
    expect(snapshot.run_status).toBe('completed');
    expect(snapshot.failure).toBeNull();
    const output = snapshot.completed_outputs.find((item) => item.agent_id === 'fundamental_analysis');
    if (!output?.artifact_id) throw new Error('The retained snapshot has no Fundamental artifact identity.');
    expect(output.artifact_id).toBe(fixture.artifactId);
    expect(output.identity.thread_id).toBe(snapshot.thread_id);
    expect(output.identity.run_id).toBe(snapshot.run_id);
    const artifactPayload: unknown = JSON.parse(artifactText);
    const envelope = parseArtifactEnvelope(artifactPayload, fixture.stem, 'financial_reports');
    const parsed = parseFundamentalArtifact(envelope.data);
    if (!parsed.fundamental_service) throw new Error('The complete retained artifact has no typed Fundamental projection.');
    expect(parsed.ticker).toBe('MSFT');
    const artifactUrl = `/api/v1/artifacts/${encodeURIComponent(output.artifact_id)}?${new URLSearchParams({ run_id: snapshot.run_id })}`;
    const report = projectFundamentalReport({
        artifact: parsed.fundamental_service,
        reference: { artifact_id: output.artifact_id, download_url: artifactUrl },
        threadId: snapshot.thread_id,
        ticker: parsed.ticker,
    });
    return { fixture, createdAt: envelope.created_at, service: parsed.fundamental_service, report };
}

async function recordRetained(info: TestInfo, name: string, source: Awaited<ReturnType<typeof loadRetained>>, observations: object) {
    const path = info.outputPath(`${name}.json`);
    await writeFile(path, JSON.stringify({
        evidenceKind: 'retained-artifact-regression',
        observedAt: new Date().toISOString(),
        fixture: source.fixture,
        artifactCreatedAt: source.createdAt,
        identity: source.report.identity,
        observations,
    }, null, 2));
    await info.attach(name, { path, contentType: 'application/json' });
}

test.describe('Fundamental retained artifact regression', () => {
    test.skip(!process.env.FUNDAMENTAL_RETAINED_DIR, 'Requires the complete #462 retained artifact/snapshot pairs. A skip is not acceptance evidence.');

    test('F01–F03 and F05–F09 preserve the fixed MSFT report through parser and view model', async ({}, info) => {
        const source = await loadRetained('base');
        const { report, service } = source;
        if (report.kind !== 'valuation' || report.uncertainty.kind !== 'provided' || service.projection_type !== 'valuation' || !('base' in service.service_result)) {
            throw new Error('The retained base must contain a typed valuation with uncertainty.');
        }
        expect(report.identity.preparationDigest).toBe(originalPreparation);
        expect(report.base.perShare?.raw).toBe('229.88242539685962775556419207139754074672901162460');
        expect(report.base.perShare?.evidence.displayValue).toBe('USD 229.88 / share');
        const quantiles = report.uncertainty.quantiles;
        expect(quantiles.filter((item) => item.aliasOf === null).map((item) => [item.label, item.value.raw, item.evidence.displayValue])).toEqual([
            ['p05', '144.66504923006348207751523639707097017148015276713', 'USD 144.67 / share'],
            ['p50', '173.10058984916732564133256488227973785421478949288', 'USD 173.10 / share'],
            ['p95', '197.99983774116374973780751746974444493359658532582', 'USD 198.00 / share'],
        ]);
        expect(quantiles.filter((item) => item.aliasOf !== null).map((item) => [item.label, item.aliasOf])).toEqual([
            ['lower', 'p05'], ['median', 'p50'], ['upper', 'p95'],
        ]);
        expect(report.base.perShare?.coordinate).toBeGreaterThan(quantiles.find((item) => item.label === 'p95')?.value.coordinate ?? Infinity);
        const assumptions = report.preparationSummary?.assumptions ?? [];
        expect(assumptions.find((item) => item.path === 'assumptions.terminal_growth')?.evidence).toMatchObject({ value: '0.0492', displayValue: '4.92%' });
        expect(assumptions.find((item) => item.path === 'assumptions.wacc.beta')?.evidence).toMatchObject({ value: '1.27664817807817509986989534809254109859466552734375', displayValue: '1.28' });
        expect(assumptions.find((item) => item.path === 'assumptions.forecast.reinvestment_rate[0]')?.evidence).toMatchObject({ value: '0.40', displayValue: '40.00%' });
        expect(report.base.nodes.find((item) => item.id === 'wacc')?.evidence).toMatchObject({ value: '0.10280811227513954443826299464966391254835787654367', displayValue: '10.28%' });
        expect(report.facts).toHaveLength(84);
        expect(new Set(report.facts.map((fact) => fact.normalizedField)).size).toBe(20);
        const revenue = report.facts.find((fact) => fact.normalizedField === 'revenue' && fact.context.end === '2026-06-30');
        expect(revenue?.evidence).toMatchObject({ value: '331839000000', displayValue: 'USD 331.84B', scale: 6 });

        const forecasts = projectForecastSeries(report);
        for (const series of forecasts) {
            expect(series.points.map((point) => point.label)).toEqual(['Year 1', 'Year 2', 'Year 3', 'Year 4', 'Year 5']);
            for (const [index, point] of series.points.entries()) {
                const node = service.service_result.base.nodes.find((item) => item.node_id === `${series.id}_${index + 1}`);
                expect(node?.value).toBeTruthy();
                expect(point.value?.raw).toBe(node?.value);
                expect(point.evidence).toMatchObject({ inputDigest: report.base.binding.inputDigest, resultHash: report.base.binding.resultHash });
            }
        }
        const history = projectHistoricalSeries(report);
        expect(history.map((item) => item.kind)).toEqual(['comparable', 'comparable', 'comparable']);
        for (const item of history) {
            if (item.kind !== 'comparable') throw new Error('Expected comparable annual periods in the retained history.');
            const facts = service.facts.facts.filter((fact) => fact.normalized_field === item.series.id).sort((a, b) => a.period_end.localeCompare(b.period_end));
            expect(item.series.points.map((point) => [point.label, point.value?.raw, point.evidence?.factId])).toEqual(
                facts.map((fact) => [fact.period_end, fact.value, fact.fact_id]),
            );
        }
        expect(report.uncertainty.scenarios.map((scenario) => [scenario.binding, scenario.perShare?.raw])).toEqual(
            service.service_result.scenario_results.map((scenario) => [{ inputDigest: scenario.input_digest, resultHash: scenario.result_hash }, scenario.per_share_value]),
        );
        expect(report.uncertainty.scenarios).toHaveLength(3);
        expect(report.uncertainty.sensitivity).toEqual([]);
        expect(report.uncertainty.dominantDrivers).toEqual([]);
        expect(report.preparationSummary?.capitalCompleteness).toMatchObject({ kind: 'provided', completeClaims: false, completeAwards: false });
        const capital = report.preparationSummary?.capitalCompleteness;
        if (capital?.kind !== 'provided') throw new Error('The retained conditional capital policy is required.');
        expect(capital.unknowns).toContain('preferred_claims');
        expect(capital.limitations.length).toBeGreaterThan(0);
        const inventory = buildFundamentalEvidenceInventory(report);
        expect(new Set(inventory.items.map((item) => item.id)).size).toBe(inventory.items.length);
        expect(inventory.items.every((item) => item.threadId === source.fixture.threadId && item.runId === source.fixture.runId && item.artifactId === source.fixture.artifactId)).toBe(true);
        await recordRetained(info, 'retained-base-F01-F09', source, {
            cases: ['F01', 'F02', 'F03', 'F05', 'F06', 'F07', 'F08', 'F09'],
            base: report.base.perShare, quantiles, factCount: report.facts.length,
            forecast: forecasts, history, capital, evidenceCount: inventory.items.length,
        });
    });

    test('F04 synthetic formatter boundaries retain zero, nonzero values and unavailable meanings', () => {
        for (const [raw, expected] of [
            ['1.005', 'USD 1.01 / share'], ['-1.005', 'USD −1.01 / share'],
            ['0.000000004', 'USD 4.00e−9 / share'], ['-0.000000004', 'USD −4.00e−9 / share'],
            ['1e24', 'USD 1.00e+24 / share'], ['0', 'USD 0.00 / share'],
        ]) expect(formatReportNumber(raw, perShare)).toBe(expected);
        expect(formatReportDatum({ kind: 'unavailable', status: 'missing', reason: 'No filing.' })).toBe('Missing · No filing.');
        expect(formatReportDatum({ kind: 'unavailable', status: 'not_applicable', reason: 'No instrument.' })).toBe('Not applicable · No instrument.');
        expect(formatReportNumber('7532000000', { kind: 'shares' })).toBe('7.53B shares');
        expect(formatReportNumber('2026', { kind: 'year' })).toBe('FY2026');
        expect(formatReportNumber('1000000', { kind: 'count' })).toBe('1,000,000');
        expect(formatReportNumber('-0.0242', { kind: 'basis-points' })).toBe('−242.00 bps');
        expect(formatReportNumber('-0.0242', { kind: 'percentage-points' })).toBe('−2.42 percentage points');
    });

    test('F06–F07 synthetic changes to the parsed model leave gaps and withhold incompatible history', async () => {
        const { report } = await loadRetained('base');
        if (report.kind !== 'valuation') throw new Error('Expected retained valuation.');
        const missingNode = { ...report, base: { ...report.base, nodes: report.base.nodes.filter((item) => item.id !== 'revenue_3') } };
        expect(projectForecastSeries(missingNode).find((item) => item.id === 'revenue')?.points.map((point) => point.value === null)).toEqual([false, false, true, false, false]);
        const incompatibleHistory = {
            ...report,
            facts: report.facts.map((fact) => fact.normalizedField === 'revenue' && fact.context.end === '2026-06-30'
                ? { ...fact, dimensions: [{ name: 'SyntheticSegmentAxis', member: 'SyntheticSegmentMember' }] } : fact),
        };
        const revenue = projectHistoricalSeries(incompatibleHistory).find((item) => (item.kind === 'comparable' ? item.series.id : item.id) === 'revenue');
        expect(revenue?.kind).toBe('unavailable');
        if (revenue?.kind !== 'unavailable') throw new Error('Incompatible history must explain why its trend is withheld.');
        expect(revenue.reasons).toContain('Issuer, security, consolidation, currency, unit, period type, concept or dimensions differ.');
        expect(incompatibleHistory.facts).toHaveLength(84);
    });

    test('F13 retains the 168.92 revision and separates applied manual evidence from automatic origin', async ({}, info) => {
        const source = await loadRetained('revision');
        const { report } = source;
        if (report.kind !== 'valuation') throw new Error('Expected a retained revision valuation.');
        expect(report.identity.preparationDigest).toBe('99fdde441fdaf9183dbc1ad225066e45e4025662f3546c63e8c0312e28683d1b');
        expect(report.base.perShare?.raw).toBe('168.92316962973986376214271505310878928165576150584');
        expect(report.base.perShare?.evidence.displayValue).toBe('USD 168.92 / share');
        expect(report.preparationSummary?.isRevised).toBe(true);
        const terminal = report.preparationSummary?.assumptions.filter((item) => item.path === 'assumptions.terminal_growth');
        expect(terminal?.map((item) => [item.value.raw, item.revisionLabel, item.evidence.displayValue])).toEqual([
            ['0.0492', 'Original retained assumption', '4.92%'], ['0.025', 'Applied manual assumption', '2.50%'],
        ]);
        const applied = terminal?.find((item) => item.isManual);
        expect(applied?.originalPreparationDigest).toBe(originalPreparation);
        expect(applied?.evidence.originalPreparationDigest).toBe(originalPreparation);
        expect(applied?.evidence.rationale).toBeTruthy();
        const inventory = buildFundamentalEvidenceInventory(report);
        expect(inventory.items.every((item) => item.threadId === source.fixture.threadId && item.runId === source.fixture.runId && item.artifactId === source.fixture.artifactId && item.preparationDigest === report.identity.preparationDigest)).toBe(true);
        expect(new Set(terminal?.map((item) => item.evidence.id)).size).toBe(2);
        await recordRetained(info, 'retained-revision-F13', source, { base: report.base.perShare, terminal, evidenceCount: inventory.items.length });
    });

    test('F14 parses the retained refusal artifact as service-error with no successful valuation', async ({}, info) => {
        const source = await loadRetained('refusal');
        expect(source.service.projection_type).toBe('degraded');
        expect('service_result' in source.service).toBe(false);
        const { report } = source;
        if (report.kind !== 'service-error') throw new Error('Expected a typed service-error for the retained refusal.');
        expect(report.code).toBe('MANUAL_OVERRIDE_INVALID');
        expect(report.message).toContain('0.04');
        expect(report.message).toContain('0.05');
        expect(report.retryable).toBe(false);
        expect('base' in report).toBe(false);
        await recordRetained(info, 'retained-refusal-F14', source, { kind: report.kind, code: report.code, message: report.message, retryable: report.retryable, hasSuccessfulCalculation: 'base' in report });
    });
});
