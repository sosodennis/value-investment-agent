import { act, renderHook, waitFor } from '@testing-library/react';
import { useAgent } from './useAgent';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

describe('useAgent restore flow', () => {
    const fetchMock = vi.fn();

    beforeEach(() => {
        vi.stubGlobal('fetch', fetchMock);
    });

    afterEach(() => {
        vi.unstubAllGlobals();
        fetchMock.mockReset();
    });

    it('hydrates refresh state from thread snapshot instead of history-only messages', async () => {
        fetchMock
            .mockResolvedValueOnce(
                new Response(
                    JSON.stringify({
                        thread_id: 'thread_1',
                        messages: [
                            {
                                id: 'snapshot-ai-1',
                                role: 'assistant',
                                content: 'Resolving ticker',
                                type: 'text',
                                agentId: 'intent_extraction',
                            },
                        ],
                        interrupts: [],
                        is_running: true,
                        agent_statuses: {
                            intent_extraction: 'done',
                            financial_news_research: 'running',
                        },
                        node_statuses: {
                            intent_extraction: 'done',
                            financial_news_research: 'idle',
                        },
                        agent_outputs: {},
                        last_seq_id: 5,
                        cursor: {
                            last_seq_id: 9,
                            updated_at: '2026-03-21T08:00:00Z',
                        },
                        activity_timeline: [
                            {
                                event_id: 'evt_1',
                                seq_id: 9,
                                event_type: 'agent.status',
                                agent_id: 'financial_news_research',
                                node: 'financial_news_research',
                                status: 'running',
                                created_at: '2026-03-21T08:00:00Z',
                                run_id: 'run_1',
                                payload: {},
                            },
                        ],
                        active_agent_id: 'debate',
                        current_node: 'semantic_translate',
                        current_status: 'running',
                        status_history: [
                            {
                                id: 'status_1',
                                node: 'financial_news_research',
                                agentId: 'financial_news_research',
                                status: 'running',
                                timestamp: '2026-03-21T08:00:00Z',
                            },
                        ],
                    }),
                    { status: 200, headers: { 'Content-Type': 'application/json' } }
                )
            )
            .mockResolvedValueOnce(
                new Response('', { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
            );

        const { result } = renderHook(() => useAgent('test-agent'));

        await act(async () => {
            await result.current.loadHistory('thread_1');
        });

        await waitFor(() => {
            expect(result.current.threadId).toBe('thread_1');
            expect(result.current.messages).toHaveLength(1);
        });

        expect(result.current.messages[0]?.id).toBe('snapshot-ai-1');
        expect(result.current.currentNode).toBe('semantic_translate');
        expect(result.current.currentStatus).toBe('running');
        expect(result.current.activityFeed).toHaveLength(1);
        expect(result.current.activityFeed[0]?.agentId).toBe('financial_news_research');
        expect(result.current.agentStatuses.financial_news_research).toBe('running');
        expect(result.current.activeAgentId).toBe('debate');
        expect(fetchMock).toHaveBeenCalledTimes(2);
        expect(fetchMock.mock.calls[0]?.[0]).toContain('/thread/thread_1');
        expect(fetchMock.mock.calls[1]?.[0]).toContain('/stream/thread_1?after_seq=9');
    });

    it('skips stream attach when the thread is not running', async () => {
        fetchMock.mockResolvedValueOnce(
            new Response(
                JSON.stringify({
                    thread_id: 'thread_2',
                    messages: [],
                    interrupts: [],
                    is_running: false,
                    agent_statuses: {
                        intent_extraction: 'done',
                    },
                    node_statuses: {
                        intent_extraction: 'done',
                    },
                    agent_outputs: {},
                    last_seq_id: 0,
                    cursor: {
                        last_seq_id: 0,
                        updated_at: '2026-03-21T08:05:00Z',
                    },
                    activity_timeline: [],
                    status_history: [],
                }),
                { status: 200, headers: { 'Content-Type': 'application/json' } }
            )
        );

        const { result } = renderHook(() => useAgent('test-agent'));

        await act(async () => {
            await result.current.loadHistory('thread_2');
        });

        expect(fetchMock).toHaveBeenCalledTimes(1);
        expect(fetchMock.mock.calls[0]?.[0]).toContain('/thread/thread_2');
    });
});

describe('useAgent Performance', () => {
    it('should have unstable sendMessage reference due to unmemoized parseStream', () => {
        const { result, rerender } = renderHook(() => useAgent('test-agent'));

        const firstSendMessage = result.current.sendMessage;

        // Force a re-render
        rerender();

        const secondSendMessage = result.current.sendMessage;

        // Optimization: The function reference SHOULD NOT change because parseStream is now memoized
        expect(secondSendMessage).toBe(firstSendMessage);
    });
});
