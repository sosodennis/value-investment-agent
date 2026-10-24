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
    active_activities: [activity()], recent_activities: [], ...overrides,
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
        fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(snapshot()), { status: 200 }));
        fetchMock.mockResolvedValueOnce(new Response(null, { status: 200, headers: { 'Content-Type': 'text/event-stream' } }));
        const { result } = renderHook(() => useAgent());
        await act(async () => result.current.loadHistory('thread_1'));
        await waitFor(() => expect(result.current.workflow?.runId).toBe('run_1'));
        expect(result.current.threadId).toBe('thread_1');
        expect(result.current.workflow?.active.get('analysis')?.label).toBe('Fundamental analysis');
        expect(String(fetchMock.mock.calls[0]?.[0])).toContain('/api/v1/threads/thread_1/activities');
        expect(String(fetchMock.mock.calls[1]?.[0])).toContain('/api/v1/threads/thread_1/events?after_seq=1');
    });

    it('rejects a snapshot from another thread', async () => {
        fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(snapshot({ thread_id: 'other' })), { status: 200 }));
        const { result } = renderHook(() => useAgent());
        await act(async () => result.current.loadHistory('thread_1'));
        await waitFor(() => expect(result.current.error).toMatch(/activity identity mismatch/));
    });

    it('applies terminal events and closes the connection', async () => {
        const terminal = { event_id: 'evt_2', seq_id: 2, event_version: 'v1', event_name: 'workflow.activity', thread_id: 'thread_1', run_id: 'run_1', occurred_at: '2026-10-24T00:00:00Z', payload: activity({ status: 'completed' }) };
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
