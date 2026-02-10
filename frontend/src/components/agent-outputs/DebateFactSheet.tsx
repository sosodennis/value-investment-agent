
import React from 'react';
import { Database, Newspaper, BarChart4, ExternalLink, ShieldCheck } from 'lucide-react';

interface EvidenceFact {
    fact_id: string;
    source_type: 'financials' | 'news' | 'technicals';
    source_weight: 'HIGH' | 'MEDIUM' | 'LOW';
    summary: string;
    value?: string | number;
    period?: string;
    provenance?: any;
}

interface DebateFactSheetProps {
    facts: EvidenceFact[];
}

const FactItem = ({ fact }: { fact: EvidenceFact }) => {
    const getTypeColor = () => {
        switch (fact.source_type) {
            case 'financials': return 'bg-emerald-500/10 text-emerald-400 border-emerald-500/25';
            case 'news': return 'bg-cyan-500/10 text-cyan-400 border-cyan-500/25';
            case 'technicals': return 'bg-amber-500/10 text-amber-400 border-amber-500/25';
            default: return 'bg-slate-500/10 text-slate-400 border-slate-500/20';
        }
    };

    const getBadgeIcon = () => {
        switch (fact.source_type) {
            case 'financials': return <Database className="w-2.5 h-2.5 text-current" />;
            case 'news': return <Newspaper className="w-2.5 h-2.5 text-current" />;
            case 'technicals': return <BarChart4 className="w-2.5 h-2.5 text-current" />;
            default: return <ShieldCheck className="w-2.5 h-2.5 text-current" />;
        }
    };

    const getIcon = () => {
        switch (fact.source_type) {
            case 'financials': return <Database className="w-3 h-3 text-emerald-400" />;
            case 'news': return <Newspaper className="w-3 h-3 text-cyan-400" />;
            case 'technicals': return <BarChart4 className="w-3 h-3 text-amber-400" />;
            default: return <ShieldCheck className="w-3 h-3 text-slate-400" />;
        }
    };

    return (
        <div
            id={`fact-${fact.fact_id}`}
            data-fact-id={fact.fact_id}
            className="group bg-slate-900/40 border border-white/5 rounded-xl p-4 hover:border-white/10 transition-all duration-300 scroll-mt-6"
        >
            <div className="flex items-start justify-between gap-4">
                <div className="flex flex-col gap-2 flex-grow">
                    <div className="flex items-center gap-2">
                        <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[8px] font-black tracking-widest uppercase ${getTypeColor()}`}>
                            {getBadgeIcon()}
                            {fact.fact_id}
                        </span>
                        <span className="px-1.5 py-0.5 rounded border text-[8px] font-black tracking-widest uppercase bg-white/5 text-slate-500 border-white/10">
                            {fact.source_weight}
                        </span>
                        <div className="h-3 w-px bg-white/5" />
                        <span className="text-[10px] text-slate-500 uppercase tracking-wider font-mono">
                            {fact.period || 'CURRENT'}
                        </span>
                    </div>
                    <p className="text-sm text-slate-200 leading-snug">
                        {fact.summary}
                    </p>
                    {fact.value !== undefined && fact.value !== null && fact.value !== '' && (
                        <div className="text-xs font-mono text-cyan-400/80">
                            Metric: <span className="text-cyan-400">{fact.value}</span>
                        </div>
                    )}
                </div>
                <div className="flex flex-col items-end gap-2 shrink-0">
                    <div className={`p-2 rounded-lg bg-slate-950 border border-white/5 shadow-inner`}>
                        {getIcon()}
                    </div>
                    {fact.provenance && (
                        <button className="text-[8px] text-slate-500 flex items-center gap-1 hover:text-cyan-400 transition-colors uppercase tracking-widest">
                            <ExternalLink size={8} /> Source
                        </button>
                    )}
                </div>
            </div>
        </div>
    );
};

export const DebateFactSheet: React.FC<DebateFactSheetProps> = ({ facts }) => {
    if (!facts || facts.length === 0) return (
        <div className="text-center py-12 tech-card bg-slate-950/20">
            <ShieldCheck className="w-12 h-12 text-slate-800 mx-auto mb-4 opacity-20" />
            <p className="text-slate-500 text-xs uppercase tracking-widest font-bold">No evidence facts registry found</p>
        </div>
    );

    const financials = facts.filter(f => f.source_type === 'financials');
    const news = facts.filter(f => f.source_type === 'news');
    const technicals = facts.filter(f => f.source_type === 'technicals');

    return (
        <div className="space-y-8 animate-fade-in py-6">
            <div className="flex items-center justify-between border-b border-white/5 pb-4 px-2">
                <div className="flex items-center gap-3">
                    <div className="w-2 h-2 rounded-full bg-cyan-500 animate-pulse" />
                    <h3 className="text-xs font-black text-white uppercase tracking-[0.2em]">Validated Fact Registry</h3>
                </div>
                <span className="text-[10px] text-slate-600 font-mono">COUNT: {facts.length}</span>
            </div>

            {financials.length > 0 && (
                <div className="space-y-4">
                    <div className="flex items-center gap-3 px-2">
                        <Database className="w-4 h-4 text-emerald-500/60" />
                        <h4 className="text-[10px] font-black text-emerald-500/80 uppercase tracking-widest">Financial Data</h4>
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {financials.map(f => <FactItem key={f.fact_id} fact={f} />)}
                    </div>
                </div>
            )}

            {news.length > 0 && (
                <div className="space-y-4">
                    <div className="flex items-center gap-3 px-2">
                        <Newspaper className="w-4 h-4 text-cyan-500/60" />
                        <h4 className="text-[10px] font-black text-cyan-500/80 uppercase tracking-widest">Market News</h4>
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {news.map(f => <FactItem key={f.fact_id} fact={f} />)}
                    </div>
                </div>
            )}

            {technicals.length > 0 && (
                <div className="space-y-4">
                    <div className="flex items-center gap-3 px-2">
                        <BarChart4 className="w-4 h-4 text-amber-500/60" />
                        <h4 className="text-[10px] font-black text-amber-500/80 uppercase tracking-widest">Technical Indicators</h4>
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {technicals.map(f => <FactItem key={f.fact_id} fact={f} />)}
                    </div>
                </div>
            )}
        </div>
    );
};
