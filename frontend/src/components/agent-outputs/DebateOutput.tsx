import React, { memo } from 'react';
import { Shield, Target, AlertTriangle, TrendingUp, TrendingDown, Minus, Info, CheckCircle2, Zap, Loader2 } from 'lucide-react';
import { DebateSuccess } from '@/types/agents/debate';
import { DebateTranscript } from './DebateTranscript';
import { DebateFactSheet } from './DebateFactSheet';
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
            <div className={`tech-card p-6 ${styles.bg} ${styles.border} relative overflow-hidden animate-slide-up`}>
                <div className="absolute top-0 right-0 p-4">
                    <div className="px-2 py-0.5 rounded-full border border-white/10 bg-white/5 text-[8px] font-black text-slate-400 uppercase tracking-widest">
                        {conclusion.risk_profile?.replace('_', ' ')}
                    </div>
                </div>

                <div className="flex items-center justify-between mb-8">
                    <div className="flex items-center gap-3">
                        <Shield size={18} className="text-cyan-400" />
                        <h3 className="text-label text-white">Investment Verdict</h3>
                    </div>
                    <div className="flex items-center gap-2">
                        {isReferenceLoading && (
                            <div className="px-3 py-1 rounded bg-slate-900/50 border border-slate-800 text-[9px] font-bold text-cyan-500 uppercase tracking-widest flex items-center gap-2 animate-pulse">
                                <Loader2 size={10} className="animate-spin" /> Fetching L3...
                            </div>
                        )}
                        <div className={`px-4 py-1.5 rounded-full border text-[10px] font-black uppercase tracking-[0.2em] bg-slate-950/40 ${styles.border} ${styles.color} shadow-lg shadow-black/20`}>
                            {direction}
                        </div>
                        {conclusion.data_quality_warning && (
                            <div className="px-2 py-1 rounded border border-amber-500/40 bg-amber-500/10 text-[9px] font-black text-amber-400 uppercase tracking-widest flex items-center gap-1">
                                <AlertTriangle size={10} /> Data Alert
                            </div>
                        )}
                    </div>
                </div>

                <div className="space-y-6 mb-8">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div className="tech-card p-4 bg-slate-950/40 group relative">
                            <div className="absolute inset-y-0 left-0 w-0.5 bg-amber-500 shadow-[2px_0_10px_rgba(245,158,11,0.4)]" />
                            <div className="flex items-center justify-between mb-1">
                                <span className="text-label text-slate-400">Reward/Risk Ratio</span>
                                <span className="text-amber-400 font-black text-xl">
                                    {conclusion.rr_ratio ? conclusion.rr_ratio.toFixed(2) + 'x' : 'N/A'}
                                </span>
                            </div>
                            <div className="text-[8px] text-slate-600 uppercase tracking-widest font-mono">
                                {isPreviewOnly ? 'ASYMMETRY CALC_PENDING' : 'WTD_UPSIDE vs WTD_DOWNSIDE'}
                            </div>
                        </div>

                        <div className="tech-card p-4 bg-slate-950/40 group relative">
                            <div className="absolute inset-y-0 left-0 w-0.5 bg-cyan-500 shadow-[2px_0_10px_rgba(6,182,212,0.4)]" />
                            <div className="flex items-center justify-between mb-1">
                                <span className="text-label text-slate-400">Edge (Alpha)</span>
                                <span className={`${(conclusion.alpha ?? 0) > 0 ? 'text-emerald-400' : 'text-rose-400'} font-black text-xl`}>
                                    {conclusion.alpha !== undefined ? (conclusion.alpha * 100).toFixed(1) + '%' : 'N/A'}
                                </span>
                            </div>
                            <div className="text-[8px] text-slate-600 uppercase tracking-widest font-mono">
                                {isPreviewOnly ? 'MARKET_EDGE_ESTIMATING' : `vs ${((conclusion.risk_free_benchmark ?? 0) * 400).toFixed(1)}% RF_RATE`}
                            </div>
                        </div>
                    </div>

                    {isPreviewOnly ? (
                        <div className="tech-card p-5 bg-amber-500/5 border-amber-500/10">
                            <div className="flex items-center gap-3 mb-3">
                                <Zap size={14} className="text-amber-400 animate-pulse" />
                                <span className="text-label text-white">Verdict Summary (Simulation)</span>
                            </div>
                            <p className="text-sm text-slate-300 italic leading-relaxed font-serif">
                                &quot;{(preview as any).verdict_display || 'Calculating probability cases...'}&quot;
                            </p>
                            <p className="text-[9px] text-slate-500 mt-3 font-mono">
                                {(preview as any).debate_rounds_display}
                            </p>
                        </div>
                    ) : (
                        <div className="space-y-4">
                            <div className="space-y-2">
                                <div className="flex justify-between text-[10px] font-black uppercase tracking-widest">
                                    <span className="text-emerald-400 flex items-center gap-1.5">
                                        <div className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                                        Bull Case ({scenarios.bull_case?.price_implication})
                                    </span>
                                    <span className="text-emerald-400">{scenarios.bull_case?.probability}%</span>
                                </div>
                                <div className="h-1.5 w-full bg-slate-900/60 rounded-full overflow-hidden border border-white/5">
                                    <div className="h-full bg-emerald-500 shadow-[0_0_10px_rgba(16,185,129,0.4)]" style={{ width: `${scenarios.bull_case?.probability}%` }} />
                                </div>
                                <p className="text-[10px] text-slate-400 leading-relaxed italic">&quot;{scenarios.bull_case?.outcome_description}&quot;</p>
                            </div>

                            <div className="space-y-2 opacity-80">
                                <div className="flex justify-between text-[10px] font-black uppercase tracking-widest">
                                    <span className="text-slate-400 flex items-center gap-1.5">
                                        <div className="w-1.5 h-1.5 rounded-full bg-slate-500" />
                                        Base Case (Neutral)
                                    </span>
                                    <span className="text-slate-400">{scenarios.base_case?.probability}%</span>
                                </div>
                                <div className="h-1 w-full bg-slate-900/60 rounded-full overflow-hidden border border-white/5">
                                    <div className="h-full bg-slate-500" style={{ width: `${scenarios.base_case?.probability}%` }} />
                                </div>
                                <p className="text-[10px] text-slate-500 leading-relaxed italic">&quot;{scenarios.base_case?.outcome_description}&quot;</p>
                            </div>

                            <div className="space-y-2">
                                <div className="flex justify-between text-[10px] font-black uppercase tracking-widest">
                                    <span className="text-rose-400 flex items-center gap-1.5">
                                        <div className="w-1.5 h-1.5 rounded-full bg-rose-500" />
                                        Bear Case ({scenarios.bear_case?.price_implication})
                                    </span>
                                    <span className="text-rose-400">{scenarios.bear_case?.probability}%</span>
                                </div>
                                <div className="h-1.5 w-full bg-slate-900/60 rounded-full overflow-hidden border border-white/5">
                                    <div className="h-full bg-rose-500 shadow-[0_0_10px_rgba(244,63,94,0.4)]" style={{ width: `${scenarios.bear_case?.probability}%` }} />
                                </div>
                                <p className="text-[10px] text-rose-300/60 leading-relaxed italic">&quot;{scenarios.bear_case?.outcome_description}&quot;</p>
                            </div>
                        </div>
                    )}
                </div>

                <div className="h-px bg-white/5 mb-6" />

                <div className="flex items-center justify-between text-[9px] font-black uppercase tracking-[0.2em]">
                    <div className="flex items-center gap-3">
                        <span className="text-slate-600">Conf_Level:</span>
                        <span className={`${styles.color} text-sm`}>{conclusion.conviction ?? 50}%</span>
                    </div>
                    <div className="flex items-center gap-3">
                        <span className="text-slate-600">Sys_Model:</span>
                        <span className="text-slate-400 font-mono tracking-normal">{conclusion.model_summary || `PRAGMATIC V2.0 (ROUND ${conclusion.debate_rounds})`}</span>
                    </div>
                </div>
            </div>

            <div className="grid grid-cols-1 gap-6">
                <div className="tech-card p-8 bg-slate-900/40 relative overflow-hidden group">
                    <div className="absolute top-0 right-0 p-8 opacity-[0.03] group-hover:opacity-[0.1] transition-opacity duration-700">
                        <Shield size={160} />
                    </div>
                    <div className="flex items-center gap-3 mb-5 relative z-10">
                        <div className="p-2 rounded-xl bg-emerald-500/10 border border-emerald-500/20 shadow-[0_0_15px_rgba(16,185,129,0.1)]">
                            <CheckCircle2 size={16} className="text-emerald-400" />
                        </div>
                        <h4 className="text-label text-emerald-400">Dominant Thesis</h4>
                    </div>
                    <p className="text-base text-white leading-relaxed font-black tracking-tight relative z-10 italic">
                        &quot;{isPreviewOnly ? (preview as any).thesis_display : conclusion.winning_thesis}&quot;
                    </p>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <div className="tech-card p-6 bg-slate-900/40 group hover:border-cyan-500/20 hover:bg-slate-900/60 transition-all duration-500">
                        <div className="flex items-center gap-3 mb-4">
                            <div className="p-2 rounded-xl bg-cyan-500/10 border border-cyan-500/20 group-hover:shadow-[0_0_15px_rgba(6,182,212,0.1)]">
                                <Target size={16} className="text-cyan-400" />
                            </div>
                            <h4 className="text-label text-cyan-400">Primary Catalyst</h4>
                        </div>
                        <p className="text-sm text-slate-300 leading-relaxed group-hover:text-white transition-colors duration-300">
                            {isPreviewOnly ? (preview as any).catalyst_display : conclusion.primary_catalyst}
                        </p>
                    </div>

                    <div className="tech-card p-6 bg-slate-900/20 group border-rose-500/10 hover:border-rose-500/30 hover:bg-rose-950/5 transition-all duration-500">
                        <div className="flex items-center gap-3 mb-4">
                            <div className="p-2 rounded-xl bg-rose-500/10 border border-rose-500/20 group-hover:shadow-[0_0_15px_rgba(244,63,94,0.1)] transition-all">
                                <AlertTriangle size={16} className="text-rose-400" />
                            </div>
                            <h4 className="text-label text-rose-400">Risk Vectors</h4>
                        </div>
                        <p className="text-sm text-rose-100/70 leading-relaxed group-hover:text-rose-100 transition-colors duration-300 font-medium">
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

            {/* Debate Transcript (History) */}
            {(effectiveOutput as any).history && (effectiveOutput as any).history.length > 0 && (
                <DebateTranscript history={(effectiveOutput as any).history} />
            )}

            {/* Fact Registry */}
            {effectiveOutput.facts && effectiveOutput.facts.length > 0 && (
                <DebateFactSheet facts={effectiveOutput.facts} />
            )}
        </div>
    );
};

export const DebateOutput = memo(DebateOutputComponent);
