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

/**
 * Status progression levels for forward-only updates
 */
const STATUS_LEVELS: Record<string, number> = {
    'idle': 0,
    'waiting': 1,
    'running': 2,
    'done': 3,
    'error': 4,
    'attention': 5
};

/**
 * Apply status updates with forward-only progression safeguard
 * Prevents stale statuses from subgraph completions from regressing current state
 */
function applyStatusUpdates(
    currentStatuses: Record<string, AgentStatus>,
    newStatuses: Record<string, string>
): Record<string, AgentStatus> {
    const updated = { ...currentStatuses };

    for (const [key, newStatus] of Object.entries(newStatuses)) {
        const currentStatus = currentStatuses[key as keyof typeof currentStatuses];
        const currentLevel = STATUS_LEVELS[currentStatus] ?? 0;
        const newLevel = STATUS_LEVELS[newStatus] ?? 0;

        // Only allow forward progression or initialization
        const isProgressing = newLevel > currentLevel;
        const isInitializing = !currentStatus || currentStatus === 'idle';

        if (isProgressing || isInitializing) {
            updated[key as keyof typeof updated] = newStatus as AgentStatus;
        } else {
            console.log(`[useAgent] Blocked regression: ${key} ${currentStatus} -/-> ${newStatus}`);
        }
    }

    return updated;
}


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
        intent_extraction: 'idle',
        fundamental_analysis: 'idle',
        financial_news_research: 'idle',
        executor: 'idle',
        auditor: 'idle',
        approval: 'idle',
        calculator: 'idle',
        debate: 'idle',
    });
    const [agentOutputs, setAgentOutputs] = useState<Record<string, any>>({});

    const messagesRef = useRef<Message[]>([]);
    messagesRef.current = messages;

    const parseStream = useCallback(async (thread_id: string, currentAiMsgId: string) => {
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

                                // Chain Start Events - Track when nodes begin execution
                                if (currentEventType === 'on_chain_start') {
                                    const nodeName = eventData.metadata?.langgraph_node;
                                    if (nodeName) {
                                        const cleanNode = nodeName.split(':').pop() || nodeName;

                                        // Use centralized node-to-agent mapping
                                        const { createNodeToAgentMap } = require('../config/agents');
                                        const nodeToAgentMap = createNodeToAgentMap();

                                        const agentId = nodeToAgentMap[cleanNode.toLowerCase()];
                                        if (agentId) {
                                            console.log(`[useAgent] Node started: ${cleanNode} -> ${agentId} = running`);
                                            setAgentStatuses(prev => ({ ...prev, [agentId]: 'running' }));
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

                                    // Primary: Use node_statuses from the update payload if available
                                    // Handle status updates from node_statuses payload
                                    if (updatePayload?.node_statuses) {
                                        console.log('[useAgent] Received node_statuses:', updatePayload.node_statuses);

                                        setAgentStatuses(prev =>
                                            applyStatusUpdates(prev, updatePayload.node_statuses)
                                        );
                                    }
                                    // Fallback: Derive status from node completion
                                    else if (nodeName) {
                                        const { getAgentIdFromNode } = require('../config/agents');
                                        const agentId = getAgentIdFromNode(nodeName.split(':').pop() || nodeName);

                                        if (agentId) {
                                            console.log(`[useAgent] Node completed: ${nodeName} -> ${agentId} = done`);
                                            setAgentStatuses(prev => ({ ...prev, [agentId]: 'done' }));
                                        }
                                    }

                                    // --- Track Granular Progress ---
                                    if (nodeName && (updatePayload?.status || updatePayload?.node_statuses || updatePayload?.internal_progress || updatePayload?.current_node)) {
                                        const cleanNode = updatePayload?.current_node || nodeName.split(':').pop() || nodeName;

                                        // Status priority: explicit status > internal_progress[cleanNode] > node_statuses[cleanNode] > Done
                                        let status = updatePayload.status;
                                        if (!status && updatePayload.internal_progress && updatePayload.internal_progress[cleanNode]) {
                                            status = updatePayload.internal_progress[cleanNode];
                                        }
                                        if (!status && updatePayload.node_statuses && updatePayload.node_statuses[cleanNode]) {
                                            status = updatePayload.node_statuses[cleanNode];
                                        }
                                        if (!status) status = 'Done';

                                        console.log(`[useAgent] Tracking progress: ${cleanNode} (${status})`);
                                        setCurrentNode(cleanNode);
                                        setCurrentStatus(status);

                                        // Update activity feed for all nodes in internal_progress if provided
                                        // or just the current cleanNode
                                        const updates: Array<{ node: string, status: string }> = [];
                                        if (updatePayload.internal_progress) {
                                            Object.entries(updatePayload.internal_progress).forEach(([node, stat]) => {
                                                updates.push({ node, status: stat as string });
                                            });
                                        } else {
                                            updates.push({ node: cleanNode, status });
                                        }

                                        setActivityFeed(prev => {
                                            let newFeed = [...prev];

                                            updates.forEach(update => {
                                                const existingIdx = newFeed.findIndex(item => item.node === update.node);
                                                if (existingIdx !== -1) {
                                                    // Update existing item
                                                    newFeed[existingIdx] = {
                                                        ...newFeed[existingIdx],
                                                        status: update.status,
                                                        timestamp: Date.now()
                                                    };
                                                } else {
                                                    // Add new item
                                                    newFeed.push({
                                                        id: `step_${update.node}_${Date.now()}`,
                                                        node: update.node,
                                                        status: update.status,
                                                        timestamp: Date.now()
                                                    });
                                                }
                                            });

                                            // Final sort/filter if needed, but append order is generally fine
                                            return newFeed;
                                        });
                                    }

                                    // Capture Financial Data
                                    if (nodeName === 'financial_health' || (nodeName && nodeName.endsWith(':financial_health'))) {
                                        const reports = updatePayload.fundamental?.financial_reports || updatePayload.financial_reports;
                                        if (reports) {
                                            setFinancialReports(reports);
                                            setMessages(prev => [
                                                ...prev,
                                                {
                                                    id: `fin_report_${Date.now()}`,
                                                    role: 'assistant',
                                                    content: '',
                                                    type: 'financial_report',
                                                    data: reports,
                                                    agentId: agentId || 'fundamental_analysis'
                                                }
                                            ]);
                                        }
                                    }

                                    // Capture News Research Data
                                    if (nodeName === 'aggregator_node' || (nodeName && nodeName.endsWith(':aggregator_node'))) {
                                        const newsOutput = updatePayload.financial_news?.output || updatePayload.financial_news_output;
                                        if (newsOutput) {
                                            setAgentOutputs(prev => ({
                                                ...prev,
                                                financial_news_research: newsOutput
                                            }));
                                        }
                                    }

                                    // Capture Debate Data
                                    if (nodeName === 'moderator' || nodeName === 'verdict' || nodeName === 'process_debate' ||
                                        (nodeName && (nodeName.endsWith(':moderator') || nodeName.endsWith(':verdict') || nodeName.endsWith(':process_debate')))) {
                                        const debateOutput = updatePayload.debate?.conclusion || updatePayload.debate_conclusion || updatePayload.debate;
                                        if (debateOutput) {
                                            // Handle case where debateOutput is the full context vs just conclusion
                                            const conclusion = debateOutput.conclusion || (debateOutput.scenario_analysis ? debateOutput : null);

                                            if (conclusion) {
                                                setAgentOutputs(prev => ({
                                                    ...prev,
                                                    debate: {
                                                        conclusion,
                                                        // Preserve other context if available
                                                        history: debateOutput.history || prev.debate?.history,
                                                        bull_thesis: debateOutput.bull_thesis || prev.debate?.bull_thesis,
                                                        bear_thesis: debateOutput.bear_thesis || prev.debate?.bear_thesis
                                                    }
                                                }));
                                            }
                                        }
                                    }

                                    // Capture Technical Analysis Data
                                    if (nodeName === 'semantic_translate' || (nodeName && nodeName.endsWith(':semantic_translate'))) {
                                        const taOutput = updatePayload.technical_analysis?.output;
                                        if (taOutput) {
                                            setAgentOutputs(prev => ({
                                                ...prev,
                                                technical_analysis: taOutput
                                            }));
                                        }
                                    }

                                    // Capture resolved ticker from intent_extraction
                                    if (nodeName === 'deciding' || nodeName === 'clarifying' || (nodeName && (nodeName.endsWith(':deciding') || nodeName.endsWith(':clarifying')))) {
                                        const ticker = updatePayload.intent_extraction?.resolved_ticker || updatePayload.resolved_ticker;
                                        if (ticker) {
                                            setResolvedTicker(ticker);
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
    }, []);

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
                intent_extraction: 'idle',
                fundamental_analysis: 'idle',
                financial_news_research: 'idle',
                executor: 'idle',
                auditor: 'idle',
                approval: 'idle',
                calculator: 'idle',
                debate: 'idle',
            });
        }

        setResolvedTicker(null);
        setCurrentNode(null);
        setCurrentStatus(null);
        setActivityFeed([]);
        setAgentStatuses(prev => ({ ...prev, intent_extraction: 'running' }));

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

                // Map nested state from backend V2
                const resolvedTicker = stateData.intent_extraction?.resolved_ticker || stateData.fundamental?.resolved_ticker || stateData.resolved_ticker;
                const nodeStatuses = stateData.node_statuses || {};
                const reports = stateData.fundamental?.financial_reports || stateData.financial_reports || [];

                setResolvedTicker(resolvedTicker);
                if (nodeStatuses) setAgentStatuses(prev => ({ ...prev, ...nodeStatuses }));
                if (reports) setFinancialReports(reports);

                // Reconstruct agent outputs from nested contexts
                const outputs: Record<string, any> = {};

                if (stateData.fundamental?.analysis_output) {
                    outputs.fundamental_analysis = {
                        analysis_output: stateData.fundamental.analysis_output,
                        financial_reports: reports
                    };
                }

                if (stateData.financial_news?.output) {
                    outputs.financial_news_research = stateData.financial_news.output;
                }

                if (stateData.debate?.conclusion) {
                    outputs.debate = {
                        conclusion: stateData.debate.conclusion,
                        history: stateData.debate.history,
                        bull_thesis: stateData.debate.bull_thesis,
                        bear_thesis: stateData.debate.bear_thesis
                    };
                } else if (stateData.agent_outputs?.debate) {
                    // Fallback for older sessions or legacy format
                    outputs.debate = stateData.agent_outputs.debate.conclusion
                        ? stateData.agent_outputs.debate
                        : { conclusion: stateData.agent_outputs.debate };
                }

                if (stateData.technical_analysis?.output) {
                    outputs.technical_analysis = stateData.technical_analysis.output;
                }

                setAgentOutputs(outputs);

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
