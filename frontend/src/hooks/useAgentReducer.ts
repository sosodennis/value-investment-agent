import { useReducer, useCallback } from 'react';
import { AgentEvent, Message } from '../types/protocol';
import { AgentStatus } from '@/types/agents';

export interface AgentData {
    status: AgentStatus;
    output: any | null;
}

export interface AgentState {
    status: 'idle' | 'running' | 'paused' | 'error' | 'done';
    messages: Message[];
    threadId: string | null;
    agents: Record<string, AgentData>;
    lastSeqId: number;
    error: string | null;
    currentNode: string | null;
    currentStatus: string | null;
    statusHistory: Array<{ id: string, node: string, agentId: string, status: string, timestamp: number }>;
}

export type AgentAction =
    | { type: 'INIT_SESSION'; threadId: string }
    | { type: 'LOAD_HISTORY'; messages: Message[], threadId: string, stateData?: any }
    | { type: 'PROCESS_EVENT'; event: AgentEvent }
    | { type: 'ADD_USER_MESSAGE'; message: Message }
    | { type: 'SET_ERROR'; error: string }
    | { type: 'RESET' };

const initialState: AgentState = {
    status: 'idle',
    messages: [],
    threadId: null,
    agents: {},
    lastSeqId: 0,
    error: null,
    currentNode: null,
    currentStatus: null,
    statusHistory: [],
};

