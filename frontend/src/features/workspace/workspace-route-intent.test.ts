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

    it('reopens standalone annual statements by exact saved identity', () => {
        expect(parseWorkspaceRouteIntent(new URLSearchParams('statement_thread=thread-1&statement_artifact=artifact-1'))).toEqual({ kind: 'statement-report', threadId: 'thread-1', artifactId: 'artifact-1', frequency: 'annual', periodId: null });
        expect(parseWorkspaceRouteIntent(new URLSearchParams('statement_thread=thread-1'))).toEqual({ kind: 'invalid-history' });
    });

    it('retains fiscal frequency and opaque returned period identity while rejecting ambiguous links', () => {
        expect(parseWorkspaceRouteIntent(new URLSearchParams('statement_thread=thread-1&statement_artifact=artifact-1&statement_frequency=ttm&statement_period=fiscal-ttm-v1%3Aabc'))).toEqual({ kind: 'statement-report', threadId: 'thread-1', artifactId: 'artifact-1', frequency: 'ttm', periodId: 'fiscal-ttm-v1:abc' });
        for (const suffix of ['statement_frequency=monthly', 'statement_frequency=ttm&statement_frequency=quarter', 'statement_period=a&statement_period=b']) {
            expect(parseWorkspaceRouteIntent(new URLSearchParams(`statement_thread=thread-1&statement_artifact=artifact-1&${suffix}`))).toEqual({ kind: 'invalid-history' });
        }
    });

    it('rejects ambiguous duplicate history identifiers', () => {
        expect(parseWorkspaceRouteIntent(new URLSearchParams('thread_id=thread-1&thread_id=thread-2&run_id=run-1'))).toEqual({
            kind: 'invalid-history',
        });
    });
});
