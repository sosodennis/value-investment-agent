export type AgentStatus = 'idle' | 'running' | 'done' | 'attention' | 'error';

export interface AgentInfo {
    id: string;
    name: string;
    description: string;
    avatar: string;
    status: AgentStatus;
    role?: string;
    output?: any;
}

export interface DimensionScore {
    name: string;
    score: number;
    color: string;
}

export interface FinancialMetrics {
    pb: number;
    pe: number;
    roe: number;
    revenueGrowth: number;
}
