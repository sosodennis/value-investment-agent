import React, { memo } from 'react';
import { Zap, TrendingUp } from 'lucide-react';
import { NewsResearchCard } from '../NewsResearchCard';
import { AINewsSummary } from '../AINewsSummary';
import { NewsResearchOutput as NewsResearchOutputType } from '@/types/agents/news';

import { AgentStatus } from '@/types/agents';

interface NewsResearchOutputProps {
    output: NewsResearchOutputType | null;
    resolvedTicker: string | null | undefined;
    status: AgentStatus;
}

const NewsResearchOutputComponent: React.FC<NewsResearchOutputProps> = ({
    output,
    resolvedTicker,
    status
}) => {
    // Wait for completion before showing data
    if (status !== 'done' || !output || !output.news_items || output.news_items.length === 0) {
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

    return (
        <div className="space-y-8 pb-12">
            <div className="flex items-center gap-3 mb-2">
                <Zap size={18} className="text-amber-400" />
                <h3 className="text-sm font-bold text-white uppercase tracking-widest">News Research Intelligence</h3>
            </div>

            <AINewsSummary output={output} />

            <div className="space-y-4">
                <div className="flex items-center gap-3 mb-4">
                    <TrendingUp size={16} className="text-cyan-400" />
                    <h3 className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Article Breakdown</h3>
                </div>
                <div className="grid grid-cols-1 gap-6">
                    {output.news_items.map((item) => (
                        <NewsResearchCard key={item.id} item={item} />
                    ))}
                </div>
            </div>
        </div>
    );
};

// Export with React.memo for performance optimization
export const NewsResearchOutput = memo(NewsResearchOutputComponent);
