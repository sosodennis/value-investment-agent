import { AgentStatus, StandardAgentOutput } from './agents';
import { HumanTickerSelection, InterruptRequestData, InterruptResumePayload } from './interrupts';
import { isRecord } from './preview';

export interface Message {
    id: string;
    role: 'user' | 'assistant' | 'system' | 'tool';
    content: string;
    type?: 'text' | 'financial_report' | 'interrupt.request';
    data?: unknown;
    isInteractive?: boolean;
    created_at?: string;
    agentId?: string;
}

export type AgentEventType =
    | 'lifecycle.status'
    | 'content.delta'
    | 'state.update'
    | 'interrupt.request'
    | 'agent.status'
    | 'error';

interface AgentEventBase {
    id: string;
    timestamp: string;
    thread_id: string;
    run_id: string;
    seq_id: number;
    source: string;
    metadata?: Record<string, unknown>;
}

export interface ContentDeltaEvent extends AgentEventBase {
    type: 'content.delta';
    data: {
        content: string;
    };
}

export interface StateUpdateEvent extends AgentEventBase {
    type: 'state.update';
    data: StandardAgentOutput;
}

export interface InterruptRequestEvent extends AgentEventBase {
    type: 'interrupt.request';
    data: InterruptRequestData;
}

export interface AgentStatusEvent extends AgentEventBase {
    type: 'agent.status';
    data: {
        status: AgentStatus;
        node?: string;
    };
}

export interface LifecycleStatusEvent extends AgentEventBase {
    type: 'lifecycle.status';
    data: {
        status: 'idle' | 'running' | 'paused' | 'error' | 'done';
    };
}

export interface ErrorEvent extends AgentEventBase {
    type: 'error';
    data: {
        message: string;
    };
}

export type AgentEvent =
    | ContentDeltaEvent
    | StateUpdateEvent
    | InterruptRequestEvent
    | AgentStatusEvent
    | LifecycleStatusEvent
    | ErrorEvent;

export interface ThreadStateResponse {
    thread_id: string;
    messages: Message[];
    interrupts: HumanTickerSelection[];
    resolved_ticker?: string | null;
    status?: string | null;
    next?: string[] | null;
    is_running: boolean;
    node_statuses: Record<string, AgentStatus>;
    agent_outputs: Record<string, StandardAgentOutput>;
    last_seq_id?: number;
}

export interface StreamRequest {
    thread_id: string;
    message?: string;
    resume_payload?: InterruptResumePayload;
}

export interface StreamStartResponse {
    status: 'started' | 'running';
    thread_id: string;
}

export const isAgentEvent = (value: unknown): value is AgentEvent => {
    if (!isRecord(value)) return false;
    const type = value.type;
    if (typeof type !== 'string') return false;
    if (typeof value.id !== 'string') return false;
    if (typeof value.timestamp !== 'string') return false;
    if (typeof value.thread_id !== 'string') return false;
    if (typeof value.run_id !== 'string') return false;
    if (typeof value.seq_id !== 'number') return false;
    if (typeof value.source !== 'string') return false;
    if (!isRecord(value.data)) return false;
    return (
        type === 'lifecycle.status' ||
        type === 'content.delta' ||
        type === 'state.update' ||
        type === 'interrupt.request' ||
        type === 'agent.status' ||
        type === 'error'
    );
};
