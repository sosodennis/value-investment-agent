export type AgentStatus = 'idle' | 'running' | 'done' | 'attention' | 'error';

export interface StandardAgentOutput {
    summary: string;
    data: any;
}

export interface AgentInfo {
    id: string;
    name: string;
    description: string;
    avatar: string;
    status: AgentStatus;
    role?: string;
    output?: StandardAgentOutput | any; // Transitional type
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
