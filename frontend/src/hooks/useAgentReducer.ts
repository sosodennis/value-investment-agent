import { useReducer, useCallback } from 'react';
import { AgentEvent, Message } from '../types/protocol';
import { AgentStatus } from '../types/agents';

export interface AgentState {
    status: 'idle' | 'running' | 'paused' | 'error' | 'done';
    messages: Message[];
    threadId: string | null;
    resolvedTicker: string | null;
    financialReports: any[];
    agentStatuses: Record<string, AgentStatus>;
    agentOutputs: Record<string, any>;
    lastSeqId: number;
    error: string | null;
    currentNode: string | null;
    currentStatus: string | null;
    statusHistory: Array<{ id: string, node: string, status: string, timestamp: number }>;
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
    resolvedTicker: null,
    financialReports: [],
    agentStatuses: {
        intent_extraction: 'idle',
        fundamental_analysis: 'idle',
        financial_news_research: 'idle',
        executor: 'idle',
        auditor: 'idle',
        approval: 'idle',
        calculator: 'idle',
        debate: 'idle',
    },
    agentOutputs: {},
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

            if (stateData) {
                // Sync business data if available in snapshot
                newState.resolvedTicker = stateData.intent_extraction?.resolved_ticker || stateData.resolvedTicker;
                newState.financialReports = stateData.fundamental?.financial_reports || stateData.financialReports;
                newState.agentStatuses = { ...state.agentStatuses, ...(stateData.node_statuses || {}) };
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
                            status: status,
                            timestamp: new Date(event.timestamp).getTime()
                        }
                    ].slice(-20);

                    return {
                        ...newState,
                        agentStatuses: {
                            ...state.agentStatuses,
                            [agentId]: status as AgentStatus,
                        },
                        currentNode: node || state.currentNode,
                        currentStatus: status,
                        statusHistory: newHistory
                    };
                }

                case 'state.update': {
                    const data = event.data;
                    const updatedOutputs = { ...state.agentOutputs };



                    // Use event.source to determine where to store data if not specified
                    if (event.source) {
                        updatedOutputs[event.source] = {
                            ...(updatedOutputs[event.source] || {}),
                            ...data
                        };


                    }

                    return {
                        ...newState,
                        resolvedTicker: data.resolved_ticker || state.resolvedTicker,
                        financialReports: data.financial_reports || state.financialReports,
                        agentOutputs: updatedOutputs,
                    };
                }

                case 'interrupt.request': {
                    const interruptData = event.data;
                    let msgType: Message['type'] = 'interrupt.request';

                    // Fallback for legacy interrupt payloads without schemas
                    if (!interruptData.schema) {
                        if (interruptData.type === 'ticker_selection') msgType = 'interrupt_ticker';
                        if (interruptData.type === 'approval_request') msgType = 'interrupt_approval';
                    }

                    const interruptMsg: Message = {
                        id: `interrupt_${event.id}`,
                        role: 'assistant',
                        content: '',
                        type: msgType,
                        data: interruptData,
                        isInteractive: true,
                        agentId: event.source || 'approval',
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
