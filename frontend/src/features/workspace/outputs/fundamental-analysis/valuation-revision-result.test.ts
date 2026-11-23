import { describe, expect, it } from 'vitest';
import type { StandardAgentOutput } from '@/types/agents';
import { parseFundamentalServiceArtifact } from '@/types/agents/fundamental-service-facts';
import { projectFundamentalReport, type FundamentalValuationModel } from './fundamental-report-model';
import { reference } from './fundamental-report.test-fixtures';
import { editableReport, revisedReport } from './valuation-revision.test-fixtures';
import { assessRevisionResult } from './valuation-revision-result';

function project(artifact: unknown, runId: string, artifactId: string): FundamentalValuationModel {
    const report = projectFundamentalReport({ artifact: parseFundamentalServiceArtifact(artifact), reference: { artifact_id: artifactId, download_url: `/api/v1/artifacts/${artifactId}?run_id=${runId}` }, threadId: 'thread-1', ticker: 'EXAMPLE' });
    if (report.kind !== 'valuation') throw new Error('Expected valuation.');
    return report;
}

describe('Revision result acceptance', () => {
    const previousReport = project(editableReport(), 'run-1', 'report-1');
    const previousOutput: StandardAgentOutput = { kind: 'fundamental_analysis.output', version: 'v1', summary: 'Original report.', reference };
    const attempt = {
        operationId: 'operation-1', previousReport, previousOutput,
        revision: { source: { thread_id: 'thread-1', run_id: 'run-1', artifact_id: 'report-1', preparation_digest: previousReport.identity.preparationDigest ?? '' }, path: 'assumptions.terminal_growth', value: '0.025', reason: 'Updated outlook.' },
    } satisfies Parameters<typeof assessRevisionResult>[0]['attempt'];

    it('accepts an exact applied manual value with the original preparation and a new source identity', () => {
        expect(assessRevisionResult({ attempt, candidate: project(revisedReport(), 'run-2', 'report-2'), expectedRunId: 'run-2' }).kind).toBe('accepted');
    });

    it.each([
        ['thread', (report) => ({ ...report, identity: { ...report.identity, threadId: 'other-thread' } })],
        ['run', (report) => ({ ...report, identity: { ...report.identity, runId: 'late-run' } })],
        ['artifact', (report) => ({ ...report, identity: { ...report.identity, artifactId: 'report-1' } })],
        ['issuer', (report) => ({ ...report, issuerId: 'other-issuer' })],
        ['share class', (report) => ({ ...report, shareClass: 'Class B' })],
        ['currency', (report) => ({ ...report, currency: 'EUR' })],
        ['snapshot', (report) => ({ ...report, snapshotDigest: 'f'.repeat(64) })],
        ['original preparation identity', (report) => ({ ...report, identity: { ...report.identity, preparationDigest: previousReport.identity.preparationDigest } })],
    ] satisfies [string, (report: FundamentalValuationModel) => FundamentalValuationModel][])('rejects an unrelated %s while preserving the original result', (_label, alter) => {
        const outcome = assessRevisionResult({ attempt, candidate: alter(project(revisedReport(), 'run-2', 'report-2')), expectedRunId: 'run-2' });
        expect(outcome.kind).toBe('failed');
        expect(attempt.previousReport.base.perShare?.raw).toBe('25.1234567890123456789');
    });
});
