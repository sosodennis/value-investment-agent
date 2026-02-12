import React, { memo } from 'react';
import { Zap, TrendingUp } from 'lucide-react';
import { NewsResearchCard } from '../NewsResearchCard';
import { AINewsSummary } from '../AINewsSummary';
import { NewsResearchOutput as NewsResearchOutputType } from '@/types/agents/news';
import { StandardAgentOutput, AgentStatus } from '@/types/agents';
import { useArtifact } from '../../hooks/useArtifact';
import { AgentLoadingState } from './AgentLoadingState';
import { NewsPreview, isNewsPreview } from '@/types/preview';

interface NewsResearchOutputProps {
    output: StandardAgentOutput | null;
    resolvedTicker: string | null | undefined;
    status: AgentStatus;
}

const NewsResearchOutputComponent: React.FC<NewsResearchOutputProps> = ({
    output,
    resolvedTicker,
    status
}) => {
    const reference = output?.reference;
    const preview = output?.preview;
    const previewData: NewsPreview | null = isNewsPreview(preview) ? preview : null;

    const { data: artifactData, isLoading: isArtifactLoading } = useArtifact<NewsResearchOutputType>(
        reference?.artifact_id
    );

    const effectiveOutput = artifactData || previewData;

    const isPreviewOnly = !artifactData && !!previewData;
    const hasData = effectiveOutput && (
        (artifactData?.news_items && artifactData.news_items.length > 0) ||
        typeof artifactData?.sentiment_score === 'number' ||
        isPreviewOnly
    );

    // Wait for completion before showing data, unless we have preview data
    if ((status !== 'done' && !hasData) || !effectiveOutput) {
        return (
            <AgentLoadingState
                type="full"
                icon={TrendingUp}
                title="Searching News..."
                description={`Our agents are scanning global financial news for ${resolvedTicker || 'the target company'}. Results will appear here shortly.`}
                status={status}
                colorClass="text-cyan-400"
            />
        );
    }

    // Checking if we are in "Preview Mode" (Artifact loading, but we have data)
    const isReferenceLoading = reference && isArtifactLoading && !artifactData;

    return (
        <div className="space-y-8 pb-12">
            <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-3">
                    <Zap size={18} className="text-amber-400" />
                    <h3 className="text-sm font-bold text-white uppercase tracking-widest">News Research Intelligence</h3>
                </div>
                {isReferenceLoading && (
                    <AgentLoadingState
                        type="header"
                        title="Loading Full Report..."
                        colorClass="text-amber-400"
                    />
                )}
            </div>

            {/* Main Summary - Handles both Preview (checking inside component for missing items) and Full Data */}
            <AINewsSummary output={effectiveOutput} />

            <div className="space-y-4">
                <div className="flex items-center gap-3 mb-4">
                    <TrendingUp size={16} className="text-cyan-400" />
                    <h3 className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Article Breakdown</h3>
                </div>

                {artifactData?.news_items && artifactData.news_items.length > 0 ? (
                    <div className="grid grid-cols-1 gap-6">
                        {artifactData.news_items.map((item) => (
                            <NewsResearchCard key={item.id} item={item} />
                        ))}
                    </div>
                ) : isPreviewOnly && previewData?.top_headlines ? (
                    <div className="space-y-4">
                        <div className="p-4 bg-slate-900/40 border border-slate-800 rounded-xl">
                            <h4 className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-3">Recent Headlines (Preview)</h4>
                            <div className="space-y-2">
                                {previewData.top_headlines.map((headline: string, i: number) => (
                                    <div key={i} className="flex gap-2 text-xs text-slate-300">
                                        <div className="w-1 h-1 bg-cyan-500 rounded-full mt-1.5 shrink-0" />
                                        <span>{headline}</span>
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>
                ) : (
                    <AgentLoadingState
                        type="block"
                        title={isReferenceLoading ? "Loading articles..." : "No articles found."}
                        colorClass="text-cyan-400"
                    />
                )}

            </div>
        </div>
    );
};

// Export with React.memo for performance optimization
export const NewsResearchOutput = memo(NewsResearchOutputComponent);
