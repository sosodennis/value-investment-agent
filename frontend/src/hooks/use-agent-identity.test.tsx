import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { components } from '@/types/generated/api-contract';
import { useAgent, type WorkflowStartResult } from './useAgent';

function deferred<T>() {
    let resolve!: (value: T | PromiseLike<T>) => void;
    let reject!: (reason?: unknown) => void;
    const promise = new Promise<T>((onResolve, onReject) => {
        resolve = onResolve;
        reject = onReject;
    });
    return { promise, resolve, reject };
}

function snapshotResponse(
    threadId: string,
    runId: string,
    runStatus = 'completed',
    extras: Partial<Pick<components['schemas']['WorkflowSnapshot'], 'pending_interactions' | 'completed_outputs'>> = {},
) {
    return new Response(JSON.stringify({
        thread_id: threadId,
        run_id: runId,
        run_status: runStatus,
        cursor: 1,
        active_activities: [],
        recent_activities: [],
        pending_interactions: [],
        completed_outputs: [],
        ...extras,
    }), { status: 200 });
}

function startResponse(threadId: string, runId: string) {
    return new Response(JSON.stringify({ thread_id: threadId, run_id: runId, status: 'started' }), { status: 202 });
}

function pendingStreamResponse(signal?: AbortSignal | null) {
    return new Response(new ReadableStream<Uint8Array>({
        start(controller) {
            signal?.addEventListener('abort', () => {
                controller.error(new DOMException('Aborted', 'AbortError'));
            }, { once: true });
        },
    }), { headers: { 'Content-Type': 'text/event-stream' } });
}

