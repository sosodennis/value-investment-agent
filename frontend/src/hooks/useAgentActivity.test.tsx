import { renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useAgentActivity } from './useAgentActivity';

describe('useAgentActivity', () => {
    const fetchMock = vi.fn();

    beforeEach(() => {
        fetchMock.mockReset();
        vi.stubGlobal('fetch', fetchMock);
    });

    afterEach(() => {
        vi.unstubAllGlobals();
    });

    it('loads recent activity for the agent', async () => {
        fetchMock.mockResolvedValueOnce(
            new Response(
                JSON.stringify([
                    {
                        id: 'segment_1',
                        node: 'intent_extraction',
                        agentId: 'intent_extraction',
                        runId: 'run_1',
                        status: 'running',
                        started_at: '2026-03-21T08:00:00Z',
                        updated_at: '2026-03-21T08:00:10Z',
                        ended_at: null,
                        is_current: true,
                    },
                    {
                        id: 'segment_2',
                        node: 'intent_extraction',
                        agentId: 'intent_extraction',
                        runId: 'run_1',
                        status: 'done',
                        started_at: '2026-03-21T07:50:00Z',
                        updated_at: '2026-03-21T07:55:00Z',
                        ended_at: '2026-03-21T07:55:00Z',
                        is_current: false,
                    },
                ]),
                { status: 200, headers: { 'Content-Type': 'application/json' } }
            )
        );

        const { result } = renderHook(() =>
            useAgentActivity('thread_1', 'intent_extraction', 5)
        );

        await waitFor(() => {
            expect(result.current.events).toHaveLength(2);
        });

        expect(result.current.events).toHaveLength(2);
        expect(result.current.events[0]?.agentId).toBe('intent_extraction');
        expect(result.current.events[0]?.runId).toBe('run_1');
        expect(result.current.events[0]?.isCurrent).toBe(true);
        expect(fetchMock).toHaveBeenCalledTimes(1);
        expect(fetchMock.mock.calls[0]?.[0]).toContain('/thread/thread_1/activity');
    });

    it('handles empty activity responses', async () => {
        fetchMock.mockResolvedValueOnce(
            new Response(JSON.stringify([]), {
                status: 200,
                headers: { 'Content-Type': 'application/json' },
            })
        );

        const { result } = renderHook(() =>
            useAgentActivity('thread_2', 'fundamental_analysis', 5)
        );

        await waitFor(() => {
            expect(result.current.hasMore).toBe(false);
        });

        expect(result.current.events).toHaveLength(0);
        expect(result.current.hasMore).toBe(false);
    });

    it('uses pageSize for load more requests when provided', async () => {
        fetchMock
            .mockResolvedValueOnce(
                new Response(
                    JSON.stringify([
                        {
                            id: 'segment_1',
                            node: 'intent_extraction',
                            agentId: 'intent_extraction',
                            runId: 'run_1',
                            status: 'running',
                            started_at: '2026-03-21T08:00:00Z',
                            updated_at: '2026-03-21T08:00:00Z',
                            ended_at: null,
                            is_current: true,
                        },
                    ]),
                    { status: 200, headers: { 'Content-Type': 'application/json' } }
                )
            )
            .mockResolvedValueOnce(
                new Response(
                    JSON.stringify([
                        {
                            id: 'segment_2',
                            node: 'intent_extraction',
                            agentId: 'intent_extraction',
                            runId: 'run_1',
                            status: 'done',
                            started_at: '2026-03-21T07:50:00Z',
                            updated_at: '2026-03-21T07:55:00Z',
                            ended_at: '2026-03-21T07:55:00Z',
                            is_current: false,
                        },
                    ]),
                    { status: 200, headers: { 'Content-Type': 'application/json' } }
                )
            );

        const { result } = renderHook(() =>
            useAgentActivity('thread_3', 'intent_extraction', 5, 10)
        );

        await waitFor(() => {
            expect(result.current.events).toHaveLength(1);
        });

        await result.current.loadMore();

        expect(fetchMock).toHaveBeenCalledTimes(2);
        const secondCall = fetchMock.mock.calls[1]?.[0];
        expect(secondCall).toContain('limit=10');
        const url = new URL(secondCall as string);
        expect(url.searchParams.get('before_updated_at')).toBe(
            '2026-03-21T08:00:00.000Z'
        );
    });
});
