import React, { useState, memo } from 'react';
import { ExternalLink, Calendar, Tag, AlertCircle, Info, TrendingUp, TrendingDown, Minus, Star, BarChart3, MessageSquare, ShieldCheck, ChevronDown } from 'lucide-react';
import { FinancialNewsItem, SentimentLabel, ImpactLevel, SearchCategory, KeyFact } from '@/types/agents/news';

interface NewsResearchCardProps {
    item: FinancialNewsItem;
}

const NewsResearchCardComponent: React.FC<NewsResearchCardProps> = ({ item }) => {
    const getSentimentColor = (sentiment: SentimentLabel) => {
        switch (sentiment) {
            case 'bullish': return 'text-emerald-200 bg-emerald-500/10 border-emerald-400/30';
            case 'bearish': return 'text-rose-200 bg-rose-500/10 border-rose-400/30';
            case 'neutral': return 'text-on-surface-variant bg-surface-container-low border-outline-variant/20';
            default: return 'text-on-surface-variant bg-surface-container-low border-outline-variant/20';
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
            case 'bullish': return {
                css: 'bg-emerald-500/10 text-emerald-200 border-emerald-400/30',
                icon: <TrendingUp size={10} />
            };
            case 'bearish': return {
                css: 'bg-rose-500/10 text-rose-200 border-rose-400/30',
                icon: <TrendingDown size={10} />
            };
            case 'corporate_event': return {
                css: 'bg-indigo-500/10 text-indigo-200 border-indigo-400/30',
                icon: <AlertCircle size={10} />
            };
            case 'financials': return {
                css: 'bg-cyan-500/10 text-cyan-200 border-cyan-400/30',
                icon: <BarChart3 size={10} />
            };
            case 'trusted_news': return {
                css: 'bg-surface-container-high text-on-surface-variant border-outline-variant/20',
                icon: <ShieldCheck size={10} className="text-amber-300" />
            };
            case 'analyst_opinion': return {
                css: 'bg-amber-500/10 text-amber-200 border-amber-400/30',
                icon: <MessageSquare size={10} />
            };
            default: return {
                css: 'bg-surface-container-high text-on-surface-variant border-outline-variant/20',
                icon: <Tag size={10} />
            };
        }
    };

    const getImpactColor = (impact: ImpactLevel) => {
        switch (impact) {
            case 'high': return 'text-rose-500';
            case 'medium': return 'text-amber-500';
            case 'low': return 'text-cyan-500';
            default: return 'text-on-surface-variant';
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
                        className={i < stars ? 'fill-amber-400 text-amber-400' : 'text-outline-variant'}
                    />
                ))}
            </div>
        );
    };

    return (
        <div className="bg-surface-container p-5 rounded-xl border border-outline-variant/10 hover:border-primary-container/30 transition-colors group">
            <div className="flex justify-between items-start mb-4">
                <div className="flex flex-col gap-1">
                    <div className="flex items-center gap-2">
                        <span className="text-[10px] font-bold text-outline uppercase tracking-[0.2em]">
                            {item.source.name}
                        </span>
                        {renderReliability(item.source.reliability_score)}
                        <div className="w-1 h-1 bg-outline-variant/60 rounded-full" />
                        <div className="flex items-center gap-1 text-[9px] text-on-surface-variant font-medium">
                            <Calendar size={10} />
                            {formatDate(item.published_at)}
                        </div>
                    </div>
                    {item.source.author && (
                        <span className="text-[9px] text-on-surface-variant/80 font-medium">By {item.source.author}</span>
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
                className="block group-hover:text-primary-container transition-colors mb-3"
            >
                <h3 className="text-sm font-bold text-on-surface leading-tight flex items-center gap-2">
                    {item.title}
                    <ExternalLink size={12} className="opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
                </h3>
            </a>

            <div className="flex flex-wrap gap-1.5 mb-3">
                {/* Source Tier First */}
                {item.categories.filter(cat => cat === 'trusted_news').map(cat => {
                    const styles = getCategoryStyles(cat);
                    return (
                        <div key={cat} className={`px-2 py-0.5 rounded border text-[8px] font-bold uppercase tracking-tighter flex items-center gap-1.5 ${styles.css}`}>
                            {styles.icon}
                            {cat.replace('_', ' ')}
                        </div>
                    );
                })}
                {/* Intent/Signal Tiers */}
                {item.categories.filter(cat => cat !== 'trusted_news').map(cat => {
                    const styles = getCategoryStyles(cat);
                    return (
                        <div key={cat} className={`px-2 py-0.5 rounded border text-[8px] font-bold uppercase tracking-tighter flex items-center gap-1.5 ${styles.css}`}>
                            {styles.icon}
                            {cat.replace('_', ' ')}
                        </div>
                    );
                })}
            </div>

            <p className="text-xs text-on-surface-variant leading-relaxed mb-4 line-clamp-3">
                {item.snippet}
            </p>

            {item.analysis && (
                <div className="bg-surface-container-low border border-outline-variant/20 rounded-xl p-4 mb-4">
                    {/* Header */}
                    <div className="flex items-center justify-between border-b border-outline-variant/20 pb-3 mb-4">
                        <div className="flex items-center gap-2">
                            <Info size={12} className="text-cyan-500" />
                            <span className="text-[10px] font-bold text-outline uppercase tracking-[0.2em]">AI Evidence Extraction</span>
                        </div>
                        <div className="flex items-center gap-2">
                            <span className="text-[9px] text-on-surface-variant font-bold uppercase">Impact</span>
                            <span className={`text-[10px] font-bold uppercase ${getImpactColor(item.analysis.impact_level)}`}>
                                {item.analysis.impact_level}
                            </span>
                        </div>
                    </div>

                    {/* Core Event */}
                    {item.analysis.key_event && (
                        <div className="flex items-start gap-2 mb-4 pb-4 border-b border-outline-variant/20">
                            <AlertCircle size={12} className="text-amber-500 mt-0.5 shrink-0" />
                            <div>
                                <div className="text-[9px] text-outline font-bold uppercase tracking-tight">Core Event Identified</div>
                                <div className="text-[11px] text-on-surface font-medium">{item.analysis.key_event}</div>
                            </div>
                        </div>
                    )}

                    {/* Summary Quote */}
                    <div className="mb-4 pb-4 border-b border-outline-variant/20">
                        <div className="text-xs text-on-surface-variant leading-relaxed italic border-l-2 border-outline-variant/30 pl-3">
                            &quot;{item.analysis.summary}&quot;
                        </div>
                    </div>

                    {/* Key Evidence */}
                    {item.analysis.key_facts && item.analysis.key_facts.length > 0 && (
                        <KeyEvidenceSection facts={item.analysis.key_facts} />
                    )}

                    {/* Reasoning Footer */}
                    <div className="text-[10px] text-on-surface-variant leading-relaxed opacity-80 pt-2">
                        <span className="font-bold uppercase tracking-tighter text-outline mr-1">Analyst Reasoning:</span>
                        {item.analysis.reasoning}
                    </div>
                </div>
            )}

            <div className="flex flex-wrap gap-2 items-center">
                {item.tags.map(tag => (
                    <div key={tag} className="flex items-center gap-1 bg-surface-container-low border border-outline-variant/20 px-2 py-0.5 rounded text-[9px] text-on-surface-variant font-medium uppercase tracking-tighter">
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
                                className="w-6 h-6 rounded-full bg-surface-container-high border border-outline-variant/30 flex items-center justify-center text-[8px] font-bold text-primary-container hover:z-10 transition-colors cursor-help"
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

// Collapsible Key Evidence Section
const KeyEvidenceSection: React.FC<{ facts: KeyFact[] }> = ({ facts }) => {
    const [isExpanded, setIsExpanded] = useState(false);
    const INITIAL_SHOW_COUNT = 3;
    const shouldCollapse = facts.length > INITIAL_SHOW_COUNT;
    const baseFacts = facts.slice(0, INITIAL_SHOW_COUNT);
    const extraFacts = facts.slice(INITIAL_SHOW_COUNT);
    const hiddenCount = facts.length - INITIAL_SHOW_COUNT;
    const renderFact = (fact: KeyFact, idx: number, keyPrefix: string) => (
        <div key={`${keyPrefix}-${idx}`} className={`p-3 rounded-xl text-[10px] flex flex-col gap-2 ${fact.sentiment === 'bullish' ? 'bg-emerald-500/10 text-emerald-200 border border-emerald-400/30' :
            fact.sentiment === 'bearish' ? 'bg-rose-500/10 text-rose-200 border border-rose-400/30' :
                'bg-surface-container-high text-on-surface-variant border border-outline-variant/20'
            }`}>
            <div className="flex items-start gap-2">
                {fact.is_quantitative ? <BarChart3 size={12} className="shrink-0 text-cyan-400 mt-0.5" /> : <MessageSquare size={12} className="shrink-0 text-outline-variant mt-0.5" />}
                <div className="flex-1 leading-normal font-medium">
                    {fact.content}
                </div>
            </div>
            {fact.citation && (
                <div className="text-[8px] text-on-surface-variant/70 pl-5 border-t border-outline-variant/20 pt-1 mt-1 truncate">
                    Source: {fact.citation}
                </div>
            )}
        </div>
    );

    return (
        <div className="space-y-3 mb-4">
            <div className="text-[9px] text-outline font-bold uppercase tracking-[0.2em] flex items-center gap-1.5">
                <BarChart3 size={10} className="text-outline-variant" />
                Key Evidence
                <span className="text-outline-variant">({facts.length})</span>
            </div>
            <div className="grid grid-cols-1 gap-2">
                {baseFacts.map((fact, idx) => renderFact(fact, idx, 'base'))}
            </div>
            {shouldCollapse && (
                <div
                    className={`expandable-panel ${isExpanded ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0'}`}
                >
                    <div className="overflow-hidden">
                        <div className="grid grid-cols-1 gap-2 pt-2">
                            {extraFacts.map((fact, idx) => renderFact(fact, idx, 'extra'))}
                        </div>
                    </div>
                </div>
            )}
            {shouldCollapse && (
                <button
                    onClick={() => setIsExpanded(!isExpanded)}
                    className="w-full flex items-center justify-center gap-1.5 py-2 text-[10px] font-bold uppercase tracking-[0.2em] text-outline hover:text-primary-container transition-colors rounded-lg border border-outline-variant/20 hover:border-primary-container/30 bg-surface-container-low"
                >
                    <ChevronDown
                        size={12}
                        className={`expandable-chevron ${isExpanded ? 'rotate-180' : ''}`}
                    />
                    {isExpanded ? 'Show less' : `Show ${hiddenCount} more`}
                </button>
            )}
        </div>
    );
};

// Export with React.memo for performance optimization
export const NewsResearchCard = memo(NewsResearchCardComponent);
