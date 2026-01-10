import React from 'react';
import { ExternalLink, Calendar, Tag, AlertCircle, Info, TrendingUp, TrendingDown, Minus, Star, BarChart3, MessageSquare } from 'lucide-react';
import { FinancialNewsItem, SentimentLabel, ImpactLevel, SearchCategory, KeyFact } from '../types/news';

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

    const getCategoryStyles = (category: SearchCategory) => {
        switch (category) {
            case 'bullish': return 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20';
            case 'bearish': return 'bg-rose-500/10 text-rose-500 border-rose-500/20';
            case 'corporate_event': return 'bg-indigo-500/10 text-indigo-500 border-indigo-500/20';
            case 'financials': return 'bg-cyan-500/10 text-cyan-500 border-cyan-500/20';
            case 'trusted_news': return 'bg-slate-500/10 text-slate-400 border-slate-500/20';
            case 'analyst_opinion': return 'bg-amber-500/10 text-amber-500 border-amber-500/20';
            default: return 'bg-slate-900/50 text-slate-500 border-slate-800';
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

    const renderReliability = (score: number) => {
        const stars = Math.round(score * 5);
        return (
            <div className="flex items-center gap-0.5" title={`Source Reliability: ${(score * 100).toFixed(0)}%`}>
                {[...Array(5)].map((_, i) => (
                    <Star
                        key={i}
                        size={8}
                        className={i < stars ? 'fill-amber-500 text-amber-500' : 'text-slate-700'}
                    />
                ))}
            </div>
        );
    };

    return (
        <div className="bg-slate-900/20 border border-slate-800/50 rounded-2xl p-6 backdrop-blur-sm hover:border-slate-700/50 transition-all group">
            <div className="flex justify-between items-start mb-4">
                <div className="flex flex-col gap-1">
                    <div className="flex items-center gap-2">
                        <span className="text-[10px] font-bold text-cyan-500 uppercase tracking-widest">
                            {item.source.name}
                        </span>
                        {renderReliability(item.source.reliability_score)}
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

            <div className="flex flex-wrap gap-1.5 mb-3">
                {item.categories.map(cat => (
                    <div key={cat} className={`px-2 py-0.5 rounded border text-[8px] font-bold uppercase tracking-tighter ${getCategoryStyles(cat)}`}>
                        {cat.replace('_', ' ')}
                    </div>
                ))}
            </div>

            <p className="text-xs text-slate-400 leading-relaxed mb-4 line-clamp-3">
                {item.snippet}
            </p>

            {item.analysis && (
                <div className="bg-slate-950/40 border border-slate-800/80 rounded-xl p-4 mb-4">
                    {/* Header */}
                    <div className="flex items-center justify-between border-b border-slate-900 pb-3 mb-4">
                        <div className="flex items-center gap-2">
                            <Info size={12} className="text-cyan-500" />
                            <span className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">AI Evidence Extraction</span>
                        </div>
                        <div className="flex items-center gap-2">
                            <span className="text-[9px] text-slate-500 font-bold uppercase">Impact</span>
                            <span className={`text-[10px] font-bold uppercase ${getImpactColor(item.analysis.impact_level)}`}>
                                {item.analysis.impact_level}
                            </span>
                        </div>
                    </div>

                    {/* Core Event */}
                    {item.analysis.key_event && (
                        <div className="flex items-start gap-2 mb-4 pb-4 border-b border-slate-900/50">
                            <AlertCircle size={12} className="text-amber-500 mt-0.5 shrink-0" />
                            <div>
                                <div className="text-[9px] text-slate-500 font-bold uppercase tracking-tight">Core Event Identified</div>
                                <div className="text-[11px] text-slate-200 font-medium">{item.analysis.key_event}</div>
                            </div>
                        </div>
                    )}

                    {/* Summary Quote */}
                    <div className="mb-4 pb-4 border-b border-slate-900/50">
                        <div className="text-xs text-slate-300 leading-relaxed italic border-l-2 border-slate-800 pl-3">
                            &quot;{item.analysis.summary}&quot;
                        </div>
                    </div>

                    {/* Key Evidence */}
                    {item.analysis.key_facts && item.analysis.key_facts.length > 0 && (
                        <div className="space-y-3 mb-4">
                            <div className="text-[9px] text-slate-500 font-bold uppercase tracking-widest flex items-center gap-1.5">
                                <BarChart3 size={10} className="text-slate-600" />
                                Key Evidence
                            </div>
                            <div className="grid grid-cols-1 gap-2">
                                {item.analysis.key_facts.map((fact, idx) => (
                                    <div key={idx} className={`p-3 rounded-xl text-[10px] flex flex-col gap-2 ${fact.sentiment === 'bullish' ? 'bg-emerald-500/5 text-emerald-200/80 border border-emerald-500/10' :
                                        fact.sentiment === 'bearish' ? 'bg-rose-500/5 text-rose-200/80 border border-rose-500/10' :
                                            'bg-slate-900/40 text-slate-400 border border-slate-800/50'
                                        }`}>
                                        <div className="flex items-start gap-2">
                                            {fact.is_quantitative ? <BarChart3 size={12} className="shrink-0 text-cyan-500 mt-0.5" /> : <MessageSquare size={12} className="shrink-0 text-slate-600 mt-0.5" />}
                                            <div className="flex-1 leading-normal font-medium">
                                                {fact.content}
                                            </div>
                                        </div>
                                        {fact.citation && (
                                            <div className="text-[8px] opacity-40 pl-5 border-t border-slate-800/30 pt-1 mt-1 truncate">
                                                Source: {fact.citation}
                                            </div>
                                        )}
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}

                    {/* Reasoning Footer */}
                    <div className="text-[10px] text-slate-500 leading-relaxed opacity-80 pt-2">
                        <span className="font-bold uppercase tracking-tighter text-slate-600 mr-1">Analyst Reasoning:</span>
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
