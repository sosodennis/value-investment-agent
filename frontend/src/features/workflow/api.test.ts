import { afterEach, describe, expect, it, vi } from 'vitest';
import { getActivitySnapshot } from './api';

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
        }), { status: 200 }));
        vi.stubGlobal('fetch', fetchMock);

        await getActivitySnapshot('thread-1');

        expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
            'http://localhost:8000/api/v1/threads/thread-1/activities'
        );
    });
});
