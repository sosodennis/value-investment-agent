import { useCallback, useState } from 'react';
import { InterruptResumePayload } from '../types/interrupts';
import {
    isAgentEvent,
    Message,
    parseHistoryResponse,
    parseStreamStartResponse,
    parseThreadStateResponse,
    StreamRequest,
} from '../types/protocol';
import { useAgentReducer } from './useAgentReducer';

const API_URL = process.env.NEXT_PUBLIC_LANGGRAPH_URL || 'http://localhost:8000';

const toErrorMessage = (error: unknown, fallback: string): string =>
    error instanceof Error ? error.message : fallback;

const hasDetail = (value: object): value is { detail: unknown } =>
    'detail' in value;

const parseErrorDetail = (value: unknown): string | null => {
    if (typeof value !== 'object' || value === null || Array.isArray(value)) {
        return null;
    }
    if (!hasDetail(value)) return null;
    const detail = value.detail;
    return typeof detail === 'string' ? detail : null;
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

    const parseStream = useCallback(
        async (threadId: string) => {
            let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
            try {
                const response = await fetch(`${API_URL}/stream/${threadId}`);
                if (!response.ok) throw new Error('Failed to attach to stream');

                reader = response.body?.getReader();
                const decoder = new TextDecoder();
                if (!reader) return;

                let buffer = '';
                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;

                    buffer += decoder.decode(value, { stream: true });
                    const lines = buffer.split('\n');
                    buffer = lines.pop() || '';

                    for (const line of lines) {
                        if (!line.startsWith('data: ')) continue;
                        const jsonStr = line.slice(6);
                        if (jsonStr === 'null') return;
                        try {
                            const parsed: unknown = JSON.parse(jsonStr);
                            if (isAgentEvent(parsed)) {
                                processEvent(parsed);
                            } else {
                                console.warn('Dropped invalid SSE payload:', parsed);
                            }
                        } catch (e) {
                            console.error('Error parsing SSE data:', line, e);
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
                    const errorRaw: unknown = await res.json();
                    throw new Error(parseErrorDetail(errorRaw) || 'Could not start job');
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
                    const errorRaw: unknown = await res.json();
                    throw new Error(parseErrorDetail(errorRaw) || 'Could not resume job');
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
                const historyUrl = new URL(`${API_URL}/history/${id}`);
                if (before) historyUrl.searchParams.append('before', before);

                const historyResponse = await fetch(historyUrl.toString());
                if (!historyResponse.ok) {
                    throw new Error(`History fetch failed: ${historyResponse.status}`);
                }

                const historyRaw: unknown = await historyResponse.json();
                const historyData = parseHistoryResponse(historyRaw);
                if (historyData.length < 20) setHasMore(false);

                const stateResponse = await fetch(`${API_URL}/thread/${id}`);
                if (stateResponse.ok) {
                    const stateRaw: unknown = await stateResponse.json();
                    const stateData = parseThreadStateResponse(stateRaw);
                    dispatchLoadHistory(historyData, id, stateData);
                    if (stateData.is_running && !before) {
                        await parseStream(id);
                    }
                } else {
                    dispatchLoadHistory(historyData, id);
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
    };
}
