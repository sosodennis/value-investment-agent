import React from 'react';
import { PieChart, List, TrendingUp, TrendingDown, Minus, Zap, BarChart3, Database, ShieldCheck, AlertCircle, MessageSquare } from 'lucide-react';
import { NewsResearchOutput, SentimentLabel, SearchCategory } from '../types/news';

interface AINewsSummaryProps {
    output: NewsResearchOutput;
}

export const AINewsSummary: React.FC<AINewsSummaryProps> = ({ output }) => {
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

    // Calculate metrics
    const allFacts = output.news_items.flatMap(item => item.analysis?.key_facts || []);
    const bullFactsCount = allFacts.filter(f => f.sentiment === 'bullish').length;
    const bearFactsCount = allFacts.filter(f => f.sentiment === 'bearish').length;
    const quantFactsCount = allFacts.filter(f => f.is_quantitative).length;

    const categoryStats = output.news_items.reduce((acc, item) => {
        item.categories.forEach(cat => {
            acc[cat] = (acc[cat] || 0) + 1;
        });
        return acc;
    }, {} as Record<string, number>);

    // Calculate score percentage (mapping -1 to 1 into 0 to 100)
    const scorePercentage = Math.round(((output.sentiment_score + 1) / 2) * 100);

    return (
        <div className="space-y-6">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                {/* Overall Sentiment Card */}
                <div className={`col-span-1 md:col-span-2 rounded-2xl border p-6 backdrop-blur-md ${getSentimentBg(output.overall_sentiment)}`}>
                    <div className="flex items-center justify-between mb-8">
                        <div className="flex items-center gap-3">
                            <Zap size={18} className="text-amber-400" />
                            <h3 className="text-sm font-bold text-white uppercase tracking-widest">Aggregate Sentiment</h3>
                        </div>
                        <div className={`px-4 py-1.5 rounded-full border text-xs font-bold uppercase tracking-widest bg-slate-950/40 ${getSentimentColor(output.overall_sentiment)}`}>
                            {output.overall_sentiment}
                        </div>
                    </div>

                    <div className="flex items-end gap-8">
                        <div className="flex-1 space-y-4">
                            <div className="flex justify-between items-center text-[10px] font-bold uppercase tracking-widest text-slate-400">
                                <span>Sentiment Score Intensity</span>
                                <span className="text-white">{(output.sentiment_score).toFixed(2)}</span>
                            </div>
                            <div className="h-3 w-full bg-slate-950/50 rounded-full overflow-hidden border border-slate-800">
                                <div
                                    className={`h-full transition-all duration-1000 ease-out shadow-[0_0_15px_rgba(34,211,238,0.2)] ${output.sentiment_score > 0 ? 'bg-emerald-500' : output.sentiment_score < 0 ? 'bg-rose-500' : 'bg-slate-500'
                                        }`}
                                    style={{ width: `${scorePercentage}%` }}
                                />
                            </div>
                            <div className="flex justify-between text-[8px] text-slate-600 font-bold uppercase tracking-tighter">
                                <span>Bearish (-1.0)</span>
                                <span>Neutral (0.0)</span>
                                <span>Bullish (+1.0)</span>
                            </div>

                            {/* Fact Distribution Bar */}
                            <div className="pt-4 space-y-2">
                                <div className="flex justify-between text-[9px] font-bold text-slate-500 uppercase tracking-widest">
                                    <span>Evidence Distribution</span>
                                    <span>{bullFactsCount} Bull / {bearFactsCount} Bear</span>
                                </div>
                                <div className="flex h-1.5 w-full rounded-full overflow-hidden bg-slate-950/50 border border-slate-800">
                                    <div
                                        className="bg-emerald-500 transition-all duration-1000"
                                        style={{ width: `${(bullFactsCount / (allFacts.length || 1)) * 100}%` }}
                                    />
                                    <div
                                        className="bg-rose-500 transition-all duration-1000"
                                        style={{ width: `${(bearFactsCount / (allFacts.length || 1)) * 100}%` }}
                                    />
                                    <div
                                        className="bg-slate-700 transition-all duration-1000"
                                        style={{ width: `${((allFacts.length - bullFactsCount - bearFactsCount) / (allFacts.length || 1)) * 100}%` }}
                                    />
                                </div>
                            </div>
                        </div>

                        <div className="shrink-0 flex flex-col items-center justify-center w-24 h-24 rounded-full border-4 border-slate-900 bg-slate-950/60 shadow-2xl relative overflow-hidden group">
                            <div className={`absolute inset-0 opacity-10 animate-pulse ${output.sentiment_score > 0 ? 'bg-emerald-500' : output.sentiment_score < 0 ? 'bg-rose-500' : 'bg-slate-500'}`} />
                            {getSentimentIcon(output.overall_sentiment)}
                            <div className="text-[10px] font-bold text-white mt-1 uppercase tracking-tighter">
                                {output.sentiment_score > 0 ? '+' : ''}{output.sentiment_score.toFixed(2)}
                            </div>
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
                        {output.key_themes.map(theme => (
                            <div key={theme} className="px-4 py-2 bg-slate-900 border border-slate-800 rounded-xl text-xs font-medium text-slate-300 hover:border-indigo-500/50 hover:text-white transition-all cursor-default">
                                {theme}
                            </div>
                        ))}
                        {output.key_themes.length === 0 && (
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
