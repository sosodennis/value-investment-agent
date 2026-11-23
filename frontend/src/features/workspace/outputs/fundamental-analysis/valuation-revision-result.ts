import type { StandardAgentOutput } from '@/types/agents';
import type { FundamentalReportModel, FundamentalValuationModel } from './fundamental-report-model';
import type { FundamentalRevision } from './valuation-revision';

type RetainedSource = {
    operationId: string;
    revision: FundamentalRevision;
    previousOutput: StandardAgentOutput;
    previousReport: FundamentalValuationModel;
};
export type RetainedRevisionAttempt = RetainedSource & (
    | { kind: 'starting' }
    | { kind: 'awaiting-result'; expectedRunId: string }
    | { kind: 'failed'; code: string; message: string }
    | { kind: 'accepted'; currentOutput: StandardAgentOutput; currentReport: FundamentalValuationModel }
);
type AttemptEvent =
    | { type: 'started'; attempt: Extract<RetainedRevisionAttempt, { kind: 'starting' }> }
    | { type: 'cleared' }
    | { type: 'run-started'; operationId: string; expectedRunId: string }
    | { type: 'failed'; operationId: string; code: string; message: string }
    | { type: 'accepted'; operationId: string; currentOutput: StandardAgentOutput; currentReport: FundamentalValuationModel };

export function revisionAttemptReducer(state: RetainedRevisionAttempt | null, event: AttemptEvent): RetainedRevisionAttempt | null {
    if (event.type === 'cleared') return null;
    if (event.type === 'started') return event.attempt;
    if (!state || state.operationId !== event.operationId || state.kind === 'accepted' || state.kind === 'failed') return state;
    switch (event.type) {
        case 'run-started': return state.kind === 'starting' ? { ...state, kind: 'awaiting-result', expectedRunId: event.expectedRunId } : state;
        case 'failed': return { ...state, kind: 'failed', code: event.code, message: event.message };
        case 'accepted': return state.kind === 'awaiting-result' ? { ...state, kind: 'accepted', currentOutput: event.currentOutput, currentReport: event.currentReport } : state;
        default: { const exhaustive: never = event; return exhaustive; }
    }
}

export function assessRevisionResult({ attempt, candidate, expectedRunId }: {
    attempt: RetainedSource;
    candidate: FundamentalReportModel;
    expectedRunId: string;
}): { kind: 'accepted'; report: FundamentalValuationModel } | { kind: 'failed'; code: string; message: string } {
    const { source } = attempt.revision;
    if (candidate.identity.threadId !== source.thread_id || candidate.identity.runId !== expectedRunId || expectedRunId === source.run_id || !candidate.identity.artifactId || candidate.identity.artifactId === source.artifact_id)
        return { kind: 'failed', code: 'REVISION_SOURCE_MISMATCH', message: 'The returned report does not belong to the requested new run and artifact.' };
    if (candidate.kind === 'service-error') return { kind: 'failed', code: candidate.code, message: candidate.message };
    if (candidate.kind === 'preparation-outcome') return { kind: 'failed', code: candidate.outcome, message: candidate.reason ?? 'The service did not produce a revised valuation.' };
    if (candidate.kind !== 'valuation') return { kind: 'failed', code: 'REVISION_RESULT_UNCONFIRMED', message: 'The new run supplied no confirmed valuation.' };
    const previous = attempt.previousReport;
    const applied = candidate.preparationSummary?.assumptions.filter((item) => item.path === attempt.revision.path && item.isManual);
    if (candidate.issuerId !== previous.issuerId || candidate.ticker !== previous.ticker || candidate.shareClass !== previous.shareClass || candidate.currency !== previous.currency || candidate.snapshotDigest !== previous.snapshotDigest || candidate.base.status !== 'completed' || candidate.identity.preparationDigest === source.preparation_digest || applied?.length !== 1 || applied[0]?.originalPreparationDigest !== source.preparation_digest || applied[0]?.value.raw !== attempt.revision.value || applied[0]?.revisionLabel !== 'Applied manual assumption')
        return { kind: 'failed', code: 'REVISION_RESULT_UNCONFIRMED', message: 'The returned valuation does not confirm this issuer, retained source and exact manual assumption.' };
    return { kind: 'accepted', report: candidate };
}
