import React, { memo, useMemo } from 'react';
import { PieChart, List, TrendingUp, TrendingDown, Minus, Zap, BarChart3, Database, ShieldCheck, AlertCircle, MessageSquare } from 'lucide-react';
import { NewsResearchOutput, SentimentLabel, SearchCategory } from '@/types/agents/news';

interface AINewsSummaryProps {
    output: NewsResearchOutput;
}

const AINewsSummaryComponent: React.FC<AINewsSummaryProps> = ({ output }) => {
    // Defensive check: ensure critical fields exist before rendering
    const isPreview = (output as any).sentiment_display !== undefined;

    if (!isPreview && (!output.news_items || output.news_items.length === 0 || typeof output.sentiment_score !== 'number')) {
        return (
            <div className="flex flex-col items-center justify-center p-12 text-slate-500">
                <Zap className="w-12 h-12 mb-4 animate-pulse opacity-50" />
                <p className="font-bold uppercase tracking-widest text-[10px]">Analyzing News Sentiment...</p>
            </div>
        );
    }

    const getSentimentColor = (sentiment: SentimentLabel) => {
        switch (sentiment) {
            case 'bullish': return 'text-emerald-400';
            case 'bearish': return 'text-rose-400';
            default: return 'text-slate-400';
        }
    };

    const getSentimentBg = (sentiment: SentimentLabel) => {
        switch (sentiment) {
            case 'bullish': return 'bg-emerald-500/10 border-emerald-500/20';
            case 'bearish': return 'bg-rose-500/10 border-rose-500/20';
            default: return 'bg-slate-500/10 border-slate-500/20';
        }
    };

    const getSentimentIcon = (sentiment: SentimentLabel) => {
        switch (sentiment) {
            case 'bullish': return <TrendingUp size={20} className="text-emerald-500" />;
            case 'bearish': return <TrendingDown size={20} className="text-rose-500" />;
            default: return <Minus size={20} className="text-slate-500" />;
        }
    };

    // Memoize expensive calculations
    const { allFacts, bullFactsCount, bearFactsCount, neutralFactsCount, quantFactsCount } = useMemo(() => {
        const items = output.news_items || [];
        const facts = items.flatMap(item => item.analysis?.key_facts || []);
        return {
            allFacts: facts,
            bullFactsCount: facts.filter(f => f.sentiment === 'bullish').length,
            bearFactsCount: facts.filter(f => f.sentiment === 'bearish').length,
            neutralFactsCount: facts.filter(f => f.sentiment === 'neutral').length,
            quantFactsCount: facts.filter(f => f.is_quantitative).length,
        };
    }, [output.news_items]);

    const categoryStats = useMemo(() => (output.news_items || []).reduce((acc, item) => {
        item.categories.forEach(cat => {
            acc[cat] = (acc[cat] || 0) + 1;
        });
        return acc;
    }, {} as Record<string, number>), [output.news_items]);

    // Calculate score percentage (mapping -1 to 1 into 0 to 100)
    const sentimentScore = typeof output.sentiment_score === 'number' ? output.sentiment_score : 0;
    const scorePercentage = Math.round(((sentimentScore + 1) / 2) * 100);

    // Calculate bullish consensus (% of decided articles that are bullish)
    const decidedCount = bullFactsCount + bearFactsCount;
    const bullishConsensus = decidedCount > 0 ? Math.round((bullFactsCount / decidedCount) * 100) : 50;

    // Signal confidence based on sample size
    const totalSources = output.news_items?.length || 0;
    const getSignalConfidence = () => {
        if (totalSources >= 8) return { level: 'High', color: 'text-emerald-400', icon: '🔥' };
        if (totalSources >= 5) return { level: 'Medium', color: 'text-amber-400', icon: '⚡' };
        return { level: 'Low', color: 'text-slate-400', icon: '💨' };
    };
    const signalConfidence = getSignalConfidence();

    // Consensus label
    const getConsensusLabel = () => {
        if (isPreview) return (output as any).sentiment_display;
        if (decidedCount === 0) return 'No Clear Signal';
        if (bullishConsensus >= 80) return 'Strong Bull Consensus';
        if (bullishConsensus >= 60) return 'Bullish Leaning';
        if (bullishConsensus <= 20) return 'Strong Bear Consensus';
        if (bullishConsensus <= 40) return 'Bearish Leaning';
        return 'Mixed Signals';
    };

    return (
        <div className="space-y-6">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                {/* Overall Sentiment Card - Redesigned to emphasize consensus */}
                <div className={`col-span-1 md:col-span-2 rounded-2xl border p-6 backdrop-blur-md ${getSentimentBg(output.overall_sentiment)}`}>
                    {/* Header with Consensus Label */}
                    <div className="flex items-center justify-between mb-6">
                        <div className="flex items-center gap-3">
                            <Zap size={18} className="text-amber-400" />
                            <h3 className="text-sm font-bold text-white uppercase tracking-widest">Market Consensus</h3>
                        </div>
                        <div className={`px-4 py-1.5 rounded-full border text-xs font-bold uppercase tracking-widest bg-slate-950/40 ${getSentimentColor(output.overall_sentiment || 'neutral')}`}>
                            {getConsensusLabel()}
                        </div>
                    </div>

                    {/* Signal Confidence Indicator */}
                    <div className="flex items-center gap-2 mb-6 text-[10px] font-bold uppercase tracking-widest">
                        <span className="text-slate-500">Signal Confidence:</span>
                        {isPreview ? (
                            <span className="text-cyan-400">PREVIEW MODE</span>
                        ) : (
                            <>
                                <span className={signalConfidence.color}>{signalConfidence.icon} {signalConfidence.level}</span>
                                <span className="text-slate-600">(Based on {totalSources} sources, {allFacts.length} evidence points)</span>
                            </>
                        )}
                    </div>

                    {/* HERO: Evidence Distribution - Main Visual */}
                    <div className="space-y-3 mb-6">
                        <div className="flex justify-between items-center text-xs font-bold uppercase tracking-widest">
                            <span className="text-white">Evidence Distribution</span>
                            {isPreview && (
                                <span className="text-cyan-400 text-[10px]">{(output as any).article_count_display}</span>
                            )}
                            {!isPreview && decidedCount > 0 && bearFactsCount === 0 && (
                                <span className="text-emerald-400 text-[10px]">⚠️ No bearish evidence found</span>
                            )}
                            {!isPreview && decidedCount > 0 && bullFactsCount === 0 && (
                                <span className="text-rose-400 text-[10px]">⚠️ No bullish evidence found</span>
                            )}
                        </div>

                        {/* Thick Stacked Bar - The Hero Visual */}
                        <div className="flex h-10 w-full rounded-xl overflow-hidden bg-slate-950/50 border border-slate-800 shadow-lg">
                            {bullFactsCount > 0 && (
                                <div
                                    className="bg-gradient-to-r from-emerald-600 to-emerald-500 transition-all duration-1000 flex items-center justify-center relative group"
                                    style={{ width: `${isPreview ? 0 : (bullFactsCount / (allFacts.length || 1)) * 100}%` }}
                                >
                                    <div className="flex items-center gap-1.5 text-white font-bold">
                                        <TrendingUp size={14} />
                                        <span className="text-sm">{bullFactsCount}</span>
                                    </div>
                                </div>
                            )}
                            {(neutralFactsCount > 0 || isPreview) && (
                                <div
                                    className="bg-gradient-to-r from-slate-600 to-slate-500 transition-all duration-1000 flex items-center justify-center"
                                    style={{ width: `${isPreview ? 100 : (neutralFactsCount / (allFacts.length || 1)) * 100}%` }}
                                >
                                    <div className="flex items-center gap-1.5 text-slate-300 font-bold">
                                        <Minus size={14} />
                                        <span className="text-sm">{isPreview ? 'LOADING EVIDENCE...' : neutralFactsCount}</span>
                                    </div>
                                </div>
                            )}
                            {bearFactsCount > 0 && !isPreview && (
                                <div
                                    className="bg-gradient-to-r from-rose-600 to-rose-500 transition-all duration-1000 flex items-center justify-center"
                                    style={{ width: `${(bearFactsCount / (allFacts.length || 1)) * 100}%` }}
                                >
                                    <div className="flex items-center gap-1.5 text-white font-bold">
                                        <TrendingDown size={14} />
                                        <span className="text-sm">{bearFactsCount}</span>
                                    </div>
                                </div>
                            )}
                        </div>

                        {/* Legend */}
                        <div className="flex justify-center gap-6 text-[9px] font-bold uppercase tracking-widest text-slate-500">
                            <div className="flex items-center gap-1.5">
                                <div className="w-3 h-3 rounded bg-emerald-500" />
                                <span>Bullish ({bullFactsCount})</span>
                            </div>
                            <div className="flex items-center gap-1.5">
                                <div className="w-3 h-3 rounded bg-slate-500" />
                                <span>Neutral ({neutralFactsCount})</span>
                            </div>
                            <div className="flex items-center gap-1.5">
                                <div className="w-3 h-3 rounded bg-rose-500" />
                                <span>Bearish ({bearFactsCount})</span>
                            </div>
                        </div>
                    </div>

                    {/* Supplementary: Average Intensity */}
                    <div className="pt-4 border-t border-slate-800/50 space-y-2">
                        <div className="flex justify-between items-center text-[10px] font-bold uppercase tracking-widest text-slate-500">
                            <span>Average Intensity</span>
                            <span className="text-slate-300">
                                {isPreview ? (output as any).sentiment_display : (
                                    <>
                                        {sentimentScore > 0 ? '+' : ''}{sentimentScore.toFixed(2)} ({sentimentScore > 0.3 ? 'Strong' : sentimentScore > 0 ? 'Moderate' : sentimentScore < -0.3 ? 'Strong' : sentimentScore < 0 ? 'Moderate' : 'Neutral'})
                                    </>
                                )}
                            </span>
                        </div>
                        <div className="h-2 w-full bg-slate-950/50 rounded-full overflow-hidden border border-slate-800">
                            <div
                                className={`h-full transition-all duration-1000 ease-out ${sentimentScore > 0 ? 'bg-emerald-500/60' : sentimentScore < 0 ? 'bg-rose-500/60' : 'bg-slate-500/60'}`}
                                style={{ width: `${scorePercentage}%` }}
                            />
                        </div>
                        <div className="flex justify-between text-[8px] text-slate-600 font-bold uppercase tracking-tighter">
                            <span>Bearish (-1.0)</span>
                            <span>Neutral (0.0)</span>
                            <span>Bullish (+1.0)</span>
                        </div>
                    </div>
                </div>

                {/* Debate-Ready Metrics Card */}
                <div className="bg-slate-900/20 border border-slate-800/50 rounded-2xl p-6 backdrop-blur-sm">
                    <div className="flex items-center gap-3 mb-6">
                        <ShieldCheck size={16} className="text-cyan-400" />
                        <h3 className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Evidence Quality</h3>
                    </div>

                    <div className="space-y-4">
                        <div className="flex justify-between items-center border-b border-slate-900 pb-3">
                            <div className="flex items-center gap-2">
                                <Database size={12} className="text-slate-500" />
                                <span className="text-[11px] text-slate-500 font-medium uppercase tracking-tighter">Total Evidence</span>
                            </div>
                            <span className="text-xs font-bold text-slate-200">{allFacts.length}</span>
                        </div>
                        <div className="flex justify-between items-center border-b border-slate-900 pb-3">
                            <div className="flex items-center gap-2">
                                <BarChart3 size={12} className="text-cyan-500" />
                                <span className="text-[11px] text-slate-500 font-medium uppercase tracking-tighter">Quantitative</span>
                            </div>
                            <span className="text-xs font-bold text-cyan-400">{quantFactsCount}</span>
                        </div>
                        <div className="flex justify-between items-center border-b border-slate-900 pb-3">
                            <div className="flex items-center gap-2">
                                <ShieldCheck size={12} className="text-emerald-500" />
                                <span className="text-[11px] text-slate-500 font-medium uppercase tracking-tighter">Source Reliability</span>
                            </div>
                            <span className="text-xs font-bold text-emerald-400">High</span>
                        </div>
                    </div>
                </div>
            </div>

            {/* Sub-Agent Triage Stats */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div className="bg-slate-950/30 border border-slate-900 rounded-2xl p-6">
                    <div className="flex items-center gap-3 mb-6">
                        <List size={16} className="text-indigo-400" />
                        <h3 className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Knowledge Themes</h3>
                    </div>

                    <div className="flex flex-wrap gap-2">
                        {(output.key_themes || []).map(theme => (
                            <div key={theme} className="px-4 py-2 bg-slate-900 border border-slate-800 rounded-xl text-xs font-medium text-slate-300 hover:border-indigo-500/50 hover:text-white transition-all cursor-default">
                                {theme}
                            </div>
                        ))}
                        {(!output.key_themes || output.key_themes.length === 0) && (
                            <div className="text-xs text-slate-600 italic">No specific themes identified.</div>
                        )}
                    </div>
                </div>

                <div className="bg-slate-950/30 border border-slate-900 rounded-2xl p-6">
                    <div className="flex items-center gap-3 mb-6">
                        <PieChart size={16} className="text-amber-400" />
                        <h3 className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Search Category Coverage</h3>
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                        {Object.entries(categoryStats).map(([cat, count]) => (
                            <div key={cat} className="flex justify-between items-center p-2 bg-slate-900/50 rounded-lg border border-slate-800">
                                <div className="flex items-center gap-2">
                                    {cat === 'bullish' && <TrendingUp size={10} className="text-emerald-500" />}
                                    {cat === 'bearish' && <TrendingDown size={10} className="text-rose-500" />}
                                    {cat === 'corporate_event' && <AlertCircle size={10} className="text-indigo-500" />}
                                    {cat === 'financials' && <BarChart3 size={10} className="text-cyan-500" />}
                                    {cat === 'trusted_news' && <ShieldCheck size={10} className="text-amber-500" />}
                                    {cat === 'analyst_opinion' && <MessageSquare size={10} className="text-amber-500" />}
                                    <span className="text-[10px] font-bold text-slate-500 uppercase tracking-tighter">
                                        {cat.replace('_', ' ')}
                                    </span>
                                </div>
                                <span className="text-xs font-bold text-white">{count}</span>
                            </div>
                        ))}
                    </div>
                </div>
            </div>
        </div>
    );
};

// Export with React.memo for performance optimization
export const AINewsSummary = memo(AINewsSummaryComponent);
