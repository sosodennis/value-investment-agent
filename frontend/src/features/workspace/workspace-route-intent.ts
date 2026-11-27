export type WorkspaceRouteIntent =
    | { kind: 'new-analysis' }
    | { kind: 'exact-run'; threadId: string; runId: string }
    | { kind: 'statement-report'; threadId: string; artifactId: string; frequency: 'annual' | 'quarter' | 'ttm'; periodId: string | null }
    | { kind: 'invalid-history' };

export function parseWorkspaceRouteIntent(searchParams: Pick<URLSearchParams, 'getAll'>): WorkspaceRouteIntent {
    const threadIds = searchParams.getAll('thread_id');
    const runIds = searchParams.getAll('run_id');

    if (threadIds.length === 0 && runIds.length === 0) {
        const statementThreads = searchParams.getAll('statement_thread');
        const statementArtifacts = searchParams.getAll('statement_artifact');
        const frequencies = searchParams.getAll('statement_frequency');
        const periods = searchParams.getAll('statement_period');
        const frequency = frequencies[0] ?? 'annual';
        if (frequencies.length > 1 || periods.length > 1 || !['annual', 'quarter', 'ttm'].includes(frequency)) return { kind: 'invalid-history' };
        if (statementThreads.length === 1 && statementArtifacts.length === 1 && statementThreads[0]?.trim() && statementArtifacts[0]?.trim()) {
            if (frequency !== 'annual' && frequency !== 'quarter' && frequency !== 'ttm') return { kind: 'invalid-history' };
            return { kind: 'statement-report', threadId: statementThreads[0], artifactId: statementArtifacts[0], frequency, periodId: periods[0] ?? null };
        }
        if (statementThreads.length || statementArtifacts.length || frequencies.length || periods.length) return { kind: 'invalid-history' };
        return { kind: 'new-analysis' };
    }
    if (threadIds.length !== 1 || runIds.length !== 1) return { kind: 'invalid-history' };

    const [threadId] = threadIds;
    const [runId] = runIds;
    if (!threadId?.trim() || !runId?.trim()) return { kind: 'invalid-history' };

    return { kind: 'exact-run', threadId, runId };
}
