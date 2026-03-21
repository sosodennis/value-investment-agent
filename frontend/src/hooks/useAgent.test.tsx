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
                    JSON.stringify([
                        {
                            id: 'history-user-1',
                            role: 'user',
                            content: 'Valuate AAPL',
                            type: 'text',
                        },
                    ]),
                    { status: 200, headers: { 'Content-Type': 'application/json' } }
                )
            )
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
                        node_statuses: {
                            intent_extraction: 'done',
                            financial_news_research: 'idle',
                        },
                        agent_outputs: {},
                        last_seq_id: 5,
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
        expect(result.current.activeAgentId).toBe('financial_news_research');
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
