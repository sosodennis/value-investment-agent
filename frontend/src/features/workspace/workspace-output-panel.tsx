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
import { buildEvidenceItems, type EvidenceSelection } from './workspace-evidence-inspector';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/cn';
import type { InteractionResponse, WorkflowInteraction } from '@/features/workflow';
import { FundamentalReviewPanel } from './outputs/fundamental-analysis/FundamentalReviewPanel';
import type {
    ForwardEvidenceManualOverride,
    ForwardEvidenceResearchRequest,
    ForwardEvidenceReview,
} from './outputs/fundamental-analysis/forward-evidence-api';

type WorkspaceOutputPanelProps = {
    agent: AgentInfo;
    output: StandardAgentOutput | null;
    resolvedTicker?: string | null;
    status: AgentStatus;
    onSelectEvidence?: (item: EvidenceSelection) => void;
    selectedEvidenceId?: string | null;
    pendingApproval?: Extract<WorkflowInteraction, { kind: 'valuation_approval' }> | null;
    onResumeInteraction?: (interaction: WorkflowInteraction, response: InteractionResponse) => Promise<void>;
    isSubmitting?: boolean;
    onRecalculate?: (manualOverride: Record<string, unknown>) => void;
    forwardEvidence?: ForwardEvidenceReview | null;
    isResearchingForwardEvidence?: boolean;
    researchError?: string | null;
    onResearchForwardEvidence?: (request: ForwardEvidenceResearchRequest) => Promise<void>;
    onApplyForwardEvidence?: (override: ForwardEvidenceManualOverride) => void;
};

export function WorkspaceOutputPanel({
    agent,
    output,
    resolvedTicker,
    status,
    onSelectEvidence,
    selectedEvidenceId,
    pendingApproval = null,
    onResumeInteraction,
    isSubmitting = false,
    onRecalculate,
    forwardEvidence = null,
    isResearchingForwardEvidence = false,
    researchError = null,
    onResearchForwardEvidence,
    onApplyForwardEvidence,
}: WorkspaceOutputPanelProps) {
    const viewModel = adaptAgentOutput(
        agent.id,
        output,
        `workspace_output.${agent.id}`
    );

    let report: ReactNode;
    if (agent.id === 'fundamental_analysis' && pendingApproval && !output) {
        return (
            <FundamentalReviewPanel
                pendingApproval={pendingApproval}
                onResumeInteraction={onResumeInteraction}
                isSubmitting={isSubmitting}
                onRecalculate={onRecalculate}
            />
        );
    }
    switch (viewModel.kind) {
        case 'fundamental_analysis':
            report = (
                <FundamentalAnalysisOutput
                    reference={viewModel.reference}
                    previewData={viewModel.preview}
                    resolvedTicker={resolvedTicker}
                    status={status}
                onSelectEvidence={onSelectEvidence}
                pendingApproval={pendingApproval}
                onResumeInteraction={onResumeInteraction}
                isSubmitting={isSubmitting}
                onRecalculate={onRecalculate}
                    forwardEvidence={forwardEvidence}
                    isResearchingForwardEvidence={isResearchingForwardEvidence}
                    researchError={researchError}
                    onResearchForwardEvidence={onResearchForwardEvidence}
                    onApplyForwardEvidence={onApplyForwardEvidence}
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

    const evidenceItems = buildEvidenceItems(agent, viewModel);

    return (
        <div className="grid min-w-0 grid-cols-1 gap-4">
            {viewModel.summary ? (
                <Card className="border">
                    <CardContent className="pt-4 text-sm leading-6 text-muted-foreground">
                        {viewModel.summary}
                    </CardContent>
                </Card>
            ) : null}
            {onSelectEvidence && evidenceItems.length > 0 ? (
                <section aria-label="Report evidence" className="border-y py-3">
                    <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
                        <h3 className="text-sm font-semibold">Report evidence</h3>
                        <p className="text-xs text-muted-foreground">Select a value to inspect its source and period.</p>
                    </div>
                    <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                        {evidenceItems.map((item) => (
                            <Button
                                key={item.id}
                                type="button"
                                variant="ghost"
                                className={cn(
                                    'h-auto min-w-0 justify-start border border-border/60 px-3 py-2 text-left whitespace-normal',
                                    selectedEvidenceId === item.id && 'border-primary bg-accent',
                                )}
                                onClick={() => onSelectEvidence(item)}
                            >
                                <span className="min-w-0">
                                    <span className="block truncate text-xs font-semibold">{item.title}</span>
                                    <span className="mt-1 block break-words font-mono text-xs text-muted-foreground">{item.value}</span>
                                </span>
                            </Button>
                        ))}
                    </div>
                </section>
            ) : null}
            <div className="min-w-0">{report}</div>
        </div>
    );
}
