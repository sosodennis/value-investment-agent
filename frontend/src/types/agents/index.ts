import { PreviewPayload } from '@/types/preview';

export type AgentStatus = 'idle' | 'running' | 'done' | 'attention' | 'error' | 'degraded';

export interface AgentErrorLog {
    node: string;
    error: string;
    timestamp?: string;
    severity: 'warning' | 'error';
}

export interface ArtifactReference {
    artifact_id: string;
    download_url: string;
    type: string;
}

export interface StandardAgentOutput {
    summary: string;
    preview?: PreviewPayload | null;
    reference?: ArtifactReference | null;
    error_logs?: AgentErrorLog[];
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
