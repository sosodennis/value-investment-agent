import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useAgent } from './useAgent';

function deferred<T>() {
    let resolve!: (value: T | PromiseLike<T>) => void;
    let reject!: (reason?: unknown) => void;
    const promise = new Promise<T>((onResolve, onReject) => {
        resolve = onResolve;
        reject = onReject;
    });
    return { promise, resolve, reject };
}

function snapshotResponse(threadId: string, runId: string, runStatus = 'completed') {
    return new Response(JSON.stringify({
        thread_id: threadId,
        run_id: runId,
        run_status: runStatus,
        cursor: 1,
        active_activities: [],
        recent_activities: [],
        pending_interactions: [],
        completed_outputs: [],
    }), { status: 200 });
}

function startResponse(threadId: string, runId: string) {
    return new Response(JSON.stringify({ thread_id: threadId, run_id: runId, status: 'started' }), { status: 202 });
}

describe('useAgent operation identity', () => {
    const fetchMock = vi.fn<typeof fetch>();
    beforeEach(() => vi.stubGlobal('fetch', fetchMock));
    afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); fetchMock.mockReset(); });

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
        let previousStart: Promise<void>;
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
        let previousStart: Promise<void>;
        act(() => { previousStart = result.current.sendMessage('First'); });
        await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
        act(() => { void result.current.sendMessage('Second'); });
        await act(async () => {
            previousSnapshot.resolve(snapshotResponse('thread-1', 'previous-run'));
            await previousStart;
        });

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
