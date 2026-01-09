import React from 'react';
import { ExternalLink, Calendar, Tag, AlertCircle, Info, TrendingUp, TrendingDown, Minus } from 'lucide-react';
import { FinancialNewsItem, SentimentLabel, ImpactLevel } from '../types/news';

interface NewsResearchCardProps {
    item: FinancialNewsItem;
}

export const NewsResearchCard: React.FC<NewsResearchCardProps> = ({ item }) => {
    const getSentimentColor = (sentiment: SentimentLabel) => {
        switch (sentiment) {
            case 'bullish': return 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20';
            case 'bearish': return 'text-rose-400 bg-rose-500/10 border-rose-500/20';
            case 'neutral': return 'text-slate-400 bg-slate-500/10 border-slate-500/20';
            default: return 'text-slate-400 bg-slate-500/10 border-slate-500/20';
        }
    };

    const getSentimentIcon = (sentiment: SentimentLabel) => {
        switch (sentiment) {
            case 'bullish': return <TrendingUp size={12} />;
            case 'bearish': return <TrendingDown size={12} />;
            case 'neutral': return <Minus size={12} />;
            default: return <Minus size={12} />;
        }
    };

    const getImpactColor = (impact: ImpactLevel) => {
        switch (impact) {
            case 'high': return 'text-rose-500';
            case 'medium': return 'text-amber-500';
            case 'low': return 'text-cyan-500';
            default: return 'text-slate-500';
        }
    };

    const formatDate = (dateStr?: string | null) => {
        if (!dateStr) return 'Unknown date';
        return new Date(dateStr).toLocaleDateString([], {
            month: 'short',
            day: 'numeric',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    };

    return (
        <div className="bg-slate-900/20 border border-slate-800/50 rounded-2xl p-6 backdrop-blur-sm hover:border-slate-700/50 transition-all group">
            <div className="flex justify-between items-start mb-4">
                <div className="flex flex-col gap-1">
                    <div className="flex items-center gap-2">
                        <span className="text-[10px] font-bold text-cyan-500 uppercase tracking-widest">
                            {item.source.name}
                        </span>
                        <div className="w-1 h-1 bg-slate-800 rounded-full" />
                        <div className="flex items-center gap-1 text-[9px] text-slate-500 font-medium">
                            <Calendar size={10} />
                            {formatDate(item.published_at)}
                        </div>
                    </div>
                    {item.source.author && (
                        <span className="text-[9px] text-slate-600 font-medium">By {item.source.author}</span>
                    )}
                </div>

                <div className="flex items-center gap-2">
                    <div className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-[10px] font-bold uppercase tracking-tighter ${getSentimentColor(item.analysis?.sentiment || 'neutral')}`}>
                        {getSentimentIcon(item.analysis?.sentiment || 'neutral')}
                        {item.analysis?.sentiment || 'neutral'}
                    </div>
                </div>
            </div>

            <a
                href={item.url}
                target="_blank"
                rel="noopener noreferrer"
                className="block group-hover:text-cyan-400 transition-colors mb-3"
            >
                <h3 className="text-sm font-bold text-white leading-tight flex items-center gap-2">
                    {item.title}
                    <ExternalLink size={12} className="opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
                </h3>
            </a>

            <p className="text-xs text-slate-400 leading-relaxed mb-4 line-clamp-3">
                {item.snippet}
            </p>

            {item.analysis && (
                <div className="bg-slate-950/40 border border-slate-800/80 rounded-xl p-4 space-y-3 mb-4">
                    <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                            <Info size={12} className="text-cyan-500" />
                            <span className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">AI Analysis</span>
                        </div>
                        <div className="flex items-center gap-2">
                            <span className="text-[9px] text-slate-500 font-bold uppercase">Impact</span>
                            <span className={`text-[10px] font-bold uppercase ${getImpactColor(item.analysis.impact_level)}`}>
                                {item.analysis.impact_level}
                            </span>
                        </div>
                    </div>

                    <div className="text-xs text-slate-300 leading-relaxed italic">
                        &quot;{item.analysis.summary}&quot;
                    </div>

                    {item.analysis.key_event && (
                        <div className="flex items-start gap-2 pt-2 border-t border-slate-900">
                            <AlertCircle size={12} className="text-amber-500 mt-0.5 shrink-0" />
                            <div>
                                <div className="text-[9px] text-slate-500 font-bold uppercase tracking-tight">Key Event</div>
                                <div className="text-[11px] text-slate-200 font-medium">{item.analysis.key_event}</div>
                            </div>
                        </div>
                    )}

                    <div className="text-[10px] text-slate-500 leading-relaxed">
                        <span className="font-bold uppercase tracking-tighter text-slate-600 mr-1">Reasoning:</span>
                        {item.analysis.reasoning}
                    </div>
                </div>
            )}

            <div className="flex flex-wrap gap-2 items-center">
                {item.tags.map(tag => (
                    <div key={tag} className="flex items-center gap-1 bg-slate-900/50 border border-slate-800 px-2 py-0.5 rounded text-[9px] text-slate-400 font-medium uppercase tracking-tighter">
                        <Tag size={8} />
                        {tag}
                    </div>
                ))}

                {item.related_tickers.length > 0 && (
                    <div className="ml-auto flex -space-x-1.5">
                        {item.related_tickers.map(entity => (
                            <div
                                key={entity.ticker}
                                title={`${entity.company_name} (${(entity.relevance_score * 100).toFixed(0)}% relevance)`}
                                className="w-6 h-6 rounded-full bg-slate-800 border-2 border-slate-950 flex items-center justify-center text-[8px] font-bold text-cyan-400 hover:z-10 transition-all cursor-help"
                            >
                                {entity.ticker.substring(0, 2)}
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
};
