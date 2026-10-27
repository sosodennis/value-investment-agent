export type WorkspaceRouteIntent =
    | { kind: 'new-analysis' }
    | { kind: 'exact-run'; threadId: string; runId: string }
    | { kind: 'invalid-history' };

export function parseWorkspaceRouteIntent(searchParams: Pick<URLSearchParams, 'getAll'>): WorkspaceRouteIntent {
    const threadIds = searchParams.getAll('thread_id');
    const runIds = searchParams.getAll('run_id');

    if (threadIds.length === 0 && runIds.length === 0) return { kind: 'new-analysis' };
    if (threadIds.length !== 1 || runIds.length !== 1) return { kind: 'invalid-history' };

    const [threadId] = threadIds;
    const [runId] = runIds;
    if (!threadId?.trim() || !runId?.trim()) return { kind: 'invalid-history' };

    return { kind: 'exact-run', threadId, runId };
}
