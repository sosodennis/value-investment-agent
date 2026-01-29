export type AgentStatus = 'idle' | 'running' | 'done' | 'attention' | 'error';

export interface ArtifactReference {
    artifact_id: string;
    key: string;
    type: string;
}

export interface StandardAgentOutput {
    preview?: any;
    reference?: ArtifactReference;
}

export interface AgentInfo {
    id: string;
    name: string;
    description: string;
    avatar: string;
    status: AgentStatus;
    role?: string;
    output?: StandardAgentOutput;
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
