import { useCallback, useReducer } from 'react';
import type { Message } from '@/types/protocol';
import {
    applyWorkflowEvent,
    createWorkflowActivityState,
    parseWorkflowActivitySnapshot,
    type WorkflowEvent,
    type WorkflowActivityState,
    type ConnectionState,
} from '@/features/workflow';

export interface AgentState {
    status: 'idle' | 'running' | 'paused' | 'error' | 'done';
    messages: Message[];
    threadId: string | null;
    runId: string | null;
    error: string | null;
    workflow: WorkflowActivityState | null;
    connection: ConnectionState;
}
type Action =
    | { type: 'INIT_SESSION'; threadId: string }
    | { type: 'SET_RUN'; runId: string }
    | { type: 'HYDRATE'; snapshot: unknown }
    | { type: 'EVENT'; event: WorkflowEvent }
    | { type: 'CONNECTION'; connection: ConnectionState }
    | { type: 'MESSAGE'; message: Message }
    | { type: 'ERROR'; error: string }
    | { type: 'RESET' };

const initialState: AgentState = { status: 'idle', messages: [], threadId: null, runId: null, error: null, workflow: null, connection: 'disconnected' };
const statusFor = (status: WorkflowActivityState['runStatus']): AgentState['status'] => status === 'running' || status === 'waiting' ? 'running' : status === 'failed' ? 'error' : status === 'completed' || status === 'cancelled' ? 'done' : 'idle';

function reducer(state: AgentState, action: Action): AgentState {
    switch (action.type) {
        case 'INIT_SESSION': return { ...initialState, threadId: action.threadId, status: 'running' };
        case 'SET_RUN': return { ...state, runId: action.runId };
        case 'CONNECTION': return { ...state, connection: action.connection };
        case 'HYDRATE': { const snapshot = parseWorkflowActivitySnapshot(action.snapshot); if (state.runId && state.runId !== snapshot.run_id) return state; return { ...state, threadId: snapshot.thread_id, runId: snapshot.run_id, status: statusFor(snapshot.run_status), workflow: createWorkflowActivityState(snapshot) }; }
        case 'EVENT': {
            if (!state.workflow) return state;
            const workflow = applyWorkflowEvent(state.workflow, action.event);
            if (workflow.gapDetected) return { ...state, workflow };
            return { ...state, workflow, status: statusFor(workflow.runStatus), runId: workflow.runId };
        }
        case 'MESSAGE': return { ...state, messages: [...state.messages, action.message] };
        case 'ERROR': return { ...state, status: 'error', error: action.error };
        case 'RESET': return initialState;
    }
}

export function useAgentReducer() {
    const [state, dispatch] = useReducer(reducer, initialState);
    const initSession = useCallback((threadId: string) => dispatch({ type: 'INIT_SESSION', threadId }), []);
    const setRun = useCallback((runId: string) => dispatch({ type: 'SET_RUN', runId }), []);
    const hydrateWorkflow = useCallback((snapshot: unknown) => dispatch({ type: 'HYDRATE', snapshot }), []);
    const processWorkflowEvent = useCallback((event: WorkflowEvent) => dispatch({ type: 'EVENT', event }), []);
    const setConnection = useCallback((connection: ConnectionState) => dispatch({ type: 'CONNECTION', connection }), []);
    const addUserMessage = useCallback((message: Message) => dispatch({ type: 'MESSAGE', message }), []);
    const setError = useCallback((error: string) => dispatch({ type: 'ERROR', error }), []);
    const reset = useCallback(() => dispatch({ type: 'RESET' }), []);
    return { state, initSession, setRun, hydrateWorkflow, processWorkflowEvent, setConnection, addUserMessage, setError, reset };
}
