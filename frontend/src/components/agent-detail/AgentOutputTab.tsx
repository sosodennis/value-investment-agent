import React from 'react';
import { AgentInfo, AgentStatus, StandardAgentOutput } from '@/types/agents';
import { adaptAgentOutput } from '@/types/agents/output-adapter';
import { FundamentalAnalysisOutput } from '../agent-outputs/FundamentalAnalysisOutput';
import { NewsResearchOutput as NewsResearchOutputPanel } from '../agent-outputs/NewsResearchOutput';
import { GenericAgentOutput } from '../agent-outputs/GenericAgentOutput';
import { DebateOutput } from '../agent-outputs/DebateOutput';
import { TechnicalAnalysisOutput } from '../agent-outputs/TechnicalAnalysisOutput';

interface AgentOutputTabProps {
    agent: AgentInfo;
    rawOutput: StandardAgentOutput | null;
    resolvedTicker?: string | null;
    status: AgentStatus;
}

export const AgentOutputTab: React.FC<AgentOutputTabProps> = ({
    agent,
    rawOutput,
    resolvedTicker,
    status
}) => {
    const viewModel = adaptAgentOutput(
        agent.id,
        rawOutput,
        `agent_output_tab.${agent.id}`
    );

    const renderOutput = () => {
        switch (viewModel.kind) {
            case 'fundamental_analysis':
                return (
                    <FundamentalAnalysisOutput
                        reference={viewModel.reference}
                        previewData={viewModel.preview}
                        resolvedTicker={resolvedTicker}
                        status={status}
                    />
                );
            case 'financial_news_research':
                return (
                    <NewsResearchOutputPanel
                        reference={viewModel.reference}
                        previewData={viewModel.preview}
                        resolvedTicker={resolvedTicker}
                        status={status}
                    />
                );
            case 'debate':
                return (
                    <DebateOutput
                        reference={viewModel.reference}
                        previewData={viewModel.preview}
                        resolvedTicker={resolvedTicker}
                        status={status}
                    />
                );
            case 'technical_analysis':
                return (
                    <TechnicalAnalysisOutput
                        reference={viewModel.reference}
                        previewData={viewModel.preview}
                        status={status}
                    />
                );
            case 'generic':
                return (
                    <GenericAgentOutput
                        agentName={agent.name}
                        viewModel={viewModel}
                        status={status}
                    />
                );
            default: {
                const unreachableKind: never = viewModel;
                return unreachableKind;
            }
        }
    };

    return (
        <div className="p-8 h-full animate-in slide-in-from-bottom-2 duration-300 overflow-y-auto custom-scrollbar">
            {renderOutput()}
        </div>
    );
};