describe('useAgent operation identity', () => {
    const fetchMock = vi.fn<typeof fetch>();
    beforeEach(() => vi.stubGlobal('fetch', fetchMock));
    afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); fetchMock.mockReset(); });

    it('returns the accepted run identity while its stream remains pending', async () => {
        fetchMock.mockResolvedValueOnce(snapshotResponse('thread-1', 'initial-run'))
            .mockResolvedValueOnce(startResponse('thread-1', 'started-run'))
            .mockResolvedValueOnce(snapshotResponse('thread-1', 'started-run', 'running'))
            .mockImplementationOnce(async (_input, init) => pendingStreamResponse(init?.signal));
        const { result, unmount } = renderHook(() => useAgent());
        await act(async () => result.current.loadHistory('thread-1', 'initial-run'));
        let outcome: WorkflowStartResult | undefined;
        act(() => {
            void result.current.sendMessage('Valuate AAPL').then((value) => { outcome = value; });
        });

        await waitFor(() => expect(result.current.connectionState).toBe('connected'));
        await waitFor(() => expect(outcome).toEqual({ kind: 'started', threadId: 'thread-1', runId: 'started-run' }));
        expect(result.current.workflow?.runStatus).toBe('running');
        expect(result.current.isLoading).toBe(false);
        expect(fetchMock.mock.calls[3]?.[1]?.signal?.aborted).toBe(false);
        unmount();
    });

    it('keeps an accepted start successful when its pending interaction resumes the same run', async () => {
        const interaction = {
            identity: { thread_id: 'thread-1', run_id: 'started-run', activity_id: 'intent.clarifying', interaction_id: 'interaction-1' },
            kind: 'ticker_selection', status: 'pending',
            request: { type: 'ticker_selection', title: 'Choose a company', description: 'Select the intended company.', candidates: [{ symbol: 'AAPL', name: 'Apple Inc.', confidence: 0.99 }] },
        } satisfies components['schemas']['WorkflowInteraction'];
        fetchMock.mockResolvedValueOnce(snapshotResponse('thread-1', 'initial-run'))
            .mockResolvedValueOnce(startResponse('thread-1', 'started-run'))
            .mockResolvedValueOnce(snapshotResponse('thread-1', 'started-run', 'waiting', { pending_interactions: [interaction] }))
            .mockImplementationOnce(async (_input, init) => pendingStreamResponse(init?.signal))
            .mockResolvedValueOnce(startResponse('thread-1', 'started-run'))
            .mockResolvedValueOnce(snapshotResponse('thread-1', 'started-run', 'completed', { completed_outputs: [{
                identity: { thread_id: 'thread-1', run_id: 'started-run', activity_id: 'fundamental' },
                agent_id: 'fundamental_analysis', output_kind: 'fundamental_analysis.output', output_version: 'v1',
                summary: 'Recalculated AAPL report', preview: {}, artifact_id: 'revised-report', artifact_type: 'financial_reports',
            }] }))
            .mockImplementationOnce(async (_input, init) => pendingStreamResponse(init?.signal));
        const { result, unmount } = renderHook(() => useAgent());
        await act(async () => result.current.loadHistory('thread-1', 'initial-run'));
        let outcome: WorkflowStartResult | undefined;
        act(() => {
            void result.current.sendMessage('Recalculate AAPL').then((value) => { outcome = value; });
        });
        await waitFor(() => expect(result.current.connectionState).toBe('connected'));
        const pending = [...(result.current.workflow?.interactions.values() ?? [])][0];
        if (!pending) throw new Error('Pending ticker interaction did not parse.');
        act(() => { void result.current.submitCommand(pending, { type: 'ticker_selection', selected_symbol: 'AAPL' }); });

        await waitFor(() => expect(result.current.agentOutputs.fundamental_analysis?.reference?.artifact_id).toBe('revised-report'));
        await waitFor(() => expect(outcome).toEqual({ kind: 'started', threadId: 'thread-1', runId: 'started-run' }));
        expect(result.current.runId).toBe('started-run');
        expect(result.current.workflow?.runStatus).toBe('completed');
        expect(result.current.error).toBeNull();
        expect(fetchMock.mock.calls[4]?.[0]).toBe('/api/v1/threads/thread-1/runs/started-run/resume');
        expect(JSON.parse(String(fetchMock.mock.calls[4]?.[1]?.body))).toEqual({
            identity: interaction.identity,
            response: { type: 'ticker_selection', selected_symbol: 'AAPL' },
        });
        expect(fetchMock.mock.calls[3]?.[1]?.signal?.aborted).toBe(true);
        unmount();
    });

    it('reports a stream recovery failure separately from its accepted start', async () => {
        fetchMock.mockResolvedValueOnce(snapshotResponse('thread-1', 'initial-run'))
            .mockResolvedValueOnce(startResponse('thread-1', 'started-run'))
            .mockResolvedValueOnce(snapshotResponse('thread-1', 'started-run', 'running'))
            .mockRejectedValueOnce(new Error('Stream disconnected.'))
            .mockRejectedValueOnce(new Error('Snapshot recovery failed.'));
        const { result } = renderHook(() => useAgent());
        await act(async () => result.current.loadHistory('thread-1', 'initial-run'));
        let outcome: WorkflowStartResult | undefined;
        await act(async () => { outcome = await result.current.sendMessage('Valuate AAPL'); });

        await waitFor(() => expect(result.current.error).toBe('Snapshot recovery failed.'));
        expect(outcome).toEqual({ kind: 'started', threadId: 'thread-1', runId: 'started-run' });
        expect(result.current.workflow?.runId).toBe('started-run');
        expect(result.current.connectionState).toBe('closed');
        expect(result.current.isLoading).toBe(false);
    });

    it('ignores a background recovery failure after selecting another run', async () => {
        const recovery = deferred<Response>();
        fetchMock.mockResolvedValueOnce(snapshotResponse('thread-1', 'initial-run'))
            .mockResolvedValueOnce(startResponse('thread-1', 'started-run'))
            .mockResolvedValueOnce(snapshotResponse('thread-1', 'started-run', 'running'))
            .mockRejectedValueOnce(new Error('Stream disconnected.'))
            .mockReturnValueOnce(recovery.promise)
            .mockResolvedValueOnce(snapshotResponse('thread-1', 'selected-run'));
        const { result } = renderHook(() => useAgent());
        await act(async () => result.current.loadHistory('thread-1', 'initial-run'));
        let outcome: WorkflowStartResult | undefined;
        act(() => { void result.current.sendMessage('Valuate AAPL').then((value) => { outcome = value; }); });
        await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(5));
        await act(async () => result.current.loadHistory('thread-1', 'selected-run'));
        await act(async () => { recovery.reject(new Error('Obsolete snapshot recovery failed.')); });

        expect(outcome).toEqual({ kind: 'started', threadId: 'thread-1', runId: 'started-run' });
        expect(result.current.workflow?.runId).toBe('selected-run');
        expect(result.current.error).toBeNull();
        expect(result.current.connectionState).toBe('disconnected');
        expect(result.current.isLoading).toBe(false);
    });

    it('ignores an obsolete history snapshot while the selected history is still loading', async () => {
        const previous = deferred<Response>();
        const selected = deferred<Response>();
        fetchMock.mockReturnValueOnce(previous.promise).mockReturnValueOnce(selected.promise);
        const { result } = renderHook(() => useAgent());
        let previousLoad: Promise<void>;
        act(() => { previousLoad = result.current.loadHistory('previous-thread', 'previous-run'); });
        act(() => { void result.current.loadHistory('selected-thread', 'selected-run'); });

        await act(async () => {
            previous.resolve(snapshotResponse('previous-thread', 'previous-run'));
            await previousLoad;
        });

        expect(result.current.workflow).toBeNull();
        expect(result.current.isLoading).toBe(true);
        expect(fetchMock.mock.calls[0]?.[1]?.signal?.aborted).toBe(true);

        await act(async () => { selected.resolve(snapshotResponse('selected-thread', 'selected-run')); });
        await waitFor(() => expect(result.current.runId).toBe('selected-run'));
        expect(result.current.threadId).toBe('selected-thread');
        expect(result.current.isLoading).toBe(false);
    });

    it('ignores a late start acknowledgement after selecting a historical run', async () => {
        const started = deferred<Response>();
        fetchMock.mockReturnValueOnce(started.promise)
            .mockResolvedValueOnce(snapshotResponse('selected-thread', 'selected-run'));
        const { result } = renderHook(() => useAgent());
        let previousStart: Promise<unknown>;
        act(() => { previousStart = result.current.sendMessage('Valuate AAPL', true); });
        const requestUrl = String(fetchMock.mock.calls[0]?.[0]);
        const previousThreadId = requestUrl.split('/')[4];
        await act(async () => result.current.loadHistory('selected-thread', 'selected-run'));
        await act(async () => {
            started.resolve(startResponse(previousThreadId, 'previous-run'));
            await previousStart;
        });

        expect(result.current.threadId).toBe('selected-thread');
        expect(result.current.runId).toBe('selected-run');
        expect(result.current.workflow?.runId).toBe('selected-run');
        expect(result.current.error).toBeNull();
        expect(fetchMock).toHaveBeenCalledTimes(2);
        expect(fetchMock.mock.calls[0]?.[1]?.signal?.aborted).toBe(true);
    });

    it('ignores a late start snapshot before the next start acknowledgement arrives', async () => {
        const previousSnapshot = deferred<Response>();
        const nextStart = deferred<Response>();
        fetchMock
            .mockResolvedValueOnce(snapshotResponse('thread-1', 'initial-run'))
            .mockResolvedValueOnce(startResponse('thread-1', 'previous-run'))
            .mockReturnValueOnce(previousSnapshot.promise)
            .mockReturnValueOnce(nextStart.promise)
            .mockResolvedValueOnce(snapshotResponse('thread-1', 'next-run'));
        const { result, unmount } = renderHook(() => useAgent());
        await act(async () => result.current.loadHistory('thread-1', 'initial-run'));
        let previousStart: Promise<WorkflowStartResult>;
        let previousOutcome: WorkflowStartResult | undefined;
        act(() => { previousStart = result.current.sendMessage('First'); });
        await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
        act(() => { void result.current.sendMessage('Second'); });
        await act(async () => {
            previousSnapshot.resolve(snapshotResponse('thread-1', 'previous-run'));
            previousOutcome = await previousStart;
        });

        expect(previousOutcome).toEqual({ kind: 'superseded' });
        expect(result.current.workflow?.runId).toBe('initial-run');
        expect(result.current.isLoading).toBe(true);
        expect(fetchMock).toHaveBeenCalledTimes(4);
        expect(fetchMock.mock.calls[2]?.[1]?.signal?.aborted).toBe(true);
        unmount();
        await act(async () => { nextStart.resolve(startResponse('thread-1', 'next-run')); });
        expect(fetchMock).toHaveBeenCalledTimes(4);
    });

    it('starts distinct sessions even when two starts are admitted in the same millisecond', async () => {
        vi.spyOn(Date, 'now').mockReturnValue(12345);
        const first = deferred<Response>();
        const second = deferred<Response>();
        fetchMock.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
        const { result, unmount } = renderHook(() => useAgent());
        act(() => {
            void result.current.sendMessage('First', true);
            void result.current.sendMessage('Second', true);
        });

        expect(fetchMock.mock.calls[0]?.[0]).not.toBe(fetchMock.mock.calls[1]?.[0]);
        expect(fetchMock.mock.calls[0]?.[1]?.signal?.aborted).toBe(true);
        unmount();
        await act(async () => {
            first.resolve(startResponse(String(fetchMock.mock.calls[0]?.[0]).split('/')[4], 'first-run'));
            second.resolve(startResponse(String(fetchMock.mock.calls[1]?.[0]).split('/')[4], 'second-run'));
        });
        expect(fetchMock).toHaveBeenCalledTimes(2);
    });

    it('aborts the active stream before awaiting a new start and rejects buffered old events', async () => {
        const body = deferred<ReadableStreamDefaultController<Uint8Array>>();
        const response = new Response(new ReadableStream<Uint8Array>({ start: body.resolve }), {
            headers: { 'Content-Type': 'text/event-stream' },
        });
        const started = deferred<Response>();
        fetchMock.mockResolvedValueOnce(snapshotResponse('thread-1', 'previous-run', 'running'))
            .mockResolvedValueOnce(response).mockReturnValueOnce(started.promise);
        const { result, unmount } = renderHook(() => useAgent());
        let previousLoad: Promise<void>;
        act(() => { previousLoad = result.current.loadHistory('thread-1', 'previous-run'); });
        await waitFor(() => expect(result.current.connectionState).toBe('connected'));
        act(() => { void result.current.sendMessage('Next'); });
        expect(fetchMock.mock.calls[1]?.[1]?.signal?.aborted).toBe(true);
        expect(result.current.connectionState).toBe('disconnected');

        await act(async () => {
            const controller = await body.promise;
            controller.enqueue(new TextEncoder().encode(`event: workflow.activity\ndata: ${JSON.stringify({
                event_id: 'obsolete-event', seq_id: 2, event_version: 'v2', event_name: 'workflow.activity',
                thread_id: 'thread-1', run_id: 'previous-run', occurred_at: '2026-11-23T00:00:00Z',
                payload: {
                    activity_id: 'workflow', thread_id: 'thread-1', run_id: 'previous-run',
                    scope_path: [], kind: 'phase', status: 'completed', label: 'Old completion', attempt: 1,
                },
            })}\n\n`));
            await previousLoad;
        });

        expect(result.current.workflow?.runStatus).toBe('running');
        expect(result.current.workflow?.cursor).toBe(1);
        expect(result.current.isLoading).toBe(true);
        expect(result.current.connectionState).toBe('disconnected');
        unmount();
        await act(async () => { started.resolve(startResponse('thread-1', 'next-run')); });
        expect(fetchMock).toHaveBeenCalledTimes(3);
    });

    it('keeps a selected history loading when an obsolete history request fails', async () => {
        const previous = deferred<Response>();
        const selected = deferred<Response>();
        fetchMock.mockReturnValueOnce(previous.promise).mockReturnValueOnce(selected.promise);
        const { result } = renderHook(() => useAgent());
        act(() => { void result.current.loadHistory('previous-thread', 'previous-run'); });
        act(() => { void result.current.loadHistory('selected-thread', 'selected-run'); });
        await act(async () => { previous.reject(new Error('Obsolete request failed.')); });

        expect(result.current.isLoading).toBe(true);
        expect(result.current.error).toBeNull();
        await act(async () => { selected.resolve(snapshotResponse('selected-thread', 'selected-run')); });
        await waitFor(() => expect(result.current.runId).toBe('selected-run'));
    });

    it('aborts the previous stream as soon as another history request is admitted', async () => {
        const stream = deferred<Response>();
        const selected = deferred<Response>();
        fetchMock.mockResolvedValueOnce(snapshotResponse('thread-1', 'previous-run', 'running'))
            .mockReturnValueOnce(stream.promise).mockReturnValueOnce(selected.promise);
        const { result } = renderHook(() => useAgent());
        let previousLoad: Promise<void>;
        act(() => { previousLoad = result.current.loadHistory('thread-1', 'previous-run'); });
        await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
        act(() => { void result.current.loadHistory('thread-1', 'selected-run'); });
        expect(fetchMock.mock.calls[1]?.[1]?.signal?.aborted).toBe(true);

        await act(async () => {
            stream.resolve(new Response(new ReadableStream({ start(controller) { controller.close(); } }), {
                status: 200, headers: { 'Content-Type': 'text/event-stream' },
            }));
            await previousLoad;
        });
        expect(result.current.connectionState).toBe('disconnected');
        expect(result.current.isLoading).toBe(true);

        await act(async () => { selected.resolve(snapshotResponse('thread-1', 'selected-run')); });
        await waitFor(() => expect(result.current.runId).toBe('selected-run'));
    });

    it('ignores a stale stream recovery snapshot after changing runs', async () => {
        const recovery = deferred<Response>();
        fetchMock.mockResolvedValueOnce(snapshotResponse('thread-1', 'previous-run', 'running'))
            .mockResolvedValueOnce(new Response('', { headers: { 'Content-Type': 'text/event-stream' } }))
            .mockReturnValueOnce(recovery.promise)
            .mockResolvedValueOnce(snapshotResponse('thread-1', 'selected-run'));
        const { result } = renderHook(() => useAgent());
        let previousLoad: Promise<void>;
        act(() => { previousLoad = result.current.loadHistory('thread-1', 'previous-run'); });
        await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
        await act(async () => result.current.loadHistory('thread-1', 'selected-run'));
        await act(async () => {
            recovery.resolve(snapshotResponse('thread-1', 'previous-run'));
            await previousLoad;
        });

        expect(result.current.workflow?.runId).toBe('selected-run');
        expect(result.current.connectionState).toBe('disconnected');
        expect(result.current.error).toBeNull();
        expect(fetchMock).toHaveBeenCalledTimes(4);
    });

    it('does not hydrate a cancellation response into a newly selected run', async () => {
        const cancellation = deferred<Response>();
        fetchMock.mockResolvedValueOnce(snapshotResponse('thread-1', 'previous-run'))
            .mockReturnValueOnce(cancellation.promise)
            .mockResolvedValueOnce(snapshotResponse('thread-1', 'selected-run'));
        const { result } = renderHook(() => useAgent());
        await act(async () => result.current.loadHistory('thread-1', 'previous-run'));
        let cancelled: Promise<void>;
        act(() => { cancelled = result.current.cancelRun(); });
        await act(async () => result.current.loadHistory('thread-1', 'selected-run'));
        await act(async () => { cancellation.resolve(new Response(null, { status: 202 })); await cancelled; });

        expect(result.current.workflow?.runId).toBe('selected-run');
        expect(result.current.connectionState).toBe('disconnected');
        expect(result.current.error).toBeNull();
        expect(fetchMock).toHaveBeenCalledTimes(3);
    });

    it.each(['history', 'start'])('aborts an in-flight %s request on unmount without starting follow-up work', async (operation) => {
        const pending = deferred<Response>();
        fetchMock.mockReturnValueOnce(pending.promise);
        const { result, unmount } = renderHook(() => useAgent());
        act(() => {
            if (operation === 'history') void result.current.loadHistory('thread-1', 'run-1');
            else void result.current.sendMessage('Valuate AAPL', true);
        });
        const threadId = String(fetchMock.mock.calls[0]?.[0]).split('/')[4];
        unmount();
        expect(fetchMock.mock.calls[0]?.[1]?.signal?.aborted).toBe(true);
        await act(async () => {
            pending.resolve(operation === 'history' ? snapshotResponse(threadId, 'run-1') : startResponse(threadId, 'run-1'));
        });
        expect(fetchMock).toHaveBeenCalledOnce();
    });
});
