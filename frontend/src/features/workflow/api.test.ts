import { afterEach, describe, expect, it, vi } from 'vitest';
import { consumeWorkflowEvents, getActivitySnapshot } from './api';

describe('workflow API', () => {
    afterEach(() => vi.unstubAllGlobals());

    it('requests and validates an exact activity run when one is supplied', async () => {
        const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
            thread_id: 'thread/1',
            run_id: 'run/2',
            run_status: 'completed',
            cursor: 0,
            active_activities: [],
            recent_activities: [],
            pending_interactions: [],
            completed_outputs: [],
        }), { status: 200 }));
        vi.stubGlobal('fetch', fetchMock);

        const snapshot = await getActivitySnapshot('thread/1', { runId: 'run/2' });

        expect(snapshot.run_id).toBe('run/2');
        expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
            'http://localhost:8000/api/v1/threads/thread%2F1/activities?run_id=run%2F2'
        );
    });

    it('rejects a response that does not match the requested run', async () => {
        const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
            thread_id: 'thread-1',
            run_id: 'latest-run',
            run_status: 'completed',
            cursor: 0,
            active_activities: [],
            recent_activities: [],
            pending_interactions: [],
            completed_outputs: [],
        }), { status: 200 }));
        vi.stubGlobal('fetch', fetchMock);

        await expect(
            getActivitySnapshot('thread-1', { runId: 'older-run' })
        ).rejects.toThrow('activity snapshot run identity mismatch');
    });

    it('keeps the latest-run request as the default', async () => {
        const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
            thread_id: 'thread-1',
            run_id: 'latest-run',
            run_status: 'completed',
            cursor: 0,
            active_activities: [],
            recent_activities: [],
            pending_interactions: [],
            completed_outputs: [],
        }), { status: 200 }));
        vi.stubGlobal('fetch', fetchMock);

        await getActivitySnapshot('thread-1');

        expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
            'http://localhost:8000/api/v1/threads/thread-1/activities'
        );
    });

    it('marks the stream connected after receiving event-stream headers without waiting for an event', async () => {
        let streamController: ReadableStreamDefaultController<Uint8Array> | undefined;
        const response = new Response(new ReadableStream<Uint8Array>({
            start(controller) { streamController = controller; },
        }), { status: 200, headers: { 'Content-Type': 'text/event-stream; charset=utf-8' } });
        const fetchMock = vi.fn().mockResolvedValue(response);
        vi.stubGlobal('fetch', fetchMock);
        const abortController = new AbortController();
        let markConnected: (() => void) | undefined;
        const connected = new Promise<void>((resolve) => { markConnected = resolve; });

        const consuming = consumeWorkflowEvents(
            'thread-1', 18, abortController.signal, () => undefined, 'run-1',
            () => markConnected?.(),
        );
        await connected;

        expect(fetchMock).toHaveBeenCalledOnce();
        abortController.abort();
        streamController?.close();
        await consuming;
    });
});
