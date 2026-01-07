import { useState, useCallback, useRef } from 'react';
import { Interrupt } from '../types/interrupts';
import { AgentStatus } from '../types/agents';

export interface Message {
    id: string;
    role: 'user' | 'assistant' | 'system' | 'tool';
    content: string;
    type?: 'text' | 'financial_report' | 'interrupt_ticker' | 'interrupt_approval';
    data?: any;
    isInteractive?: boolean;
    created_at?: string;
    agentId?: string;
}

const API_URL = process.env.NEXT_PUBLIC_LANGGRAPH_URL || 'http://localhost:8000';

export function useAgent(assistantId: string = "agent") {
    const [messages, setMessages] = useState<Message[]>([]);
    const [threadId, setThreadId] = useState<string | null>(null);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [resolvedTicker, setResolvedTicker] = useState<string | null>(null);
    const [hasMore, setHasMore] = useState(true);
    const [financialReports, setFinancialReports] = useState<any[]>([]);
    const [currentNode, setCurrentNode] = useState<string | null>(null);
    const [currentStatus, setCurrentStatus] = useState<string | null>(null);
    const [activityFeed, setActivityFeed] = useState<{ id: string, node: string, status: string, timestamp: number }[]>([]);
    const [agentStatuses, setAgentStatuses] = useState<Record<string, AgentStatus>>({
        fundamental_analysis: 'idle',
        executor: 'idle',
        auditor: 'idle',
        approval: 'idle',
        calculator: 'idle',
    });
    const [agentOutputs, setAgentOutputs] = useState<Record<string, any>>({});

    const messagesRef = useRef<Message[]>([]);
    messagesRef.current = messages;

    const parseStream = async (thread_id: string, currentAiMsgId: string) => {
        console.log(`📡 [parseStream] Opening detached stream for ${thread_id}...`);
        let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
        let latestAiMsgId = currentAiMsgId;
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
                            const envelope = JSON.parse(jsonStr);

                            // === 1. HANDLE ERRORS ===
                            if (envelope.type === 'error') {
                                console.error("❌ Job Error:", envelope.data);
                                setError(envelope.data.message || "An unknown error occurred.");
                                continue;
                            }

                            // === 2. HANDLE INTERRUPTS ===
                            else if (envelope.type === 'interrupt') {
                                const interruptVal = envelope.data[0] as Interrupt;
                                console.log("⏸️ Interrupt Detected:", interruptVal);

                                let msgType: Message['type'] = 'text';
                                if (interruptVal.type === 'ticker_selection') msgType = 'interrupt_ticker';
                                if (interruptVal.type === 'approval_request') msgType = 'interrupt_approval';

                                setCurrentStatus('Waiting for input...');
                                setMessages(prev => [...prev, {
                                    id: `interrupt_${Date.now()}`,
                                    role: 'assistant',
                                    content: '',
                                    type: msgType,
                                    data: interruptVal,
                                    isInteractive: true
                                }]);
                                continue;
                            }

                            // === 3. HANDLE LANGGRAPH EVENTS ===
                            if (envelope.type === 'event') {
                                const eventData = envelope.data;
                                const currentEventType = eventData.event;

                                // Token Streaming
                                if (currentEventType === 'on_chat_model_stream') {
                                    const chunk = eventData.data?.chunk;
                                    if (chunk?.content) {
                                        const text = typeof chunk.content === 'string'
                                            ? chunk.content
                                            : chunk.content[0]?.text || '';

                                        if (text) {
                                            setMessages((prev) => {
                                                const lastIdx = prev.length - 1;
                                                const lastMsg = prev[lastIdx];
                                                if (lastMsg && lastMsg.role === 'assistant' && lastMsg.id === latestAiMsgId && !lastMsg.type) {
                                                    const newMsgs = [...prev];
                                                    newMsgs[lastIdx] = { ...lastMsg, content: lastMsg.content + text };
                                                    return newMsgs;
                                                } else {
                                                    const newMsgId = `ai_${Date.now()}`;
                                                    latestAiMsgId = newMsgId;
                                                    return [...prev, { id: newMsgId, role: 'assistant', content: text, type: 'text' }];
                                                }
                                            });
                                        }
                                    }
                                }

                                // Chain End Events
                                if (currentEventType === 'on_chain_end') {
                                    const nodeName = eventData.metadata?.langgraph_node;
                                    const output = eventData.data?.output;
                                    const updatePayload = output?.update || output;

                                    const agentId = updatePayload?.metadata?.agent_id ||
                                        updatePayload?.messages?.[0]?.additional_kwargs?.agent_id ||
                                        eventData.metadata?.agent_id;

                                    if (updatePayload && updatePayload.node_statuses) {
                                        setAgentStatuses(prev => ({ ...prev, ...updatePayload.node_statuses }));
                                    }

                                    // --- Track Granular Progress ---
                                    if (nodeName && (updatePayload?.status || updatePayload?.node_statuses)) {
                                        const cleanNode = nodeName.split(':').pop() || nodeName;
                                        const status = updatePayload.status || 'Active';

                                        setCurrentNode(cleanNode);
                                        setCurrentStatus(status);

                                        setActivityFeed(prev => {
                                            if (prev.length > 0 && prev[prev.length - 1].node === cleanNode && prev[prev.length - 1].status === status) {
                                                return prev;
                                            }
                                            return [...prev, {
                                                id: `step_${Date.now()}`,
                                                node: cleanNode,
                                                status: status,
                                                timestamp: Date.now()
                                            }];
                                        });
                                    }

                                    // Capture Financial Data
                                    if (nodeName === 'financial_health' || (nodeName && nodeName.endsWith(':financial_health'))) {
                                        if (updatePayload && updatePayload.financial_reports) {
                                            setFinancialReports(updatePayload.financial_reports);
                                            setMessages(prev => [
                                                ...prev,
                                                {
                                                    id: `fin_report_${Date.now()}`,
                                                    role: 'assistant',
                                                    content: '',
                                                    type: 'financial_report',
                                                    data: updatePayload.financial_reports,
                                                    agentId: agentId || 'fundamental_analysis'
                                                }
                                            ]);
                                        }
                                    }

                                    if (nodeName === 'deciding' || nodeName === 'clarifying' || (nodeName && (nodeName.endsWith(':deciding') || nodeName.endsWith(':clarifying')))) {
                                        if (updatePayload && updatePayload.resolved_ticker) {
                                            setResolvedTicker(updatePayload.resolved_ticker);
                                        }
                                    }

                                    const chunk = eventData.data?.chunk || eventData.data?.output;
                                    if (chunk && typeof chunk === 'object' && chunk.messages && chunk.messages.length > 0) {
                                        const lastMsg = chunk.messages[chunk.messages.length - 1];
                                        if (lastMsg.type === 'ai' && typeof lastMsg.content === 'string') {
                                            const msgContent = lastMsg.content;
                                            const msgAgentId = lastMsg.additional_kwargs?.agent_id || agentId;

                                            setMessages((prev) => {
                                                const lastStateMsg = prev[prev.length - 1];
                                                if (lastStateMsg && lastStateMsg.content === msgContent && lastStateMsg.role === 'assistant') {
                                                    return prev;
                                                }
                                                const newMsgId = `ai_node_${Date.now()}`;
                                                latestAiMsgId = newMsgId;
                                                return [...prev, {
                                                    id: newMsgId,
                                                    role: 'assistant',
                                                    content: msgContent,
                                                    agentId: msgAgentId
                                                }];
                                            });
                                        }
                                    }
                                    latestAiMsgId = `ai_flushed_${Date.now()}`;
                                }
                            }
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
            setCurrentNode(null);
            setCurrentStatus(null);
        }
    };

    const sendMessage = useCallback(async (content: string, newSession: boolean = false) => {
        setIsLoading(true);
        setError(null);

        let currentThreadId = threadId;

        if (newSession || !currentThreadId) {
            currentThreadId = `thread_${Date.now()}`;
            setThreadId(currentThreadId);
            setMessages([]);
            setResolvedTicker(null);
            setFinancialReports([]);
            setAgentOutputs({});
            setActivityFeed([]);
            setAgentStatuses({
                fundamental_analysis: 'idle',
                executor: 'idle',
                auditor: 'idle',
                approval: 'idle',
                calculator: 'idle',
            });
        }

        setResolvedTicker(null);
        setCurrentNode(null);
        setCurrentStatus(null);
        setActivityFeed([]);
        setAgentStatuses(prev => ({ ...prev, fundamental_analysis: 'running' }));

        const userMsg: Message = { id: `user_${Date.now()}`, role: 'user', content, type: 'text' };
        setMessages(prev => [...prev, userMsg]);

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
            await parseStream(currentThreadId, `ai_${Date.now()}`);
        } catch (error) {
            setError((error as Error).message || "Failed to send message.");
            setIsLoading(false);
        }
    }, [threadId, parseStream]);

    const submitCommand = useCallback(async (payload: any) => {
        if (!threadId) {
            console.error("❌ submitCommand called but threadId is null");
            setError("Session ID missing. Please refresh the page.");
            return;
        }
        setMessages(prev => prev.map(m => m.isInteractive ? { ...m, isInteractive: false } : m));
        setError(null);
        setCurrentNode(null);
        setCurrentStatus(null);

        let interactionText = "Resumed execution";
        if (payload.selected_symbol) interactionText = `Selected Ticker: ${payload.selected_symbol}`;
        else if (typeof payload.approved === 'boolean') interactionText = payload.approved ? "✅ Approved Audit Plan" : "❌ Rejected Audit Plan";

        setMessages(prev => [...prev, { id: `user_action_${Date.now()}`, role: 'user', content: interactionText, type: 'text' }]);
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
            await parseStream(threadId, `ai_resume_${Date.now()}`);
        } catch (error) {
            setError((error as Error).message || "Failed to submit command.");
            setIsLoading(false);
        }
    }, [threadId, parseStream]);

    const loadHistory = useCallback(async (id: string, before?: string) => {
        setIsLoading(true);
        setError(null);
        try {
            const historyUrl = new URL(`${API_URL}/history/${id}`);
            if (before) historyUrl.searchParams.append('before', before);

            const historyResponse = await fetch(historyUrl.toString());
            if (!historyResponse.ok) throw new Error(`History fetch failed: ${historyResponse.status}`);
            let historyData: Message[] = await historyResponse.json();

            historyData = historyData.map(msg => {
                if (msg.type === 'ticker_selection' as any) return { ...msg, type: 'interrupt_ticker' };
                if (msg.type === 'approval_request' as any) return { ...msg, type: 'interrupt_approval' };
                return msg;
            });

            if (historyData.length < 20) setHasMore(false);

            setMessages(prev => before ? [...historyData, ...prev] : historyData);
            setThreadId(id);

            const stateResponse = await fetch(`${API_URL}/thread/${id}`);
            if (stateResponse.ok) {
                const stateData = await stateResponse.json();
                setResolvedTicker(stateData.resolved_ticker);
                if (stateData.node_statuses) setAgentStatuses(prev => ({ ...prev, ...stateData.node_statuses }));
                if (stateData.financial_reports) setFinancialReports(stateData.financial_reports);
                if (stateData.agent_outputs) setAgentOutputs(stateData.agent_outputs);

                if (stateData.interrupts && stateData.interrupts.length > 0 && !before) {
                    stateData.interrupts.forEach((interrupt: any, index: number) => {
                        let msgType: Message['type'] = 'text';
                        if (interrupt.type === 'ticker_selection') msgType = 'interrupt_ticker';
                        if (interrupt.type === 'approval_request') msgType = 'interrupt_approval';

                        setMessages(prev => {
                            const exists = prev.some(m => m.type === msgType && JSON.stringify(m.data) === JSON.stringify(interrupt));
                            if (exists) return prev;
                            return [...prev, {
                                id: `interrupt_revived_${index}_${Date.now()}`,
                                role: 'assistant',
                                content: '',
                                type: msgType,
                                data: interrupt,
                                isInteractive: true
                            }];
                        });
                    });
                }

                if (stateData.is_running && !before) {
                    await parseStream(id, `ai_attached_${Date.now()}`);
                }
            }
        } catch (error) {
            setError((error as Error).message || "Failed to load history.");
        } finally {
            setIsLoading(false);
        }
    }, [parseStream]);

    return {
        messages,
        sendMessage,
        submitCommand,
        loadHistory,
        isLoading,
        error,
        threadId,
        resolvedTicker,
        hasMore,
        agentStatuses,
        financialReports,
        currentNode,
        currentStatus,
        activityFeed,
        agentOutputs,
    };
}
