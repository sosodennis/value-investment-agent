import { useCallback, useState } from 'react';
import { clientLogger } from '@/lib/logger';
import { InterruptResumePayload } from '../types/interrupts';
import {
    Message,
    parseAgentEvent,
    parseApiErrorMessage,
    parseHistoryResponse,
    parseStreamStartResponse,
    parseThreadStateResponse,
    StreamRequest,
} from '../types/protocol';
import { useAgentReducer } from './useAgentReducer';
import { deriveActiveAgentId } from '@/lib/agent-session-state';

const API_URL = process.env.NEXT_PUBLIC_LANGGRAPH_URL || 'http://localhost:8000';

const toErrorMessage = (error: unknown, fallback: string): string =>
    error instanceof Error ? error.message : fallback;

const readErrorMessage = async (
    response: Response,
    fallback: string
): Promise<string> => {
    try {
        const raw: unknown = await response.json();
        return (
            parseApiErrorMessage(raw) || `${fallback} (HTTP ${response.status})`
        );
    } catch {
        return `${fallback} (HTTP ${response.status})`;
    }
};

export function useAgent(assistantId: string = 'agent') {
    void assistantId;
    const {
        state,
        processEvent,
        initSession,
        loadHistory: dispatchLoadHistory,
        addUserMessage,
        setError,
    } = useAgentReducer();

    const [isLoading, setIsLoading] = useState(false);
    const [hasMore, setHasMore] = useState(true);
    const activeAgentId = deriveActiveAgentId({
        active_agent_id: state.activeAgentId,
        current_node: state.currentNode,
        current_status: state.currentStatus,
        status_history: state.statusHistory,
        node_statuses: Object.fromEntries(
            Object.entries(state.agents).map(([id, data]) => [id, data.status])
        ),
        is_running: state.status === 'running' || state.status === 'paused',
    });

    const parseStream = useCallback(
        async (threadId: string, afterSeq?: number) => {
            let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
            try {
                const streamUrl = new URL(`${API_URL}/stream/${threadId}`);
                if (
                    typeof afterSeq === 'number' &&
                    Number.isFinite(afterSeq) &&
                    afterSeq > 0
                ) {
                    streamUrl.searchParams.set('after_seq', String(afterSeq));
                }
                const response = await fetch(streamUrl.toString());
                if (!response.ok) {
                    throw new Error(
                        await readErrorMessage(response, 'Failed to attach to stream')
                    );
                }

                reader = response.body?.getReader();
                const decoder = new TextDecoder();
                if (!reader) return;

                let buffer = '';
                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;

                    buffer += decoder.decode(value, { stream: true });
                    const events = buffer.split(/\r?\n\r?\n/);
                    buffer = events.pop() || '';

                    for (const rawEvent of events) {
                        const trimmed = rawEvent.replace(/\r/g, '').trim();
                        if (!trimmed || trimmed.startsWith(':')) continue;

                        const dataLines: string[] = [];
                        const lines = trimmed.split('\n');
                        for (const line of lines) {
                            if (line.startsWith('data:')) {
                                dataLines.push(line.slice(5).trimStart());
                            }
                        }

                        if (dataLines.length === 0) continue;
                        const jsonStr = dataLines.join('\n');
                        if (jsonStr === 'null') continue;
                        try {
                            const parsed: unknown = JSON.parse(jsonStr);
                            const event = parseAgentEvent(parsed, 'stream event');
                            processEvent(event);
                        } catch (e) {
                            clientLogger.error('stream.parse_error', {
                                event: trimmed,
                                error: e instanceof Error ? e.message : String(e),
                                threadId,
                            });
                            throw e;
                        }
                    }
                }
            } catch (error) {
                setError(toErrorMessage(error, 'An error occurred during streaming.'));
            } finally {
                reader?.releaseLock();
                setIsLoading(false);
            }
        },
        [processEvent, setError]
    );

    const sendMessage = useCallback(
        async (content: string, newSession = false) => {
            setIsLoading(true);

            let currentThreadId = state.threadId;
            if (newSession || !currentThreadId) {
                currentThreadId = `thread_${Date.now()}`;
                initSession(currentThreadId);
            }

            const userMsg: Message = {
                id: `user_${Date.now()}`,
                role: 'user',
                content,
                type: 'text',
            };
            addUserMessage(userMsg);

            try {
                const payload: StreamRequest = {
                    thread_id: currentThreadId,
                    message: content,
                };
                const res = await fetch(`${API_URL}/stream`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });

                if (!res.ok) {
                    throw new Error(await readErrorMessage(res, 'Could not start job'));
                }
                const startData = parseStreamStartResponse(await res.json());
                if (startData.thread_id !== currentThreadId) {
                    throw new Error(
                        `Thread ID mismatch: expected ${currentThreadId}, got ${startData.thread_id}.`
                    );
                }
                await parseStream(currentThreadId);
            } catch (error) {
                setError(toErrorMessage(error, 'Failed to send message.'));
                setIsLoading(false);
            }
        },
        [state.threadId, initSession, addUserMessage, parseStream, setError]
    );

    const submitCommand = useCallback(
        async (payload: InterruptResumePayload) => {
            const threadId = state.threadId;
            if (!threadId) {
                setError('Session ID missing. Please refresh the page.');
                return;
            }

            let interactionText = 'Resumed execution';
            if (
                'selected_symbol' in payload &&
                typeof payload.selected_symbol === 'string'
            ) {
                interactionText = `Selected Ticker: ${payload.selected_symbol}`;
            } else if (
                'approved' in payload &&
                typeof payload.approved === 'boolean'
            ) {
                interactionText = payload.approved
                    ? 'Approved Audit Plan'
                    : 'Rejected Audit Plan';
            }

            const userActionMsg: Message = {
                id: `user_action_${Date.now()}`,
                role: 'user',
                content: interactionText,
                type: 'text',
            };
            addUserMessage(userActionMsg);
            setIsLoading(true);

            try {
                const requestPayload: StreamRequest = {
                    thread_id: threadId,
                    resume_payload: payload,
                };
                const res = await fetch(`${API_URL}/stream`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(requestPayload),
                });
                if (!res.ok) {
                    throw new Error(await readErrorMessage(res, 'Could not resume job'));
                }
                const startData = parseStreamStartResponse(await res.json());
                if (startData.thread_id !== threadId) {
                    throw new Error(
                        `Thread ID mismatch: expected ${threadId}, got ${startData.thread_id}.`
                    );
                }
                await parseStream(threadId);
            } catch (error) {
                setError(toErrorMessage(error, 'Failed to submit command.'));
                setIsLoading(false);
            }
        },
        [state.threadId, addUserMessage, parseStream, setError]
    );

    const loadHistory = useCallback(
        async (id: string, before?: string) => {
            setIsLoading(true);
            try {
                if (before) {
                    const historyUrl = new URL(`${API_URL}/history/${id}`);
                    historyUrl.searchParams.append('before', before);
                    const historyResponse = await fetch(historyUrl.toString());
                    if (!historyResponse.ok) {
                        throw new Error(
                            await readErrorMessage(historyResponse, 'History fetch failed')
                        );
                    }

                    const historyRaw: unknown = await historyResponse.json();
                    const historyData = parseHistoryResponse(historyRaw);
                    if (historyData.length < 20) setHasMore(false);
                    dispatchLoadHistory(historyData, id);
                    return;
                }

                const stateResponse = await fetch(`${API_URL}/thread/${id}`);
                if (!stateResponse.ok) {
                    throw new Error(
                        await readErrorMessage(stateResponse, 'Thread state fetch failed')
                    );
                }
                const stateRaw: unknown = await stateResponse.json();
                const stateData = parseThreadStateResponse(stateRaw);
                dispatchLoadHistory(stateData.messages, id, stateData);
                if (stateData.is_running) {
                    const afterSeq =
                        stateData.cursor?.last_seq_id ?? stateData.last_seq_id;
                    await parseStream(id, afterSeq);
                }
            } catch (error) {
                setError(toErrorMessage(error, 'Failed to load history.'));
            } finally {
                setIsLoading(false);
            }
        },
        [dispatchLoadHistory, parseStream, setError]
    );

    return {
        messages: state.messages,
        sendMessage,
        submitCommand,
        loadHistory,
        isLoading,
        error: state.error,
        threadId: state.threadId,
        hasMore,
        agentStatuses: Object.fromEntries(
            Object.entries(state.agents).map(([id, data]) => [id, data.status])
        ),
        agentOutputs: Object.fromEntries(
            Object.entries(state.agents).map(([id, data]) => [id, data.output])
        ),
        currentNode: state.currentNode,
        currentStatus: state.currentStatus,
        activityFeed: state.statusHistory,
        activeAgentId,
        projectionUpdatedAt: state.cursorUpdatedAt,
    };
}
