import { useState, useCallback } from 'react';
import { AgentStatus } from '../types/agents';
import { AgentEvent, Message } from '../types/protocol';
import { useAgentReducer } from './useAgentReducer';

const API_URL = process.env.NEXT_PUBLIC_LANGGRAPH_URL || 'http://localhost:8000';

export function useAgent(assistantId: string = "agent") {
    const {
        state,
        processEvent,
        initSession,
        loadHistory: dispatchLoadHistory, // Renamed to avoid name clash
        addUserMessage,
        setError,
        reset
    } = useAgentReducer();

    const [isLoading, setIsLoading] = useState(false);
    const [hasMore, setHasMore] = useState(true);

    const parseStream = useCallback(async (thread_id: string) => {
        console.log(`📡 [parseStream] Opening detached stream for ${thread_id}...`);
        let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
        try {
            const response = await fetch(`${API_URL}/stream/${thread_id}`);
            if (!response.ok) throw new Error("Failed to attach to stream");

            reader = response.body?.getReader();
            const decoder = new TextDecoder();
            if (!reader) return;

            let buffer = '';
            while (true) {
                const { done, value } = await reader.read();
                if (done) {
                    console.log(`🏁 [parseStream] Stream for ${thread_id} closed.`);
                    break;
                }

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop() || '';

                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        const jsonStr = line.slice(6);
                        if (jsonStr === 'null') {
                            console.log(`🏁 [parseStream] Received EOF from server.`);
                            return;
                        }

                        try {
                            const event: AgentEvent = JSON.parse(jsonStr);
                            processEvent(event);
                        } catch (e) {
                            console.error("Error parsing SSE data:", line, e);
                        }
                    }
                }
            }
        } catch (error) {
            console.error("❌ [parseStream] Stream error:", error);
            setError((error as Error).message || "An error occurred during streaming.");
        } finally {
            reader?.releaseLock();
            setIsLoading(false);
        }
    }, [processEvent, setError]);

    const sendMessage = useCallback(async (content: string, newSession: boolean = false) => {
        setIsLoading(true);

        let currentThreadId = state.threadId;

        if (newSession || !currentThreadId) {
            currentThreadId = `thread_${Date.now()}`;
            initSession(currentThreadId);
        }

        const userMsg: Message = { id: `user_${Date.now()}`, role: 'user', content, type: 'text' };
        addUserMessage(userMsg);

        try {
            const res = await fetch(`${API_URL}/stream`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ thread_id: currentThreadId, message: content })
            });

            if (!res.ok) {
                const errorData = await res.json();
                throw new Error(errorData.detail || "Could not start job");
            }
            await parseStream(currentThreadId);
        } catch (error) {
            setError((error as Error).message || "Failed to send message.");
            setIsLoading(false);
        }
    }, [state.threadId, initSession, addUserMessage, parseStream, setError]);

    const submitCommand = useCallback(async (payload: any) => {
        const threadId = state.threadId;
        if (!threadId) {
            console.error("❌ submitCommand called but threadId is null");
            setError("Session ID missing. Please refresh the page.");
            return;
        }

        // De-activate interactive messages
        // (This would ideally be handled in the reducer/state, but for now we follow old logic)

        let interactionText = "Resumed execution";
        if (payload.selected_symbol) interactionText = `Selected Ticker: ${payload.selected_symbol}`;
        else if (typeof payload.approved === 'boolean') interactionText = payload.approved ? "✅ Approved Audit Plan" : "❌ Rejected Audit Plan";

        const userActionMsg: Message = { id: `user_action_${Date.now()}`, role: 'user', content: interactionText, type: 'text' };
        addUserMessage(userActionMsg);
        setIsLoading(true);

        try {
            const res = await fetch(`${API_URL}/stream`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ thread_id: threadId, resume_payload: payload })
            });

            if (!res.ok) {
                const errorData = await res.json();
                throw new Error(errorData.detail || "Could not resume job");
            }
            await parseStream(threadId);
        } catch (error) {
            setError((error as Error).message || "Failed to submit command.");
            setIsLoading(false);
        }
    }, [state.threadId, addUserMessage, parseStream, setError]);

    const loadHistory = useCallback(async (id: string, before?: string) => {
        setIsLoading(true);
        try {
            const historyUrl = new URL(`${API_URL}/history/${id}`);
            if (before) historyUrl.searchParams.append('before', before);

            const historyResponse = await fetch(historyUrl.toString());
            if (!historyResponse.ok) throw new Error(`History fetch failed: ${historyResponse.status}`);
            let historyData: Message[] = await historyResponse.json();

            // Transform history if needed (e.g. mapping old types to new ones)
            historyData = historyData.map(msg => {
                if ((msg.type as any) === 'ticker_selection') return { ...msg, type: 'interrupt_ticker' };
                if ((msg.type as any) === 'approval_request') return { ...msg, type: 'interrupt_approval' };
                return msg;
            });

            if (historyData.length < 20) setHasMore(false);

            // Re-sync basic state from thread endpoint
            const stateResponse = await fetch(`${API_URL}/thread/${id}`);
            if (stateResponse.ok) {
                const stateData = await stateResponse.json();
                dispatchLoadHistory(historyData, id, stateData);

                if (stateData.is_running && !before) {
                    await parseStream(id);
                }
            } else {
                dispatchLoadHistory(historyData, id);
            }
        } catch (error) {
            setError((error as Error).message || "Failed to load history.");
        } finally {
            setIsLoading(false);
        }
    }, [initSession, setError]);

    return {
        messages: state.messages,
        sendMessage,
        submitCommand,
        loadHistory,
        isLoading,
        error: state.error,
        threadId: state.threadId,
        resolvedTicker: state.resolvedTicker,
        hasMore,
        agentStatuses: state.agentStatuses,
        financialReports: state.financialReports,
        currentNode: state.currentNode,
        currentStatus: state.currentStatus,
        activityFeed: state.statusHistory,
        agentOutputs: state.agentOutputs,
    };
}
