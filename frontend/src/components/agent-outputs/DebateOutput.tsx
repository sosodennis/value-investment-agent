import React, { memo } from 'react';
import { Shield, Target, AlertTriangle, TrendingUp, TrendingDown, Minus, Info, CheckCircle2, Zap, Loader2 } from 'lucide-react';
import { DebateAgentOutput, DebateSuccess } from '@/types/agents/debate';
import { StandardAgentOutput, AgentStatus } from '@/types/agents';
import { useArtifact } from '../../hooks/useArtifact';

interface DebateOutputProps {
    output: StandardAgentOutput | null;
    resolvedTicker?: string | null;
    status: AgentStatus;
}

const DebateOutputComponent: React.FC<DebateOutputProps> = ({ output, resolvedTicker, status }) => {
    // 1. Determine if we have a reference to fetch
    const reference = (output as any)?.reference || (output as any)?.artifact?.reference;
    const preview = (output as any)?.preview || (output as any)?.artifact?.preview || (output as any);

    // 2. Fetch artifact if reference exists
    const { data: artifactData, isLoading: isArtifactLoading } = useArtifact<DebateSuccess>(
        reference?.artifact_id
    );

    // 3. Resolve the actual data to display (Artifact > Preview)
    const effectiveOutput = artifactData || preview;

    const isPreviewOnly = !artifactData && !!preview;
    const hasData = effectiveOutput && (
        (effectiveOutput.final_verdict && effectiveOutput.scenario_analysis) ||
        isPreviewOnly
    );

    if ((status !== 'done' && !hasData) || !effectiveOutput || (!artifactData && !isPreviewOnly)) {
        return (
            <div className="flex flex-col items-center justify-center h-full text-slate-500 py-12 min-h-[400px]">
                <Shield size={48} className="text-slate-800 mb-4 opacity-50 animate-pulse" />
                <p className="text-sm font-bold uppercase tracking-widest">Debate in Progress</p>
                <p className="text-[10px] mt-2 opacity-60">Wait for the debate between Bull and Bear agents to conclude.</p>
                <p className="text-[10px] text-slate-600 mt-2">Status: {status}</p>
            </div>
        );
    }

    const conclusion = effectiveOutput;
    const direction = conclusion.final_verdict;
    const scenarios = conclusion.scenario_analysis || {};

    const getDirectionStyles = () => {
        switch (direction) {
            case 'STRONG_LONG':
                return {
                    color: 'text-emerald-400',
                    bg: 'bg-emerald-500/20',
                    border: 'border-emerald-500/40',
                    accent: 'text-emerald-300',
                    icon: <TrendingUp size={20} className="text-emerald-400 animate-pulse" />,
                };
            case 'LONG':
                return {
                    color: 'text-emerald-400',
                    bg: 'bg-emerald-500/10',
                    border: 'border-emerald-500/20',
                    accent: 'text-emerald-400',
                    icon: <TrendingUp size={20} className="text-emerald-500" />,
                };
            case 'STRONG_SHORT':
                return {
                    color: 'text-rose-400',
                    bg: 'bg-rose-500/20',
                    border: 'border-rose-500/40',
                    accent: 'text-rose-300',
                    icon: <TrendingDown size={20} className="text-rose-400 animate-pulse" />,
                };
            case 'SHORT':
                return {
                    color: 'text-rose-400',
                    bg: 'bg-rose-500/10',
                    border: 'border-rose-500/20',
                    accent: 'text-rose-400',
                    icon: <TrendingDown size={20} className="text-rose-500" />,
                };
            case 'AVOID':
                return {
                    color: 'text-amber-400',
                    bg: 'bg-amber-500/10',
                    border: 'border-amber-500/20',
                    accent: 'text-amber-400',
                    icon: <AlertTriangle size={20} className="text-amber-500" />,
                };
            default:
                return {
                    color: 'text-slate-400',
                    bg: 'bg-slate-500/10',
                    border: 'border-slate-500/20',
                    accent: 'text-slate-400',
                    icon: <Minus size={20} className="text-slate-500" />,
                };
        }
    };

    const styles = getDirectionStyles();
    const isReferenceLoading = reference && isArtifactLoading && !artifactData;

    return (
        <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-700 pb-12">
            <div className={`rounded-2xl border p-6 backdrop-blur-md ${styles.bg} ${styles.border} relative overflow-hidden`}>
                <div className="absolute top-0 right-0 p-4">
                    <div className="px-2 py-0.5 rounded border border-white/10 bg-white/5 text-[9px] font-bold text-slate-400 uppercase tracking-widest">
                        {conclusion.risk_profile?.replace('_', ' ')}
                    </div>
                </div>

                <div className="flex items-center justify-between mb-6">
                    <div className="flex items-center gap-3">
                        <Shield size={18} className="text-cyan-400" />
                        <h3 className="text-sm font-bold text-white uppercase tracking-widest">Investment Verdict</h3>
                    </div>
                    <div className="flex items-center gap-2">
                        {isReferenceLoading && (
                            <div className="px-3 py-1 rounded bg-slate-900/50 border border-slate-800 text-[9px] font-bold text-cyan-500 uppercase tracking-widest flex items-center gap-2 animate-pulse">
                                <Loader2 size={10} className="animate-spin" /> Async Fetching...
                            </div>
                        )}
                        <div className={`px-4 py-1.5 rounded-full border text-xs font-bold uppercase tracking-widest bg-slate-950/40 ${styles.border} ${styles.color}`}>
                            {direction}
                        </div>
                        {conclusion.data_quality_warning && (
                            <div className="px-2 py-1 rounded border border-amber-500/40 bg-amber-500/10 text-[9px] font-black text-amber-400 uppercase tracking-widest flex items-center gap-1">
                                <AlertTriangle size={10} /> Data Issue
                            </div>
                        )}
                    </div>
                </div>

                <div className="space-y-4 mb-6">
                    <div className="flex items-center justify-between">
                        <h4 className="text-[10px] font-bold text-slate-500 uppercase tracking-widest flex items-center gap-2">
                            <Info size={12} /> Asymmetric Reward/Risk Model
                        </h4>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        <div className="flex flex-col gap-1 p-3 bg-slate-800/30 rounded-lg border border-slate-700/30 overflow-hidden relative group">
                            <div className="absolute inset-y-0 left-0 w-1 bg-amber-500" />
                            <div className="flex items-center justify-between">
                                <span className="text-white font-bold uppercase tracking-tighter text-[10px]">Reward/Risk Ratio:</span>
                                <span className="text-amber-400 font-black text-lg">
                                    {conclusion.rr_ratio ? conclusion.rr_ratio.toFixed(2) + 'x' : 'N/A'}
                                </span>
                            </div>
                            <p className="text-[8px] text-slate-500 uppercase tracking-widest mt-1">
                                {isPreviewOnly ? 'L3 DATA LOADING...' : 'weighted upside vs downside'}
                            </p>
                        </div>

                        <div className="flex flex-col gap-1 p-3 bg-slate-800/30 rounded-lg border border-slate-700/30 overflow-hidden relative group">
                            <div className="absolute inset-y-0 left-0 w-1 bg-cyan-500" />
                            <div className="flex items-center justify-between">
                                <span className="text-white font-bold uppercase tracking-tighter text-[10px]">Edge (Alpha):</span>
                                <span className={`${(conclusion.alpha ?? 0) > 0 ? 'text-emerald-400' : 'text-rose-400'} font-black text-lg`}>
                                    {conclusion.alpha !== undefined ? (conclusion.alpha * 100).toFixed(1) + '%' : 'N/A'}
                                </span>
                            </div>
                            <p className="text-[8px] text-slate-500 uppercase tracking-widest mt-1">
                                {isPreviewOnly ? 'L3 DATA LOADING...' : `vs ${((conclusion.risk_free_benchmark ?? 0) * 400).toFixed(1)}% risk-free rate`}
                            </p>
                        </div>
                    </div>

                    {isPreviewOnly ? (
                        <div className="py-4 border-y border-white/5 my-4">
                            <div className="flex items-center gap-3 mb-2">
                                <Zap size={14} className="text-amber-400" />
                                <span className="text-[11px] font-bold text-white uppercase tracking-widest">Verdict Summary (Preview)</span>
                            </div>
                            <p className="text-xs text-slate-300 italic leading-relaxed">
                                {(preview as any).verdict_display || 'Calculating probability cases...'}
                            </p>
                            <p className="text-[10px] text-slate-500 mt-2">
                                {(preview as any).debate_rounds_display}
                            </p>
                        </div>
                    ) : (
                        <div className="grid grid-cols-1 gap-3 mt-4">
                            <div className="space-y-1.5">
                                <div className="flex justify-between text-[10px] uppercase font-bold tracking-tight">
                                    <span className="text-emerald-400">Bull Case ({scenarios.bull_case?.price_implication})</span>
                                    <span className="text-emerald-500">
                                        {scenarios.bull_case?.probability}%
                                    </span>
                                </div>
                                <div className="h-1.5 w-full bg-slate-800 rounded-full overflow-hidden">
                                    <div
                                        className="h-full bg-emerald-500 transition-all duration-1000"
                                        style={{ width: `${scenarios.bull_case?.probability}%` }}
                                    />
                                </div>
                                <p className="text-[9px] text-slate-500 leading-tight italic">{scenarios.bull_case?.outcome_description}</p>
                            </div>

                            <div className="space-y-1.5">
                                <div className="flex justify-between text-[10px] uppercase font-bold tracking-tight">
                                    <span className="text-slate-400">Base Case (Neutral)</span>
                                    <span className="text-slate-400">
                                        {scenarios.base_case?.probability}%
                                    </span>
                                </div>
                                <div className="h-1.5 w-full bg-slate-800 rounded-full overflow-hidden">
                                    <div
                                        className="h-full bg-slate-500 transition-all duration-1000"
                                        style={{ width: `${scenarios.base_case?.probability}%` }}
                                    />
                                </div>
                                <p className="text-[9px] text-slate-500 leading-tight italic">{scenarios.base_case?.outcome_description}</p>
                            </div>

                            <div className="space-y-1.5">
                                <div className="flex justify-between text-[10px] uppercase font-bold tracking-tight">
                                    <span className="text-rose-400">Bear Case ({scenarios.bear_case?.price_implication})</span>
                                    <span className="text-rose-500">
                                        {scenarios.bear_case?.probability}%
                                    </span>
                                </div>
                                <div className="h-1.5 w-full bg-slate-800 rounded-full overflow-hidden">
                                    <div
                                        className="h-full bg-rose-500 transition-all duration-1000"
                                        style={{ width: `${scenarios.bear_case?.probability}%` }}
                                    />
                                </div>
                                <p className="text-[9px] text-slate-500 leading-tight italic">{scenarios.bear_case?.outcome_description}</p>
                            </div>
                        </div>
                    )}
                </div>

                <div className="h-px bg-white/5 mb-4" />

                <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-widest">
                    <span className="text-slate-500">Conviction Score:</span>
                    <span className={`${styles.color} text-sm font-black`}>
                        {conclusion.conviction ?? 50}%
                    </span>
                    <span className="text-slate-400 ml-auto font-mono">
                        {conclusion.model_summary || `Pragmatic V2.0 (Round ${conclusion.debate_rounds})`}
                    </span>
                </div>
            </div>

            <div className="grid grid-cols-1 gap-6">
                <div className="bg-slate-900/40 border border-slate-800/50 rounded-2xl p-6 relative overflow-hidden group">
                    <div className="absolute top-0 right-0 p-8 opacity-[0.03] group-hover:opacity-[0.05] transition-opacity">
                        <Shield size={120} />
                    </div>
                    <div className="flex items-center gap-2 mb-4">
                        <div className="p-1.5 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
                            <CheckCircle2 size={14} className="text-emerald-400" />
                        </div>
                        <h4 className="text-[10px] font-bold text-emerald-400 uppercase tracking-widest">Winning Investment Thesis</h4>
                    </div>
                    <p className="text-sm text-slate-200 leading-relaxed font-medium relative z-10 italic">
                        &quot;{isPreviewOnly ? (preview as any).thesis_display : conclusion.winning_thesis}&quot;
                    </p>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <div className="bg-slate-900/40 border border-slate-800/50 rounded-2xl p-6 group">
                        <div className="flex items-center gap-2 mb-4">
                            <div className="p-1.5 rounded-lg bg-cyan-500/10 border border-cyan-500/20">
                                <Target size={14} className="text-cyan-400" />
                            </div>
                            <h4 className="text-[10px] font-bold text-cyan-400 uppercase tracking-widest">Primary Catalyst</h4>
                        </div>
                        <p className="text-xs text-slate-300 leading-relaxed group-hover:text-white transition-colors">
                            {isPreviewOnly ? (preview as any).catalyst_display : conclusion.primary_catalyst}
                        </p>
                    </div>

                    <div className="bg-slate-900/40 border border-slate-800/50 rounded-2xl p-6 group border-rose-500/10">
                        <div className="flex items-center gap-2 mb-4">
                            <div className="p-1.5 rounded-lg bg-rose-500/10 border border-rose-500/20">
                                <AlertTriangle size={14} className="text-rose-400" />
                            </div>
                            <h4 className="text-[10px] font-bold text-rose-400 uppercase tracking-widest">Critical Failure Mode</h4>
                        </div>
                        <p className="text-xs text-rose-200/80 leading-relaxed group-hover:text-rose-100 transition-colors font-medium">
                            {isPreviewOnly ? (preview as any).risk_display : conclusion.primary_risk}
                        </p>
                    </div>
                </div>
            </div>

            <div className="bg-slate-950/30 border border-slate-900 rounded-2xl p-6">
                <div className="flex items-center gap-2 mb-6">
                    <Info size={14} className="text-slate-500" />
                    <h4 className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Supporting Audit Factors</h4>
                </div>
                <div className="space-y-3">
                    {conclusion.supporting_factors?.map((factor: string, i: number) => (
                        <div key={i} className="flex gap-3 text-xs text-slate-400 hover:text-slate-300 transition-colors p-3 bg-slate-900/20 rounded-xl border border-slate-800/30">
                            <div className="w-1.5 h-1.5 rounded-full bg-slate-700 mt-1.5 shrink-0" />
                            <p className="leading-relaxed">{factor}</p>
                        </div>
                    ))}
                    {(!conclusion.supporting_factors || conclusion.supporting_factors.length === 0) && (
                        <p className="text-[10px] text-slate-600 italic">No secondary factors recorded.</p>
                    )}
                </div>
            </div>

            <div className="flex items-center justify-between px-2 text-[9px] font-bold text-slate-700 uppercase tracking-[0.2em]">
                <div>Ticker: {resolvedTicker || 'N/A'}</div>
                <div className="flex items-center gap-2 opacity-40">
                    <Zap size={10} />
                    <span>Pragmatic V2.0 Engine Active</span>
                </div>
            </div>
        </div>
    );
};

export const DebateOutput = memo(DebateOutputComponent);
