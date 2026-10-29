import React, { useState, memo } from 'react';
import { ExternalLink, Calendar, Tag, AlertCircle, Info, TrendingUp, TrendingDown, Minus, Star, BarChart3, MessageSquare, ShieldCheck, ChevronDown } from 'lucide-react';
import { FinancialNewsItem, SentimentLabel, ImpactLevel, SearchCategory, KeyFact } from '@/types/agents/news';
import type { BadgeProps } from '@/components/ui/badge';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';

interface NewsResearchCardProps {
    item: FinancialNewsItem;
}

const NewsResearchCardComponent: React.FC<NewsResearchCardProps> = ({ item }) => {
    const getSentimentVariant = (sentiment: SentimentLabel): NonNullable<BadgeProps['variant']> => {
        switch (sentiment) {
            case 'bullish': return 'success';
            case 'bearish': return 'destructive';
            case 'neutral': return 'outline';
            default: return 'outline';
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

    const getCategoryStyles = (category: SearchCategory): { variant: NonNullable<BadgeProps['variant']>; icon: React.ReactNode } => {
        switch (category) {
            case 'bullish': return {
                variant: 'success',
                icon: <TrendingUp size={10} />
            };
            case 'bearish': return {
                variant: 'destructive',
                icon: <TrendingDown size={10} />
            };
            case 'corporate_event': return {
                variant: 'default',
                icon: <AlertCircle size={10} />
            };
            case 'financials': return {
                variant: 'default',
                icon: <BarChart3 size={10} />
            };
            case 'trusted_news': return {
                variant: 'outline',
                icon: <ShieldCheck size={10} className="text-warning" />
            };
            case 'analyst_opinion': return {
                variant: 'warning',
                icon: <MessageSquare size={10} />
            };
            default: return {
                variant: 'outline',
                icon: <Tag size={10} />
            };
        }
    };

    const getImpactVariant = (impact: ImpactLevel): NonNullable<BadgeProps['variant']> => {
        switch (impact) {
            case 'high': return 'destructive';
            case 'medium': return 'warning';
            case 'low': return 'default';
            default: return 'outline';
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
            <div className="flex items-center gap-0.5" role="img" aria-label={`Source reliability: ${(score * 100).toFixed(0)}%`}>
                {[...Array(5)].map((_, i) => (
                    <Star
                        key={i}
                        size={8}
                        className={i < stars ? 'fill-warning text-warning' : 'text-border'}
                    />
                ))}
            </div>
        );
    };

    return (
        <Card className="group p-4 transition-colors hover:bg-muted/30">
            <div className="flex justify-between items-start mb-4">
                <div className="flex flex-col gap-1">
                    <div className="flex items-center gap-2">
                        <span className="text-xs font-bold text-muted-foreground uppercase tracking-[0.2em]">
                            {item.source.name}
                        </span>
                        {renderReliability(item.source.reliability_score)}
                        <div className="w-1 h-1 bg-border/60 rounded-full" />
                        <div className="flex items-center gap-1 text-xs text-muted-foreground font-medium">
                            <Calendar size={10} />
                            {formatDate(item.published_at)}
                        </div>
                    </div>
                    {item.source.author && (
                        <span className="text-xs text-muted-foreground/80 font-medium">By {item.source.author}</span>
                    )}
                </div>

                <div className="flex items-center gap-2">
                    <Badge variant={getSentimentVariant(item.analysis?.sentiment || 'neutral')} className="gap-1.5 capitalize">
                        {getSentimentIcon(item.analysis?.sentiment || 'neutral')}
                        {item.analysis?.sentiment || 'neutral'}
                    </Badge>
                </div>
            </div>

            <a
                href={item.url}
                target="_blank"
                rel="noopener noreferrer"
                className="block group-hover:text-primary transition-colors mb-3"
            >
                <h3 className="text-sm font-bold text-foreground leading-tight flex items-center gap-2">
                    {item.title}
                    <ExternalLink size={12} className="opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
                </h3>
            </a>

            <div className="flex flex-wrap gap-1.5 mb-3">
                {/* Source Tier First */}
                {item.categories.filter(cat => cat === 'trusted_news').map(cat => {
                    const styles = getCategoryStyles(cat);
                    return (
                        <Badge key={cat} variant={styles.variant} className="gap-1.5">
                            {styles.icon}
                            {cat.replace('_', ' ')}
                        </Badge>
                    );
                })}
                {/* Intent/Signal Tiers */}
                {item.categories.filter(cat => cat !== 'trusted_news').map(cat => {
                    const styles = getCategoryStyles(cat);
                    return (
                        <Badge key={cat} variant={styles.variant} className="gap-1.5">
                            {styles.icon}
                            {cat.replace('_', ' ')}
                        </Badge>
                    );
                })}
            </div>

            <p className="text-xs text-muted-foreground leading-relaxed mb-4 line-clamp-3">
                {item.snippet}
            </p>

            {item.analysis && (
                <div className="bg-muted/50 border border-border/20 rounded-lg p-4 mb-4">
                    {/* Header */}
                    <div className="flex items-center justify-between border-b border-border/20 pb-3 mb-4">
                        <div className="flex items-center gap-2">
                            <Info size={12} className="text-primary" />
                            <span className="text-xs font-bold text-muted-foreground uppercase tracking-[0.2em]">AI Evidence Extraction</span>
                        </div>
                        <div className="flex items-center gap-2">
                            <span className="text-xs text-muted-foreground font-bold uppercase">Impact</span>
                            <Badge variant={getImpactVariant(item.analysis.impact_level)}>{item.analysis.impact_level}</Badge>
                        </div>
                    </div>

                    {/* Core Event */}
                    {item.analysis.key_event && (
                        <div className="flex items-start gap-2 mb-4 pb-4 border-b border-border/20">
                            <AlertCircle size={12} className="text-warning mt-0.5 shrink-0" />
                            <div>
                                <div className="text-xs text-muted-foreground font-bold uppercase tracking-tight">Core Event Identified</div>
                                <div className="text-xs text-foreground font-medium">{item.analysis.key_event}</div>
                            </div>
                        </div>
                    )}

                    {/* Summary Quote */}
                    <div className="mb-4 pb-4 border-b border-border/20">
                        <div className="text-xs text-muted-foreground leading-relaxed italic border-l-2 border-border/30 pl-3">
                            &quot;{item.analysis.summary}&quot;
                        </div>
                    </div>

                    {/* Key Evidence */}
                    {item.analysis.key_facts && item.analysis.key_facts.length > 0 && (
                        <KeyEvidenceSection facts={item.analysis.key_facts} />
                    )}

                    {/* Reasoning Footer */}
                    <div className="text-xs text-muted-foreground leading-relaxed opacity-80 pt-2">
                        <span className="font-bold uppercase tracking-tighter text-muted-foreground mr-1">Analyst Reasoning:</span>
                        {item.analysis.reasoning}
                    </div>
                </div>
            )}

            <div className="flex flex-wrap gap-2 items-center">
                {item.tags.map(tag => (
                    <Badge key={tag} variant="outline" className="gap-1">
                        <Tag size={8} />
                        {tag}
                    </Badge>
                ))}

                {item.related_tickers.length > 0 && (
                    <div className="ml-auto flex flex-wrap gap-1">
                        {item.related_tickers.map(entity => (
                            <Badge
                                key={entity.ticker}
                                variant="outline"
                                title={`${entity.company_name} (${(entity.relevance_score * 100).toFixed(0)}% relevance)`}
                            >
                                {entity.ticker}
                            </Badge>
                        ))}
                    </div>
                )}
            </div>
        </Card>
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
        <div key={`${keyPrefix}-${idx}`} className="grid gap-2 rounded-md bg-background p-3 text-sm">
            <div className="flex items-start gap-2">
                {fact.is_quantitative ? <BarChart3 size={12} className="shrink-0 text-primary mt-0.5" /> : <MessageSquare size={12} className="shrink-0 text-border mt-0.5" />}
                <div className="flex min-w-0 flex-1 flex-wrap items-start justify-between gap-2 leading-normal">
                    <span className="font-medium text-foreground">{fact.content}</span>
                    <Badge variant={fact.sentiment === 'bullish' ? 'success' : fact.sentiment === 'bearish' ? 'destructive' : 'outline'} className="capitalize">
                        {fact.sentiment}
                    </Badge>
                </div>
            </div>
            {fact.citation && (
                <div className="text-xs text-muted-foreground/70 pl-5 border-t border-border/20 pt-1 mt-1 truncate">
                    Source: {fact.citation}
                </div>
            )}
        </div>
    );

    return (
        <div className="space-y-3 mb-4">
            <div className="text-xs text-muted-foreground font-bold uppercase tracking-[0.2em] flex items-center gap-1.5">
                <BarChart3 size={10} className="text-border" />
                Key Evidence
                <span className="text-border">({facts.length})</span>
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
                <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="w-full"
                    aria-expanded={isExpanded}
                    onClick={() => setIsExpanded((expanded) => !expanded)}
                >
                    {isExpanded ? 'Show less' : `Show ${hiddenCount} more`}
                    <ChevronDown className={`size-4 transition-transform ${isExpanded ? 'rotate-180' : ''}`} />
                </Button>
            )}
        </div>
    );
};

// Export with React.memo for performance optimization
export const NewsResearchCard = memo(NewsResearchCardComponent);
