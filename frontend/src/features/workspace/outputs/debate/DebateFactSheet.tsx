
import React from 'react';
import { Database, Newspaper, BarChart4, ShieldCheck } from 'lucide-react';
import { EvidenceFact } from '@/types/agents/debate';
import type { BadgeProps } from '@/components/ui/badge';
import { Badge } from '@/components/ui/badge';
import { Card } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';

interface DebateFactSheetProps {
    facts: EvidenceFact[];
}

const FactItem = ({ fact }: { fact: EvidenceFact }) => {
    const getTypeVariant = (): NonNullable<BadgeProps['variant']> => {
        switch (fact.source_type) {
            case 'financials': return 'success';
            case 'news': return 'default';
            case 'technicals': return 'warning';
            case 'valuation': return 'outline';
        }
    };

    const getBadgeIcon = () => {
        switch (fact.source_type) {
            case 'financials': return <Database className="w-2.5 h-2.5 text-current" />;
            case 'news': return <Newspaper className="w-2.5 h-2.5 text-current" />;
            case 'technicals': return <BarChart4 className="w-2.5 h-2.5 text-current" />;
            case 'valuation': return <Database className="w-2.5 h-2.5 text-current" />;
            default: return <ShieldCheck className="w-2.5 h-2.5 text-current" />;
        }
    };

    const getIcon = () => {
        switch (fact.source_type) {
            case 'financials': return <Database className="w-3 h-3 text-success" />;
            case 'news': return <Newspaper className="w-3 h-3 text-primary" />;
            case 'technicals': return <BarChart4 className="w-3 h-3 text-warning" />;
            case 'valuation': return <Database className="w-3 h-3 text-primary" />;
            default: return <ShieldCheck className="w-3 h-3 text-muted-foreground" />;
        }
    };

    return (
        <Card
            id={`fact-${fact.fact_id}`}
            data-fact-id={fact.fact_id}
            tabIndex={-1}
            className="group scroll-mt-6 p-4 transition-colors hover:bg-muted/30 focus:outline-none focus:ring-2 focus:ring-ring"
        >
            <div className="flex items-start justify-between gap-4">
                <div className="flex flex-col gap-2 flex-grow min-w-0">
                    <div className="flex items-center gap-2">
                        <Badge variant={getTypeVariant()} className="gap-1">
                            {getBadgeIcon()}
                            {fact.fact_id}
                        </Badge>
                        <Badge variant="outline">
                            {fact.source_weight}
                        </Badge>
                        <span className="text-xs text-muted-foreground font-mono">
                            {fact.period || 'CURRENT'}
                        </span>
                    </div>
                    <p className="text-sm text-foreground leading-snug break-words">
                        {fact.summary}
                    </p>
                    {fact.value !== undefined && fact.value !== null && fact.value !== '' && (
                        <div className="text-xs font-mono text-muted-foreground break-words">
                            Metric: <span className="text-foreground">{fact.value}{fact.units ? ` ${fact.units}` : ''}</span>
                        </div>
                    )}
                </div>
                <div className="flex flex-col items-end gap-2 shrink-0">
                    <div className="p-2 rounded-md bg-muted/50 text-muted-foreground">
                        {getIcon()}
                    </div>
                    {fact.provenance && (
                        <details className="max-w-48 text-xs text-muted-foreground">
                            <summary className="cursor-pointer rounded-sm px-2 py-1 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                                Provenance
                            </summary>
                            <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-md bg-muted p-2 font-mono text-xs">
                                {JSON.stringify(fact.provenance, null, 2)}
                            </pre>
                        </details>
                    )}
                </div>
            </div>
        </Card>
    );
};

export const DebateFactSheet: React.FC<DebateFactSheetProps> = ({ facts }) => {
    if (!facts || facts.length === 0) {
        return (
            <EmptyState
                className="rounded-lg bg-muted/30 px-4 py-8"
                icon={<ShieldCheck aria-hidden="true" />}
                title="No evidence found"
                description="The debate report did not include evidence facts."
            />
        );
    }

    const financials = facts.filter(f => f.source_type === 'financials');
    const news = facts.filter(f => f.source_type === 'news');
    const technicals = facts.filter(f => f.source_type === 'technicals');
    const valuation = facts.filter(f => f.source_type === 'valuation');

    return (
        <div className="space-y-6 py-4">
            <div className="flex items-center justify-between gap-3">
                <h3 className="flex items-center gap-2 text-base font-semibold text-foreground">
                    <ShieldCheck aria-hidden="true" className="size-4 text-primary" />
                    Evidence
                </h3>
                <Badge variant="outline">{facts.length} facts</Badge>
            </div>

            {financials.length > 0 && (
                <div className="space-y-4">
                    <div className="flex items-center gap-2">
                        <Database className="size-4 text-success" />
                        <h4 className="text-sm font-medium">Financial data</h4>
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {financials.map(f => <FactItem key={f.fact_id} fact={f} />)}
                    </div>
                </div>
            )}

            {news.length > 0 && (
                <div className="space-y-4">
                    <div className="flex items-center gap-2">
                        <Newspaper className="size-4 text-primary" />
                        <h4 className="text-sm font-medium">Market news</h4>
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {news.map(f => <FactItem key={f.fact_id} fact={f} />)}
                    </div>
                </div>
            )}

            {technicals.length > 0 && (
                <div className="space-y-4">
                    <div className="flex items-center gap-2">
                        <BarChart4 className="size-4 text-warning" />
                        <h4 className="text-sm font-medium">Technical indicators</h4>
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {technicals.map(f => <FactItem key={f.fact_id} fact={f} />)}
                    </div>
                </div>
            )}

            {valuation.length > 0 && (
                <div className="space-y-4">
                    <div className="flex items-center gap-2">
                        <Database className="size-4 text-muted-foreground" />
                        <h4 className="text-sm font-medium">Valuation signals</h4>
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {valuation.map(f => <FactItem key={f.fact_id} fact={f} />)}
                    </div>
                </div>
            )}
        </div>
    );
};
