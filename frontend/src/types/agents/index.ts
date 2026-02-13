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

export type AgentOutputKind =
    | 'intent_extraction.output'
    | 'fundamental_analysis.output'
    | 'financial_news_research.output'
    | 'debate.output'
    | 'technical_analysis.output'
    | 'generic.output';

export interface StandardAgentOutput {
    kind: AgentOutputKind;
    version: 'v1';
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
