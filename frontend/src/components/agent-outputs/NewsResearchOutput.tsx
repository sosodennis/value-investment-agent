import React, { memo } from 'react';
import { Zap, TrendingUp, Loader2 } from 'lucide-react';
import { NewsResearchCard } from '../NewsResearchCard';
import { AINewsSummary } from '../AINewsSummary';
import { NewsResearchOutput as NewsResearchOutputType } from '@/types/agents/news';
import { StandardAgentOutput, AgentStatus } from '@/types/agents';
import { useArtifact } from '../../hooks/useArtifact';

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
    // 1. Determine if we have a reference to fetch
    const reference = (output as StandardAgentOutput)?.reference;
    const preview = (output as StandardAgentOutput)?.preview as NewsResearchOutputType | undefined;

    // 2. Fetch artifact if reference exists
    const { data: artifactData, isLoading: isArtifactLoading } = useArtifact<NewsResearchOutputType>(
        reference?.artifact_id
    );

    // 3. Resolve the actual data to display (Artifact > Preview)
    // Legacy fallback to 'output' itself is removed.
    const effectiveOutput = artifactData || preview;

    // 4. Check if we have valid data to show
    const hasData = effectiveOutput && (
        (effectiveOutput.news_items && effectiveOutput.news_items.length > 0) ||
        typeof effectiveOutput.sentiment_score === 'number'
    );

    // Wait for completion before showing data, unless we have preview data
    if ((status !== 'done' && !hasData) || !effectiveOutput) {
        return (
            <div className="flex-1 flex flex-col items-center justify-center p-12 text-center h-full">
                <TrendingUp size={48} className="text-slate-900 mb-4" />
                <h4 className="text-slate-500 font-bold text-xs uppercase tracking-widest">Searching News...</h4>
                <p className="text-slate-700 text-[10px] mt-2 max-w-[240px]">
                    Our agents are scanning global financial news for {resolvedTicker || 'the target company'}. Results will appear here shortly.
                </p>
                <p className="text-[10px] text-slate-500 mt-2">Status: {status}</p>
            </div>
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
                    <div className="flex items-center gap-2 text-[10px] text-amber-400 font-bold uppercase tracking-widest animate-pulse">
                        <Loader2 size={12} className="animate-spin" />
                        <span>Loading Full Report...</span>
                    </div>
                )}
            </div>

            {/* Main Summary - Handles both Preview (checking inside component for missing items) and Full Data */}
            <AINewsSummary output={effectiveOutput} />

            <div className="space-y-4">
                <div className="flex items-center gap-3 mb-4">
                    <TrendingUp size={16} className="text-cyan-400" />
                    <h3 className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Article Breakdown</h3>
                </div>

                {effectiveOutput.news_items && effectiveOutput.news_items.length > 0 ? (
                    <div className="grid grid-cols-1 gap-6">
                        {effectiveOutput.news_items.map((item) => (
                            <NewsResearchCard key={item.id} item={item} />
                        ))}
                    </div>
                ) : (
                    <div className="p-8 border border-slate-800 rounded-xl bg-slate-900/30 text-center">
                        <p className="text-slate-500 text-xs italic">
                            {isReferenceLoading ? "Loading articles..." : "No articles found."}
                        </p>
                    </div>
                )}

            </div>
        </div>
    );
};

// Export with React.memo for performance optimization
export const NewsResearchOutput = memo(NewsResearchOutputComponent);