function agentReducer(state: AgentState, action: AgentAction): AgentState {
    console.log(`[Reducer] Action: ${action.type}`, action);

    switch (action.type) {
        case 'INIT_SESSION':
            return {
                ...initialState,
                threadId: action.threadId,
                status: 'running',
            };

        case 'LOAD_HISTORY': {
            const { messages, threadId, stateData } = action;
            const newState: AgentState = {
                ...state,
                threadId,
                messages,
                status: (stateData?.is_running ? 'running' : 'idle') as AgentState['status'],
            };

            // Inject pending interrupts from stateData into messages
            if (stateData?.interrupts && Array.isArray(stateData.interrupts)) {
                const interruptMessages = stateData.interrupts.map((interrupt: any, idx: number) => {
                    // Check if schema exists, if not, synthesize one for known types like 'ticker_selection'
                    let data = interrupt.details || interrupt.data || {};

                    if (interrupt.type === 'ticker_selection' && !data.schema) {
                        const candidates = interrupt.candidates || data.candidates || [];
                        const tickerOptions = candidates.map((c: any) => c.symbol);
                        const tickerTitles = candidates.map((c: any) => {
                            const confidence = typeof c.confidence === 'number'
                                ? `${(c.confidence * 100).toFixed(0)}% match`
                                : 'match';
                            return `${c.symbol} - ${c.name} (${confidence})`;
                        });

                        data = {
                            type: 'ticker_selection',
                            title: 'Ticker Resolution',
                            description: interrupt.reason || data.reason || 'Multiple tickers found or ambiguity detected.',
                            data: {},
                            schema: {
                                type: "object",
                                title: "Select Correct Ticker",
                                properties: {
                                    selected_symbol: {
                                        type: "string",
                                        title: "Target Company",
                                        enum: tickerOptions,
                                        enumNames: tickerTitles
                                    }
                                },
                                required: ["selected_symbol"]
                            },
                            ui_schema: {
                                selected_symbol: { "ui:widget": "radio" }
                            }
                        };
                    }

                    return {
                        id: `pending_interrupt_${Date.now()}_${idx}`,
                        role: 'assistant',
                        content: '',
                        type: 'interrupt.request', // Normalize to interrupt.request for UI
                        data: data,
                        isInteractive: true,
                        agentId: 'intent_extraction',
                    } as Message;
                });

                // Filter out any existing matching interrupts to facilitate idempotency if needed
                // But for now, just append them as they are "pending" state interrupts
                newState.messages = [...newState.messages, ...interruptMessages];
                newState.status = 'paused'; // Force status to paused if interrupts exist
            }

            if (stateData) {
                // Generic Sync: Load all mapped outputs into the agents map
                const agents: Record<string, AgentData> = { ...state.agents };

                // 1. Sync Statuses
                if (stateData.node_statuses) {
                    Object.entries(stateData.node_statuses).forEach(([id, status]) => {
                        agents[id] = { ...agents[id], status: status as AgentStatus };
                    });
                }

                // 2. Sync Outputs (Artifacts)
                if (stateData.agent_outputs) {
                    Object.entries(stateData.agent_outputs).forEach(([id, output]) => {
                        agents[id] = { ...agents[id], output };
                    });
                }

                newState.agents = agents;
            }

            return newState;
        }

        case 'RESET':
            return initialState;

        case 'SET_ERROR':
            return { ...state, error: action.error, status: 'error' };

        case 'ADD_USER_MESSAGE':
            return {
                ...state,
                messages: state.messages.map(m =>
                    m.isInteractive ? { ...m, isInteractive: false } : m
                ).concat(action.message),
            };

        case 'PROCESS_EVENT': {
            const { event } = action;

            // 1. Sequence Check (Ordering Protection)
            if (event.seq_id <= state.lastSeqId) {
                console.warn(`[Reducer] Dropping out-of-order event: ${event.type} (seq: ${event.seq_id}, last: ${state.lastSeqId})`);
                return state;
            }

            const newState = { ...state, lastSeqId: event.seq_id };

            switch (event.type) {
                case 'content.delta': {
                    const content = event.data.content;
                    const lastMsg = state.messages[state.messages.length - 1];

                    // Append to last message if it's an assistant message without a special type
                    if (lastMsg && lastMsg.role === 'assistant' && !lastMsg.type && lastMsg.agentId === event.source) {
                        const updatedMessages = [...state.messages];
                        updatedMessages[updatedMessages.length - 1] = {
                            ...lastMsg,
                            content: lastMsg.content + content,
                        };
                        return { ...newState, messages: updatedMessages };
                    } else {
                        // Start a new message
                        const newMsg: Message = {
                            id: `ai_${event.id}`,
                            role: 'assistant',
                            content: content,
                            agentId: event.source,
                        };
                        return { ...newState, messages: [...state.messages, newMsg] };
                    }
                }

                case 'agent.status': {
                    const { status, node } = event.data;
                    const agentId = event.source;

                    // Idempotency check: Don't add redundant entries to statusHistory
                    const lastHistoryEntry = state.statusHistory[state.statusHistory.length - 1];
                    const isRedundant = lastHistoryEntry &&
                        lastHistoryEntry.node === (node || agentId) &&
                        lastHistoryEntry.status === status;

                    const newHistory = isRedundant ? state.statusHistory : [
                        ...state.statusHistory,
                        {
                            id: `status_${event.id}`,
                            node: node || agentId,
                            agentId: agentId,
                            status: status,
                            timestamp: new Date(event.timestamp).getTime()
                        }
                    ].slice(-20);

                    return {
                        ...newState,
                        agents: {
                            ...state.agents,
                            [agentId]: {
                                ...state.agents[agentId],
                                status: status as AgentStatus
                            }
                        },
                        currentNode: node || state.currentNode,
                        currentStatus: status,
                        statusHistory: newHistory
                    };
                }

                case 'state.update': {
                    const { source, data } = event;

                    if (!source) return newState;

                    return {
                        ...newState,
                        agents: {
                            ...state.agents,
                            [source]: {
                                ...state.agents[source],
                                output: { ...(state.agents[source]?.output || {}), ...data }
                            }
                        }
                    };
                }

                case 'interrupt.request': {
                    const interruptAgent = event.source && event.source !== 'system.interrupt'
                        ? event.source
                        : 'intent_extraction';
                    const interruptMsg: Message = {
                        id: `interrupt_${event.id}`,
                        role: 'assistant',
                        content: '',
                        type: 'interrupt.request',
                        data: event.data,
                        isInteractive: true,
                        agentId: interruptAgent,
                    };

                    return {
                        ...newState,
                        status: 'paused',
                        messages: [...state.messages, interruptMsg],
                    };
                }

                case 'lifecycle.status': {
                    const status = event.data.status;
                    return { ...newState, status: status as AgentState['status'] };
                }

                case 'error': {
                    return {
                        ...newState,
                        status: 'error',
                        error: event.data.message || 'Unknown agent error',
                    };
                }

                default:
                    return newState;
            }
        }

        default:
            return state;
    }
}

export function useAgentReducer() {
    const [state, dispatch] = useReducer(agentReducer, initialState);

    const processEvent = useCallback((event: AgentEvent) => {
        dispatch({ type: 'PROCESS_EVENT', event });
    }, []);

    const initSession = useCallback((threadId: string) => {
        dispatch({ type: 'INIT_SESSION', threadId });
    }, []);

    const addUserMessage = useCallback((message: Message) => {
        dispatch({ type: 'ADD_USER_MESSAGE', message });
    }, []);

    const setError = useCallback((error: string) => {
        dispatch({ type: 'SET_ERROR', error });
    }, []);

    const reset = useCallback(() => {
        dispatch({ type: 'RESET' });
    }, []);

    const loadHistory = useCallback((messages: Message[], threadId: string, stateData?: any) => {
        dispatch({ type: 'LOAD_HISTORY', messages, threadId, stateData });
    }, []);

    return {
        state,
        processEvent,
        initSession,
        loadHistory,
        addUserMessage,
        setError,
        reset,
    };
}
