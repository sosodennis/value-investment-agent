import type { ReactNode } from 'react';
import { Card, CardContent } from '@/components/ui/card';
import {
    DebateOutput,
} from './outputs/debate/DebateOutput';
import {
    FundamentalAnalysisOutput,
} from './outputs/fundamental-analysis/FundamentalAnalysisOutput';
import {
    GenericAgentOutput,
} from './outputs/shared/GenericAgentOutput';
import {
    NewsResearchOutput as NewsResearchOutputPanel,
} from './outputs/news/NewsResearchOutput';
import {
    TechnicalAnalysisOutput,
} from './outputs/technical-analysis/TechnicalAnalysisOutput';
import { adaptAgentOutput } from '@/types/agents/output-adapter';
import type { AgentInfo, AgentStatus, StandardAgentOutput } from '@/types/agents';

type WorkspaceOutputPanelProps = {
    agent: AgentInfo;
    output: StandardAgentOutput | null;
    resolvedTicker?: string | null;
    status: AgentStatus;
};

export function WorkspaceOutputPanel({
    agent,
    output,
    resolvedTicker,
    status,
}: WorkspaceOutputPanelProps) {
    const viewModel = adaptAgentOutput(
        agent.id,
        output,
        `workspace_output.${agent.id}`
    );

    let report: ReactNode;
    switch (viewModel.kind) {
        case 'fundamental_analysis':
            report = (
                <FundamentalAnalysisOutput
                    reference={viewModel.reference}
                    previewData={viewModel.preview}
                    resolvedTicker={resolvedTicker}
                    status={status}
                />
            );
            break;
        case 'financial_news_research':
            report = (
                <NewsResearchOutputPanel
                    reference={viewModel.reference}
                    previewData={viewModel.preview}
                    resolvedTicker={resolvedTicker}
                    status={status}
                />
            );
            break;
        case 'debate':
            report = (
                <DebateOutput
                    reference={viewModel.reference}
                    previewData={viewModel.preview}
                    resolvedTicker={resolvedTicker}
                    status={status}
                />
            );
            break;
        case 'technical_analysis':
            report = (
                <TechnicalAnalysisOutput
                    reference={viewModel.reference}
                    previewData={viewModel.preview}
                    status={status}
                />
            );
            break;
        case 'generic':
            report = (
                <GenericAgentOutput
                    agentName={agent.name}
                    viewModel={viewModel}
                    status={status}
                />
            );
            break;
        default: {
            const unreachable: never = viewModel;
            return unreachable;
        }
    }

    return (
        <div className="grid gap-4">
            {viewModel.summary ? (
                <Card className="border">
                    <CardContent className="pt-4 text-sm leading-6 text-muted-foreground">
                        {viewModel.summary}
                    </CardContent>
                </Card>
            ) : null}
            {report}
        </div>
    );
}
