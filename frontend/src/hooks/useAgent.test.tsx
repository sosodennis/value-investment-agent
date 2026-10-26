import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useAgent } from './useAgent';

const activity = (overrides: Record<string, unknown> = {}) => ({
    activity_id: 'analysis', thread_id: 'thread_1', run_id: 'run_1',
    scope_path: ['fundamental_analysis'], kind: 'phase', status: 'running',
    label: 'Fundamental analysis', attempt: 1, ...overrides,
});

const snapshot = (overrides: Record<string, unknown> = {}) => ({
    thread_id: 'thread_1', run_id: 'run_1', run_status: 'running', cursor: 1,
    active_activities: [activity()], recent_activities: [], pending_interactions: [], completed_outputs: [], ...overrides,
});

const streamResponse = (event: unknown) => {
    const body = new ReadableStream<Uint8Array>({
        start(controller) {
            controller.enqueue(new TextEncoder().encode(`event: workflow.activity\ndata: ${JSON.stringify(event)}\n\n`));
            controller.close();
        },
    });
    return new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } });
};

describe('useAgent workflow runtime', () => {
    const fetchMock = vi.fn();
    beforeEach(() => vi.stubGlobal('fetch', fetchMock));
    afterEach(() => { vi.unstubAllGlobals(); fetchMock.mockReset(); });

    it('hydrates a canonical snapshot and subscribes with its cursor', async () => {
        const terminalEvent = {
            event_id: 'evt_2', seq_id: 2, event_version: 'v2',
            event_name: 'workflow.activity', thread_id: 'thread_1', run_id: 'run_1',
            occurred_at: '2026-10-24T00:00:00Z',
            payload: activity({ activity_id: 'workflow', status: 'completed', label: 'Workflow completed' }),
        };
        fetchMock
            .mockResolvedValueOnce(new Response(JSON.stringify(snapshot()), { status: 200 }))
            .mockResolvedValueOnce(streamResponse(terminalEvent))
            .mockResolvedValueOnce(new Response(JSON.stringify(snapshot({
                cursor: 2,
                run_status: 'completed',
                active_activities: [],
                recent_activities: [activity({ status: 'completed' })],
            })), { status: 200 }));
        const { result } = renderHook(() => useAgent());
        await act(async () => result.current.loadHistory('thread_1', 'run_1'));
        await waitFor(() => expect(result.current.workflow?.runId).toBe('run_1'));
        expect(result.current.threadId).toBe('thread_1');
        expect(result.current.workflow?.runStatus).toBe('completed');
        expect(result.current.workflow?.recent[0]?.label).toBe('Fundamental analysis');
        expect(String(fetchMock.mock.calls[0]?.[0])).toContain('/api/v1/threads/thread_1/activities');
        expect(String(fetchMock.mock.calls[1]?.[0])).toContain('/api/v1/threads/thread_1/events?after_seq=1&run_id=run_1');
    });

    it('rejects a snapshot from another thread', async () => {
        fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(snapshot({ thread_id: 'other' })), { status: 200 }));
        const { result } = renderHook(() => useAgent());
        await act(async () => result.current.loadHistory('thread_1'));
        await waitFor(() => expect(result.current.error).toMatch(/activity identity mismatch/));
    });

    it('hydrates the run returned by start before subscribing', async () => {
        fetchMock
            .mockImplementationOnce((input: string) => {
                const threadId = input.match(/threads\/([^/]+)\/runs$/)?.[1];
                return Promise.resolve(new Response(JSON.stringify({ thread_id: threadId, run_id: 'started-run', status: 'started' }), { status: 202 }));
            })
            .mockImplementationOnce((input: string) => {
                const threadId = input.match(/threads\/([^/]+)\/activities/)?.[1];
                return Promise.resolve(new Response(JSON.stringify(snapshot({ thread_id: threadId, run_id: 'started-run', run_status: 'completed', active_activities: [] })), { status: 200 }));
            })
            .mockImplementationOnce((input: string) => {
                const threadId = input.match(/threads\/([^/]+)\/events/)?.[1];
                return Promise.resolve(streamResponse({
                    event_id: 'started-evt', seq_id: 1, event_version: 'v2', event_name: 'workflow.activity',
                    thread_id: threadId, run_id: 'started-run', occurred_at: '2026-10-24T00:00:00Z',
                    payload: activity({ activity_id: 'workflow', thread_id: threadId, run_id: 'started-run', status: 'completed' }),
                }));
            })
            .mockImplementationOnce((input: string) => {
                const threadId = input.match(/threads\/([^/]+)\/activities/)?.[1];
                return Promise.resolve(new Response(JSON.stringify(snapshot({ thread_id: threadId, run_id: 'started-run', run_status: 'completed', active_activities: [] })), { status: 200 }));
            });
        const { result } = renderHook(() => useAgent());

        await act(async () => result.current.sendMessage('Valuate AAPL', true));

        await waitFor(() => expect(result.current.workflow?.runId).toBe('started-run'));
        expect(String(fetchMock.mock.calls[1]?.[0])).toMatch(
            /\/api\/v1\/threads\/thread_[^/]+\/activities\?run_id=started-run$/,
        );
        expect(result.current.error).toBeNull();
    });

    it('requests and renders the exact older run from a history link', async () => {
        fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(snapshot({
            run_id: 'older-run',
            run_status: 'completed',
            active_activities: [],
            recent_activities: [],
        })), { status: 200 }));
        const { result } = renderHook(() => useAgent());
        await act(async () => result.current.loadHistory('thread_1', 'older-run'));

        await waitFor(() => expect(result.current.workflow?.runId).toBe('older-run'));
        expect(result.current.error).toBeNull();
        expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
            'http://localhost:8000/api/v1/threads/thread_1/activities?run_id=older-run'
        );
    });

    it('subscribes to and recovers only the requested historical run', async () => {
        const oldRunActivity = activity({ run_id: 'older-run' });
        const terminalEvent = {
            event_id: 'older-evt-2', seq_id: 2, event_version: 'v2',
            event_name: 'workflow.activity', thread_id: 'thread_1',
            run_id: 'older-run', occurred_at: '2026-10-24T00:00:00Z',
            payload: activity({ activity_id: 'workflow', run_id: 'older-run', status: 'completed', label: 'Completed' }),
        };
        fetchMock
            .mockResolvedValueOnce(new Response(JSON.stringify(snapshot({
                run_id: 'older-run', active_activities: [oldRunActivity],
            })), { status: 200 }))
            .mockResolvedValueOnce(streamResponse(terminalEvent))
            .mockResolvedValueOnce(new Response(JSON.stringify(snapshot({
                run_id: 'older-run', run_status: 'completed', cursor: 2,
                active_activities: [], recent_activities: [terminalEvent.payload],
            })), { status: 200 }));
        const { result } = renderHook(() => useAgent());

        await act(async () => result.current.loadHistory('thread_1', 'older-run'));

        await waitFor(() => expect(result.current.workflow?.runStatus).toBe('completed'));
        expect(result.current.workflow?.runId).toBe('older-run');
        expect(String(fetchMock.mock.calls[1]?.[0])).toBe(
            'http://localhost:8000/api/v1/threads/thread_1/events?after_seq=1&run_id=older-run'
        );
        expect(String(fetchMock.mock.calls[2]?.[0])).toBe(
            'http://localhost:8000/api/v1/threads/thread_1/activities?run_id=older-run'
        );
    });

    it('rejects a latest-run response when a link requests another run', async () => {
        fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(snapshot({ run_id: 'latest-run', active_activities: [], recent_activities: [] })), { status: 200 }));
        const { result } = renderHook(() => useAgent());
        await act(async () => result.current.loadHistory('thread_1', 'older-run'));
        await waitFor(() => expect(result.current.error).toMatch(/activity snapshot run identity mismatch/));
        expect(result.current.workflow).toBeNull();
        expect(result.current.threadId).toBeNull();
        expect(fetchMock).toHaveBeenCalledOnce();
        expect(String(fetchMock.mock.calls[0]?.[0])).toContain('?run_id=older-run');
    });

    it.each([404, 401])('surfaces an unavailable history response with HTTP %s', async (status) => {
        fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'History unavailable.' }), { status }));
        const { result } = renderHook(() => useAgent());
        await act(async () => result.current.loadHistory('thread_1', 'run_1'));
        await waitFor(() => expect(result.current.error).toContain('History unavailable.'));
        expect(result.current.workflow).toBeNull();
        expect(fetchMock).toHaveBeenCalledOnce();
    });

    it('applies terminal events and closes the connection', async () => {
        const terminal = { event_id: 'evt_2', seq_id: 2, event_version: 'v2', event_name: 'workflow.activity', thread_id: 'thread_1', run_id: 'run_1', occurred_at: '2026-10-24T00:00:00Z', payload: activity({ status: 'completed' }) };
        fetchMock
            .mockResolvedValueOnce(new Response(JSON.stringify(snapshot()), { status: 200 }))
            .mockResolvedValueOnce(streamResponse(terminal))
            .mockResolvedValueOnce(new Response(JSON.stringify(snapshot({ cursor: 2, run_status: 'completed', active_activities: [], recent_activities: [terminal.payload] })), { status: 200 }));
        const { result } = renderHook(() => useAgent());
        await act(async () => result.current.loadHistory('thread_1'));
        await waitFor(() => expect(result.current.workflow?.runStatus).toBe('completed'));
        expect(result.current.connectionState).toBe('closed');
        expect(result.current.workflow?.active.size).toBe(0);
    });
});
