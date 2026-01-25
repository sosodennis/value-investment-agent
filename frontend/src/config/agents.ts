/**
 * Centralized Agent Configuration
 * * Single source of truth for UI metadata (Name, Role, Avatar).
 * Node mapping logic has been moved to the Backend.
 */

import { AgentStatus } from '../types/agents';

/**
 * Agent metadata and configuration
 */
export interface AgentConfig {
    id: string;
    name: string;
    role: string;
    description: string;
    avatar: string;
    // [Removed] nodes list is no longer needed
    /** Optional: Custom status derivation logic */
    getStatus?: (baseStatus: AgentStatus, hasTickerInterrupt?: boolean, hasApprovalInterrupt?: boolean) => AgentStatus;
}

/**
 * Complete agent configuration registry
 */
export const AGENT_CONFIGS: AgentConfig[] = [
    {
        id: 'intent_extraction',
        name: 'Intent Planner',
        role: 'Strategy & Goal Setting',
        description: 'Extracts intent and resolves ticker from user query.',
        avatar: 'https://api.dicebear.com/7.x/avataaars/svg?seed=Intent',
        getStatus: (baseStatus, hasTickerInterrupt) =>
            hasTickerInterrupt ? 'attention' : baseStatus,
    },
    {
        id: 'fundamental_analysis',
        name: 'Fundamental Analyst',
        role: 'Financial Health',
        description: 'Fetches financial data and selects valuation model.',
        avatar: 'https://api.dicebear.com/7.x/avataaars/svg?seed=Felix',
    },
    {
        id: 'technical_analysis',
        name: 'Technical Analyst',
        role: 'QUANTITATIVE SIGNALS',
        description: 'Analyzes price action using Fractional Differentiation.',
        avatar: 'https://api.dicebear.com/7.x/avataaars/svg?seed=Tech',
    },
    {
        id: 'financial_news_research',
        name: 'Financial News',
        role: 'MARKET SENTIMENT ANALYSIS',
        description: 'Researches recent news and developments for the company.',
        avatar: 'https://api.dicebear.com/7.x/avataaars/svg?seed=News',
    },
    {
        id: 'debate',
        name: 'Debate Arena',
        role: 'ADVERSARIAL REASONING',
        description: 'Bull vs Bear debate to scrutinize the investment thesis.',
        avatar: 'https://api.dicebear.com/7.x/avataaars/svg?seed=Arena',
    },
    {
        id: 'executor',
        name: 'Data Executor',
        role: 'MARKET DATA RETRIEVAL',
        description: 'Executes tools to fetch real-time financial data.',
        avatar: 'https://api.dicebear.com/7.x/avataaars/svg?seed=Aneka',
    },
    {
        id: 'auditor',
        name: 'Risk Auditor',
        role: 'COMPLIANCE & VALIDATION',
        description: 'Audits data integrity and checks for anomalies.',
        avatar: 'https://api.dicebear.com/7.x/avataaars/svg?seed=Liam',
    },
    {
        id: 'approval',
        name: 'Chief Auditor',
        role: 'FINAL DECISION AUTHORITY',
        description: 'Manages human-in-the-loop approvals.',
        avatar: 'https://api.dicebear.com/7.x/avataaars/svg?seed=Sasha',
        getStatus: (baseStatus, _, hasApprovalInterrupt) =>
            hasApprovalInterrupt ? 'attention' : baseStatus,
    },
    {
        id: 'calculator',
        name: 'Valuation Engine',
        role: 'DCF & MODEL EXECUTION',
        description: 'Performs finalized financial calculations.',
        avatar: 'https://api.dicebear.com/7.x/avataaars/svg?seed=Coco',
    },
];

/**
 * Utility: Get agent config by ID
 */
export function getAgentConfig(agentId: string): AgentConfig | undefined {
    return AGENT_CONFIGS.find(a => a.id === agentId);
}
