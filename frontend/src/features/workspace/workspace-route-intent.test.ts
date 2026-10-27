import { describe, expect, it } from 'vitest';
import { parseWorkspaceRouteIntent } from './workspace-route-intent';

describe('parseWorkspaceRouteIntent', () => {
    it('keeps a route without history identifiers in new-analysis mode', () => {
        expect(parseWorkspaceRouteIntent(new URLSearchParams('ticker=AAPL'))).toEqual({ kind: 'new-analysis' });
    });

    it('requires one non-empty thread and run identifier for history mode', () => {
        expect(parseWorkspaceRouteIntent(new URLSearchParams('thread_id=thread%201&run_id=run%2F2'))).toEqual({
            kind: 'exact-run',
            threadId: 'thread 1',
            runId: 'run/2',
        });
        expect(parseWorkspaceRouteIntent(new URLSearchParams('thread_id=thread-1'))).toEqual({ kind: 'invalid-history' });
        expect(parseWorkspaceRouteIntent(new URLSearchParams('run_id=run-1'))).toEqual({ kind: 'invalid-history' });
        expect(parseWorkspaceRouteIntent(new URLSearchParams('thread_id=&run_id=run-1'))).toEqual({ kind: 'invalid-history' });
    });

    it('rejects ambiguous duplicate history identifiers', () => {
        expect(parseWorkspaceRouteIntent(new URLSearchParams('thread_id=thread-1&thread_id=thread-2&run_id=run-1'))).toEqual({
            kind: 'invalid-history',
        });
    });
});
