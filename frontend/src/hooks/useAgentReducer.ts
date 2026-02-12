import { useCallback, useReducer } from 'react';
import { AgentStatus, StandardAgentOutput } from '../types/agents';
import { HumanTickerSelection, InterruptRequestData } from '../types/interrupts';
import { AgentEvent, Message, ThreadStateResponse } from '../types/protocol';

export interface AgentData {
    status: AgentStatus;
    output: StandardAgentOutput | null;
}

export interface StatusHistoryEntry {
    id: string;
    node: string;
    agentId: string;
    status: string;
    timestamp: number;
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
    statusHistory: StatusHistoryEntry[];
}

export type AgentAction =
    | { type: 'INIT_SESSION'; threadId: string }
    | { type: 'LOAD_HISTORY'; messages: Message[]; threadId: string; stateData?: ThreadStateResponse }
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

const toInterruptRequestData = (
    interrupt: HumanTickerSelection
): InterruptRequestData => {
    const tickerOptions = interrupt.candidates.map((candidate) => candidate.symbol);
    const tickerTitles = interrupt.candidates.map((candidate) => {
        const confidence = `${(candidate.confidence * 100).toFixed(0)}% match`;
        return `${candidate.symbol} - ${candidate.name} (${confidence})`;
    });

    return {
        type: 'ticker_selection',
        title: 'Ticker Resolution',
        description: interrupt.reason || 'Multiple tickers found or ambiguity detected.',
        data: {},
        schema: {
            type: 'object',
            title: 'Select Correct Ticker',
            properties: {
                selected_symbol: {
                    type: 'string',
                    title: 'Target Company',
                    enum: tickerOptions,
                    oneOf: tickerOptions.map((symbol, idx) => ({
                        const: symbol,
                        title: tickerTitles[idx] ?? symbol,
                    })),
                },
            },
            required: ['selected_symbol'],
        },
        ui_schema: {
            selected_symbol: { 'ui:widget': 'radio' },
        },
    };
};

function agentReducer(state: AgentState, action: AgentAction): AgentState {
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
                status: stateData?.is_running ? 'running' : 'idle',
                lastSeqId: stateData?.last_seq_id ?? state.lastSeqId,
            };

            if (stateData?.interrupts.length) {
                const interruptMessages: Message[] = stateData.interrupts.map(
                    (interrupt, idx) => ({
                        id: `pending_interrupt_${Date.now()}_${idx}`,
                        role: 'assistant',
                        content: '',
                        type: 'interrupt.request',
                        data: toInterruptRequestData(interrupt),
                        isInteractive: true,
                        agentId: 'intent_extraction',
                    })
                );
                newState.messages = [...newState.messages, ...interruptMessages];
                newState.status = 'paused';
            }

            if (stateData) {
                const agents: Record<string, AgentData> = { ...state.agents };

                Object.entries(stateData.node_statuses).forEach(([id, status]) => {
                    agents[id] = { ...agents[id], status };
                });

                Object.entries(stateData.agent_outputs).forEach(([id, output]) => {
                    agents[id] = { ...agents[id], output };
                });

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
                messages: state.messages
                    .map((message) =>
                        message.isInteractive ? { ...message, isInteractive: false } : message
                    )
                    .concat(action.message),
            };

        case 'PROCESS_EVENT': {
            const { event } = action;
            if (event.seq_id <= state.lastSeqId) return state;

            const newState = { ...state, lastSeqId: event.seq_id };

            switch (event.type) {
                case 'content.delta': {
                    const content = event.data.content;
                    const lastMsg = state.messages[state.messages.length - 1];
                    if (
                        lastMsg &&
                        lastMsg.role === 'assistant' &&
                        !lastMsg.type &&
                        lastMsg.agentId === event.source
                    ) {
                        const updatedMessages = [...state.messages];
                        updatedMessages[updatedMessages.length - 1] = {
                            ...lastMsg,
                            content: `${lastMsg.content}${content}`,
                        };
                        return { ...newState, messages: updatedMessages };
                    }

                    const newMsg: Message = {
                        id: `ai_${event.id}`,
                        role: 'assistant',
                        content,
                        agentId: event.source,
                    };
                    return { ...newState, messages: [...state.messages, newMsg] };
                }

                case 'agent.status': {
                    const { status, node } = event.data;
                    const agentId = event.source;
                    const lastHistoryEntry = state.statusHistory[state.statusHistory.length - 1];
                    const isRedundant =
                        !!lastHistoryEntry &&
                        lastHistoryEntry.node === (node || agentId) &&
                        lastHistoryEntry.status === status;

                    const newHistory = isRedundant
                        ? state.statusHistory
                        : [
                              ...state.statusHistory,
                              {
                                  id: `status_${event.id}`,
                                  node: node || agentId,
                                  agentId,
                                  status,
                                  timestamp: new Date(event.timestamp).getTime(),
                              },
                          ].slice(-20);

                    return {
                        ...newState,
                        agents: {
                            ...state.agents,
                            [agentId]: {
                                ...state.agents[agentId],
                                status,
                            },
                        },
                        currentNode: node || state.currentNode,
                        currentStatus: status,
                        statusHistory: newHistory,
                    };
                }

                case 'state.update': {
                    const source = event.source;
                    return {
                        ...newState,
                        agents: {
                            ...state.agents,
                            [source]: {
                                ...state.agents[source],
                                output: event.data,
                            },
                        },
                    };
                }

                case 'interrupt.request': {
                    const interruptAgent =
                        event.source && event.source !== 'system.interrupt'
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

                case 'lifecycle.status':
                    return { ...newState, status: event.data.status };

                case 'error':
                    return {
                        ...newState,
                        status: 'error',
                        error: event.data.message || 'Unknown agent error',
                    };

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

    const loadHistory = useCallback(
        (messages: Message[], threadId: string, stateData?: ThreadStateResponse) => {
            dispatch({ type: 'LOAD_HISTORY', messages, threadId, stateData });
        },
        []
    );

    return {
        state,
        processEvent,
        initSession,
        addUserMessage,
        setError,
        reset,
        loadHistory,
    };
}
