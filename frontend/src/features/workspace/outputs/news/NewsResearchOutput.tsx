import React, { memo } from 'react';
import { Zap, TrendingUp } from 'lucide-react';
import { NewsResearchCard } from './NewsResearchCard';
import { AINewsSummary } from './AINewsSummary';
import { parseNewsArtifact } from '@/types/agents/artifact-parsers';
import { ArtifactReference, AgentStatus } from '@/types/agents';
import { useArtifact } from '../../../../hooks/useArtifact';
import { AgentLoadingState } from '../shared/AgentLoadingState';
import { NewsPreview } from '@/types/preview';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Card } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';

interface NewsResearchOutputProps {
    reference: ArtifactReference | null;
    previewData: NewsPreview | null;
    resolvedTicker: string | null | undefined;
    status: AgentStatus;
}

const NewsResearchOutputComponent: React.FC<NewsResearchOutputProps> = ({
    reference,
    previewData,
    resolvedTicker,
    status
}) => {
    const { data: artifactData, isLoading: isArtifactLoading, error: artifactError } = useArtifact(
        reference,
        parseNewsArtifact,
        'news_output.artifact',
        'news_analysis_report'
    );

    const effectiveOutput = artifactData || previewData;

    const isPreviewOnly = !artifactData && !!previewData;
    const hasData = effectiveOutput && (
        (artifactData?.news_items && artifactData.news_items.length > 0) ||
        typeof artifactData?.sentiment_score === 'number' ||
        isPreviewOnly
    );

    // Wait for completion before showing data, unless we have preview data
    if (artifactError && !effectiveOutput) {
        return (
            <Alert variant="destructive" role="alert">
                <AlertTitle>News report unavailable</AlertTitle>
                <AlertDescription>{artifactError.message}</AlertDescription>
            </Alert>
        );
    }

    if (status === 'error' && !effectiveOutput) {
        return (
            <Alert variant="destructive" role="alert">
                <AlertTitle>News research failed</AlertTitle>
                <AlertDescription>The agent ended before producing news research data.</AlertDescription>
            </Alert>
        );
    }

    if ((status !== 'done' && !hasData) || (!effectiveOutput && isArtifactLoading)) {
        return (
            <AgentLoadingState
                type="full"
                icon={TrendingUp}
                title="Searching News…"
                description={`Our agents are scanning global financial news for ${resolvedTicker || 'the target company'}. Results will appear here shortly.`}
                status={status}

            />
        );
    }

    if (!effectiveOutput) {
        return (
            <EmptyState
                icon={<TrendingUp aria-hidden="true" />}
                title="No news research available"
                description="The completed run did not include a news research report."
            />
        );
    }

    // Checking if we are in "Preview Mode" (Artifact loading, but we have data)
    const isReferenceLoading = reference && isArtifactLoading && !artifactData;

    return (
        <div className="space-y-8 pb-12 ">
            <div className="flex items-center justify-between mb-6 px-2">
                <div className="flex items-center gap-3">
                    <Zap size={18} className="text-warning" />
                    <h3 className="text-xs font-bold text-muted-foreground uppercase tracking-[0.2em]">News Research Intelligence</h3>
                </div>
                {isReferenceLoading && (
                    <AgentLoadingState
                        type="header"
                        title="Loading Full Report…"

                    />
                )}
            </div>

            {artifactError && isPreviewOnly && (
                <Alert variant="destructive" role="alert">
                    <AlertTitle>Full news report unavailable</AlertTitle>
                    <AlertDescription>
                        Showing the available preview. {artifactError.message}
                    </AlertDescription>
                </Alert>
            )}

            {/* Main Summary - Handles both Preview (checking inside component for missing items) and Full Data */}
            <AINewsSummary output={effectiveOutput} />

            <div className="space-y-4">
                <div className="flex items-center gap-3 mb-4">
                    <TrendingUp size={16} className="text-primary" />
                    <h3 className="text-[10px] font-bold text-muted-foreground uppercase tracking-[0.2em]">Article Breakdown</h3>
                </div>

                {artifactData?.news_items && artifactData.news_items.length > 0 ? (
                    <div className="grid grid-cols-1 gap-6">
                        {artifactData.news_items.map((item) => (
                            <NewsResearchCard key={item.id} item={item} />
                        ))}
                    </div>
                ) : isPreviewOnly && previewData?.top_headlines ? (
                    <div className="space-y-4">
                        <Card className="space-y-3 bg-muted/50 p-5">
                            <h4 className="text-[10px] font-bold text-muted-foreground uppercase tracking-[0.2em] mb-3">Recent Headlines (Preview)</h4>
                            <div className="space-y-2">
                                {previewData.top_headlines.map((headline: string, i: number) => (
                                    <div key={i} className="flex gap-2 text-xs text-muted-foreground">
                                        <div className="w-1 h-1 bg-primary rounded-full mt-1.5 shrink-0" />
                                        <span>{headline}</span>
                                    </div>
                                ))}
                            </div>
                        </Card>
                    </div>
                ) : (
                <EmptyState
                    className="border-border/30 bg-muted/20 px-4 py-6"
                    icon={<TrendingUp aria-hidden="true" />}
                    title={isReferenceLoading ? 'Loading articles' : 'No articles found'}
                    description={isReferenceLoading
                        ? 'The full article list is still loading.'
                        : 'No article records were included in this report.'}
                />
                )}

            </div>
        </div>
    );
};

// Export with React.memo for performance optimization
export const NewsResearchOutput = memo(NewsResearchOutputComponent);
