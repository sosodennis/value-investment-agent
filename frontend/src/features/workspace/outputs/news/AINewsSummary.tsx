import React, { memo, useMemo } from 'react';
import { PieChart, List, TrendingUp, TrendingDown, Minus, Zap, BarChart3, Database, ShieldCheck, AlertCircle, MessageSquare } from 'lucide-react';
import { NewsResearchOutput, SentimentLabel } from '@/types/agents/news';
import { NewsPreview, isNewsPreview } from '@/types/preview';
import type { BadgeProps } from '@/components/ui/badge';
import { Badge } from '@/components/ui/badge';
import { Card } from '@/components/ui/card';
import { AgentLoadingState } from '../shared/AgentLoadingState';

interface AINewsSummaryProps {
    output: NewsResearchOutput | NewsPreview;
}

const AINewsSummaryComponent: React.FC<AINewsSummaryProps> = ({ output }) => {
    const isPreview = isNewsPreview(output);
    const newsItems = useMemo(
        () => (isPreview ? [] : output.news_items || []),
        [isPreview, output]
    );
    const keyThemes = useMemo(
        () => (isPreview ? [] : output.key_themes || []),
        [isPreview, output]
    );
    const overallSentiment: SentimentLabel = isPreview
        ? 'neutral'
        : output.overall_sentiment || 'neutral';
    const previewSentimentDisplay = isPreview ? output.sentiment_display : undefined;
    const previewArticleCountDisplay = isPreview ? output.article_count_display : undefined;

    const getSentimentVariant = (sentiment: SentimentLabel): NonNullable<BadgeProps['variant']> => {
        switch (sentiment) {
            case 'bullish': return 'success';
            case 'bearish': return 'destructive';
            default: return 'outline';
        }
    };

    // Memoize expensive calculations
    const { allFacts, bullFactsCount, bearFactsCount, neutralFactsCount, quantFactsCount } = useMemo(() => {
        const facts = newsItems.flatMap((item) => item.analysis?.key_facts || []);
        return {
            allFacts: facts,
            bullFactsCount: facts.filter(f => f.sentiment === 'bullish').length,
            bearFactsCount: facts.filter(f => f.sentiment === 'bearish').length,
            neutralFactsCount: facts.filter(f => f.sentiment === 'neutral').length,
            quantFactsCount: facts.filter(f => f.is_quantitative).length,
        };
    }, [newsItems]);

    const categoryStats = useMemo(
        () =>
            newsItems.reduce<Record<string, number>>((acc, item) => {
                item.categories.forEach((cat) => {
                    acc[cat] = (acc[cat] || 0) + 1;
                });
                return acc;
            }, {}),
        [newsItems]
    );

    // Calculate score percentage (mapping -1 to 1 into 0 to 100)
    const sentimentScore = !isPreview && typeof output.sentiment_score === 'number' ? output.sentiment_score : 0;
    const scorePercentage = Math.round(((sentimentScore + 1) / 2) * 100);

    // Calculate bullish consensus (% of decided articles that are bullish)
    const decidedCount = bullFactsCount + bearFactsCount;
    const bullishConsensus = decidedCount > 0 ? Math.round((bullFactsCount / decidedCount) * 100) : 50;

    const totalSources = newsItems.length;
    const averageSourceReliability = newsItems.length > 0
        ? newsItems.reduce((total, item) => total + item.source.reliability_score, 0) / newsItems.length
        : null;

    // Consensus label
    const getConsensusLabel = () => {
        if (isPreview) return previewSentimentDisplay || 'PREVIEW MODE';
        if (decidedCount === 0) return 'No Clear Signal';
        if (bullishConsensus >= 80) return 'Strong Bull Consensus';
        if (bullishConsensus >= 60) return 'Bullish Leaning';
        if (bullishConsensus <= 20) return 'Strong Bear Consensus';
        if (bullishConsensus <= 40) return 'Bearish Leaning';
        return 'Mixed Signals';
    };

    if (!isPreview && (newsItems.length === 0 || typeof output.sentiment_score !== 'number')) {
        return (
            <AgentLoadingState
                type="block"
                title="Analyzing News Sentiment…"
            />
        );
    }

    return (
        <div className="space-y-6">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                {/* Overall Sentiment Card - Redesigned to emphasize consensus */}
                <Card className="col-span-1 md:col-span-2 grid content-start gap-4 p-4">
                    {/* Header with Consensus Label */}
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
                        <div className="flex items-center gap-3">
                            <Zap size={18} className="text-warning flex-shrink-0" />
                            <h3 className="text-base font-semibold text-foreground">Market consensus</h3>
                        </div>
                        <Badge variant={getSentimentVariant(overallSentiment)} className="max-w-full whitespace-normal text-center">
                            {getConsensusLabel()}
                        </Badge>
                    </div>

                    <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
                        <span>Source coverage</span>
                        <Badge variant="outline">{isPreview ? previewArticleCountDisplay ?? 'Preview' : `${totalSources} sources`}</Badge>
                        {!isPreview ? <span>{allFacts.length} evidence points</span> : null}
                    </div>

                    {/* HERO: Evidence Distribution - Main Visual */}
                    <div className="space-y-3 mb-6">
                        <div className="flex justify-between items-center text-xs font-bold uppercase tracking-wider">
                            <span className="text-foreground">Evidence Distribution</span>
                            {isPreview && (
                                <span className="text-primary text-xs">{previewArticleCountDisplay || 'Loading…'}</span>
                            )}
                            {!isPreview && decidedCount > 0 && bearFactsCount === 0 && (
                                <span className="text-success text-xs">⚠️ No Bearish Evidence Found</span>
                            )}
                            {!isPreview && decidedCount > 0 && bullFactsCount === 0 && (
                                <span className="text-destructive text-xs">⚠️ No Bullish Evidence Found</span>
                            )}
                        </div>

                        {/* Thick Stacked Bar - The Hero Visual */}
                        <div className="flex h-10 w-full rounded-lg overflow-hidden bg-muted border border-border/20 ">
                            {bullFactsCount > 0 && (
                                <div
                                    className="bg-success transition-[width] duration-300 flex items-center justify-center relative group"
                                    style={{ width: `${isPreview ? 0 : (bullFactsCount / (allFacts.length || 1)) * 100}%` }}
                                >
                                    <div className="flex items-center gap-1.5 text-foreground font-bold">
                                        <TrendingUp size={14} />
                                        <span className="text-sm">{bullFactsCount}</span>
                                    </div>
                                </div>
                            )}
                            {(neutralFactsCount > 0 || isPreview) && (
                                <div
                                    className="bg-muted transition-[width] duration-300 flex items-center justify-center"
                                    style={{ width: `${isPreview ? 100 : (neutralFactsCount / (allFacts.length || 1)) * 100}%` }}
                                >
                                    <div className="flex items-center gap-1.5 text-muted-foreground font-bold">
                                        <Minus size={14} />
                                        <span className="text-sm">{isPreview ? 'LOADING EVIDENCE…' : neutralFactsCount}</span>
                                    </div>
                                </div>
                            )}
                            {bearFactsCount > 0 && !isPreview && (
                                <div
                                    className="bg-destructive transition-[width] duration-300 flex items-center justify-center"
                                    style={{ width: `${(bearFactsCount / (allFacts.length || 1)) * 100}%` }}
                                >
                                    <div className="flex items-center gap-1.5 text-foreground font-bold">
                                        <TrendingDown size={14} />
                                        <span className="text-sm">{bearFactsCount}</span>
                                    </div>
                                </div>
                            )}
                        </div>

                        {/* Legend */}
                        <div className="flex justify-center gap-6 text-xs font-bold uppercase tracking-wider text-muted-foreground">
                            <div className="flex items-center gap-1.5">
                                <div className="w-3 h-3 rounded bg-success" />
                                <span>Bullish ({bullFactsCount})</span>
                            </div>
                            <div className="flex items-center gap-1.5">
                                <div className="w-3 h-3 rounded bg-muted" />
                                <span>Neutral ({neutralFactsCount})</span>
                            </div>
                            <div className="flex items-center gap-1.5">
                                <div className="w-3 h-3 rounded bg-destructive" />
                                <span>Bearish ({bearFactsCount})</span>
                            </div>
                        </div>
                    </div>

                    {/* Supplementary: Average Intensity */}
                    <div className="pt-4 border-t border-border/20 space-y-2">
                        <div className="flex justify-between items-center text-xs font-bold uppercase tracking-wider text-muted-foreground">
                            <span>Average Intensity</span>
                            <span className="text-foreground">
                                {isPreview ? (previewSentimentDisplay || 'PREVIEW MODE') : (
                                    <>
                                        {sentimentScore > 0 ? '+' : ''}{sentimentScore.toFixed(2)} ({sentimentScore > 0.3 ? 'Strong' : sentimentScore > 0 ? 'Moderate' : sentimentScore < -0.3 ? 'Strong' : sentimentScore < 0 ? 'Moderate' : 'Neutral'})
                                    </>
                                )}
                            </span>
                        </div>
                        <div className="h-2 w-full bg-muted rounded-full overflow-hidden border border-border/20">
                            <div
                            className={`h-full transition-[width,background-color] duration-1000 ease-out ${sentimentScore > 0 ? 'bg-success/60' : sentimentScore < 0 ? 'bg-destructive/60' : 'bg-muted'}`}
                                style={{ width: `${scorePercentage}%` }}
                            />
                        </div>
                        <div className="flex justify-between text-xs text-muted-foreground font-bold uppercase tracking-tighter">
                            <span>Bearish (-1.0)</span>
                            <span>Neutral (0.0)</span>
                            <span>Bullish (+1.0)</span>
                        </div>
                    </div>
                </Card>

                {/* Debate-Ready Metrics Card */}
                <Card className="grid content-start gap-4 p-4">
                    <div className="flex items-center gap-2">
                        <ShieldCheck size={16} className="text-primary" />
                        <h3 className="text-base font-semibold">Evidence quality</h3>
                    </div>

                    <div className="space-y-4">
                        <div className="flex justify-between items-center border-b border-border/20 pb-3">
                            <div className="flex items-center gap-2">
                                <Database size={12} className="text-muted-foreground" />
                                <span className="text-xs text-muted-foreground font-medium uppercase tracking-tighter">Total Evidence</span>
                            </div>
                            <span className="text-xs font-bold text-foreground">{allFacts.length}</span>
                        </div>
                        <div className="flex justify-between items-center border-b border-border/20 pb-3">
                            <div className="flex items-center gap-2">
                                <BarChart3 size={12} className="text-primary" />
                                <span className="text-xs text-muted-foreground font-medium uppercase tracking-tighter">Quantitative</span>
                            </div>
                            <span className="text-xs font-bold text-primary">{quantFactsCount}</span>
                        </div>
                        <div className="flex justify-between items-center border-b border-border/20 pb-3">
                            <div className="flex items-center gap-2">
                                <ShieldCheck size={12} className="text-success" />
                                <span className="text-xs text-muted-foreground font-medium uppercase tracking-tighter">Source Reliability</span>
                            </div>
                            <span className="text-xs font-semibold text-foreground">
                                {averageSourceReliability === null ? 'Not reported' : `${(averageSourceReliability * 100).toFixed(0)}% average`}
                            </span>
                        </div>
                    </div>
                </Card>
            </div>

            {/* Sub-Agent Triage Stats */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <Card className="grid content-start gap-4 p-4">
                    <div className="flex items-center gap-2">
                        <List size={16} className="text-primary" />
                        <h3 className="text-base font-semibold">Knowledge themes</h3>
                    </div>

                    <div className="flex flex-wrap gap-2">
                        {keyThemes.map(theme => (
                            <Badge key={theme} variant="outline">
                                {theme}
                            </Badge>
                        ))}
                        {keyThemes.length === 0 && (
                        <div className="text-xs text-muted-foreground italic">No Specific Themes Identified</div>
                    )}
                    </div>
                </Card>

                <Card className="grid content-start gap-4 p-4">
                    <div className="flex items-center gap-2">
                        <PieChart size={16} className="text-warning" />
                        <h3 className="text-base font-semibold">Search category coverage</h3>
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                        {Object.entries(categoryStats).map(([cat, count]) => (
                            <div key={cat} className="flex justify-between items-center p-2 bg-muted/50 rounded-lg border border-border/20">
                                <div className="flex items-center gap-2">
                                    {cat === 'bullish' && <TrendingUp size={10} className="text-success" />}
                                    {cat === 'bearish' && <TrendingDown size={10} className="text-destructive" />}
                                    {cat === 'corporate_event' && <AlertCircle size={10} className="text-primary" />}
                                    {cat === 'financials' && <BarChart3 size={10} className="text-primary" />}
                                    {cat === 'trusted_news' && <ShieldCheck size={10} className="text-warning" />}
                                    {cat === 'analyst_opinion' && <MessageSquare size={10} className="text-warning" />}
                                    <span className="text-xs font-bold text-muted-foreground uppercase tracking-tighter">
                                        {cat.replace('_', ' ')}
                                    </span>
                                </div>
                                <span className="text-xs font-bold text-foreground">{count}</span>
                            </div>
                        ))}
                    </div>
                </Card>
            </div>
        </div>
    );
};

// Export with React.memo for performance optimization
export const AINewsSummary = memo(AINewsSummaryComponent);
