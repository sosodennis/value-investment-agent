/**
 * Centralized Agent Configuration
 *
 * This file serves as the single source of truth for all agent metadata,
 * node mappings, and UI configuration. Following the DRY principle.
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
    /** Internal node names that belong to this agent */
    nodes: string[];
    /** Optional: Custom status derivation logic */
    getStatus?: (baseStatus: AgentStatus, hasTickerInterrupt?: boolean, hasApprovalInterrupt?: boolean) => AgentStatus;
}

/**
 * Complete agent configuration registry
 * This is the SINGLE SOURCE OF TRUTH for all agent metadata
 */
export const AGENT_CONFIGS: AgentConfig[] = [
    {
        id: 'intent_extraction',
        name: 'Intent Planner',
        role: 'Strategy & Goal Setting',
        description: 'Extracts intent and resolves ticker from user query.',
        avatar: 'https://api.dicebear.com/7.x/avataaars/svg?seed=Intent',
        nodes: ['extraction', 'searching', 'deciding', 'clarifying', 'intent_extraction', 'intent_agent', 'prepare_intent', 'process_intent'],
        getStatus: (baseStatus, hasTickerInterrupt) =>
            hasTickerInterrupt ? 'attention' : baseStatus,
    },
    {
        id: 'fundamental_analysis',
        name: 'Fundamental Analyst',
        role: 'Financial Health',
        description: 'Fetches financial data and selects valuation model.',
        avatar: 'https://api.dicebear.com/7.x/avataaars/svg?seed=Felix',
        nodes: ['financial_health', 'model_selection', 'fundamental_analysis', 'fundamental_agent', 'prepare_fundamental', 'process_fundamental'],
    },
    {
        id: 'technical_analysis',
        name: 'Technical Analyst',
        role: 'QUANTITATIVE SIGNALS',
        description: 'Analyzes price action using Fractional Differentiation.',
        avatar: 'https://api.dicebear.com/7.x/avataaars/svg?seed=Tech',
        nodes: ['data_fetch', 'fracdiff_compute', 'semantic_translate', 'technical_analysis', 'technical_agent', 'prepare_technical', 'process_technical'],
    },
    {
        id: 'financial_news_research',
        name: 'Financial News',
        role: 'MARKET SENTIMENT ANALYSIS',
        description: 'Researches recent news and developments for the company.',
        avatar: 'https://api.dicebear.com/7.x/avataaars/svg?seed=News',
        nodes: ['search_node', 'selector_node', 'fetch_node', 'analyst_node', 'aggregator_node', 'financial_news_research', 'news_agent', 'prepare_news', 'process_news'],
    },
    {
        id: 'debate',
        name: 'Debate Arena',
        role: 'ADVERSARIAL REASONING',
        description: 'Bull vs Bear debate to scrutinize the investment thesis.',
        avatar: 'https://api.dicebear.com/7.x/avataaars/svg?seed=Arena',
        nodes: ['debate_aggregator', 'r1_bull', 'r1_bear', 'r1_moderator', 'r2_bull', 'r2_bear', 'r2_moderator', 'r3_bull', 'r3_bear', 'verdict', 'debate_agent', 'prepare_debate', 'process_debate'],
    },
    {
        id: 'executor',
        name: 'Data Executor',
        role: 'MARKET DATA RETRIEVAL',
        description: 'Executes tools to fetch real-time financial data.',
        avatar: 'https://api.dicebear.com/7.x/avataaars/svg?seed=Aneka',
        nodes: ['executor'],
    },
    {
        id: 'auditor',
        name: 'Risk Auditor',
        role: 'COMPLIANCE & VALIDATION',
        description: 'Audits data integrity and checks for anomalies.',
        avatar: 'https://api.dicebear.com/7.x/avataaars/svg?seed=Liam',
        nodes: ['auditor'],
    },
    {
        id: 'approval',
        name: 'Chief Auditor',
        role: 'FINAL DECISION AUTHORITY',
        description: 'Manages human-in-the-loop approvals.',
        avatar: 'https://api.dicebear.com/7.x/avataaars/svg?seed=Sasha',
        nodes: ['approval'],
        getStatus: (baseStatus, _, hasApprovalInterrupt) =>
            hasApprovalInterrupt ? 'attention' : baseStatus,
    },
    {
        id: 'calculator',
        name: 'Valuation Engine',
        role: 'DCF & MODEL EXECUTION',
        description: 'Performs finalized financial calculations.',
        avatar: 'https://api.dicebear.com/7.x/avataaars/svg?seed=Coco',
        nodes: ['calculator'],
    },
];

/**
 * Utility: Get agent config by ID
 */
export function getAgentConfig(agentId: string): AgentConfig | undefined {
    return AGENT_CONFIGS.find(a => a.id === agentId);
}

/**
 * Utility: Get agent ID from node name
 * This is used to map internal node names to their parent agent
 */
export function getAgentIdFromNode(nodeName: string): string | undefined {
    const cleanNode = nodeName.toLowerCase().split(':').pop() || nodeName.toLowerCase();

    for (const agent of AGENT_CONFIGS) {
        if (agent.nodes.includes(cleanNode)) {
            return agent.id;
        }
    }

    return undefined;
}

/**
 * Utility: Check if a node belongs to an agent
 */
export function nodeMatchesAgent(nodeName: string, agentId: string): boolean {
    const cleanNode = nodeName.toLowerCase().split(':').pop() || nodeName.toLowerCase();
    const config = getAgentConfig(agentId);
    return config ? config.nodes.includes(cleanNode) : false;
}

/**
 * Utility: Create node-to-agent mapping (for useAgent.ts)
 * Returns a Record<nodeName, agentId>
 */
export function createNodeToAgentMap(): Record<string, string> {
    const map: Record<string, string> = {};

    for (const agent of AGENT_CONFIGS) {
        for (const node of agent.nodes) {
            map[node] = agent.id;
        }
    }

    return map;
}
