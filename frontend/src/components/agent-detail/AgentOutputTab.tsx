import React from 'react';
import { AgentInfo, AgentStatus } from '@/types/agents';
import {
    FundamentalAnalysisOutput,
    NewsResearchOutput as NewsResearchOutputPanel,
    GenericAgentOutput,
    DebateOutput,
    TechnicalAnalysisOutput
} from '../agent-outputs';

interface AgentOutputTabProps {
    agent: AgentInfo;
    rawOutput: any;
    resolvedTicker?: string;
    status: AgentStatus;
}

export const AgentOutputTab: React.FC<AgentOutputTabProps> = ({
    agent,
    rawOutput,
    resolvedTicker,
    status
}) => {
    return (
        <div className="p-8 h-full animate-in slide-in-from-bottom-2 duration-300">
            {agent.id === 'fundamental_analysis' ? (
                <FundamentalAnalysisOutput
                    output={rawOutput}
                    resolvedTicker={resolvedTicker}
                    status={status}
                />
            ) : agent.id === 'financial_news_research' ? (
                <NewsResearchOutputPanel
                    output={rawOutput}
                    resolvedTicker={resolvedTicker}
                    status={status}
                />
            ) : agent.id === 'debate' ? ( // Fixed: Use explicit ID check
                <DebateOutput
                    output={rawOutput}
                    resolvedTicker={resolvedTicker}
                    status={status}
                />
            ) : agent.id === 'technical_analysis' ? (
                <TechnicalAnalysisOutput
                    output={rawOutput}
                    status={status}
                />
            ) : (
                <GenericAgentOutput
                    agentName={agent.name}
                    output={rawOutput}
                    status={status}
                />
            )}
        </div>
    );
};
