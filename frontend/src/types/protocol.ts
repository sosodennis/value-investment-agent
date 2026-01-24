export interface Message {
    id: string;
    role: 'user' | 'assistant' | 'system' | 'tool';
    content: string;
    type?: 'text' | 'financial_report' | 'interrupt_ticker' | 'interrupt_approval' | 'interrupt.request';
    data?: any;
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

/**
 * Standardized Agent Event Protocol (Matches backend src/interface/protocol.py)
 */
export interface AgentEvent {
    id: string;
    timestamp: string;
    thread_id: string;
    run_id: string;
    seq_id: number;
    type: AgentEventType;
    source: string;
    data: Record<string, any>;
    metadata?: Record<string, any>;
}

/**
 * Specific data structures for different event types
 */
export interface ContentDeltaData {
    content: string;
}

export interface AgentStatusData {
    status: 'idle' | 'running' | 'done' | 'error' | 'attention';
    node?: string;
}

export interface StateUpdateData {
    financial_reports?: any[];
    news_research?: any;
    technical_analysis?: any;
    resolved_ticker?: string;
    [key: string]: any;
}
