import React, { memo } from 'react';
import { Shield, Target, AlertTriangle, TrendingUp, TrendingDown, Minus, Info, CheckCircle2, Zap, Gavel } from 'lucide-react';
import { parseDebateArtifact } from '@/types/agents/artifact-parsers';
import { DebateTranscript } from './DebateTranscript';
import { DebateFactSheet } from './DebateFactSheet';
import { ArtifactReference, AgentStatus } from '@/types/agents';
import { useArtifact } from '../../../hooks/useArtifact';
import { DebatePreview } from '@/types/preview';
import { AgentLoadingState } from '../shared/AgentLoadingState';

interface DebateOutputProps {
    reference: ArtifactReference | null;
    previewData: DebatePreview | null;
    resolvedTicker?: string | null;
    status: AgentStatus;
}

const DebateOutputComponent: React.FC<DebateOutputProps> = ({
    reference,
    previewData,
    resolvedTicker,
    status
}) => {
    const { data: artifactData, isLoading: isArtifactLoading } = useArtifact(
        reference?.artifact_id,
        parseDebateArtifact,
        'debate_output.artifact',
        'debate_final_report'
    );

    const isPreviewOnly = !artifactData && !!previewData;
    const hasData = !!artifactData || isPreviewOnly;

    if ((status !== 'done' && !hasData) || (!artifactData && !isPreviewOnly)) {
        return (
            <AgentLoadingState
                type="full"
                icon={Gavel}
                title="Debate in Progress…"
                description="Wait for the debate between Bull and Bear agents to conclude."
                status={status}
                colorClass="text-amber-400"
            />
        );
    }

    const conclusion = artifactData;
    const direction = artifactData?.final_verdict || 'NEUTRAL';
    const scenarios = artifactData?.scenario_analysis;

    const getDirectionStyles = () => {
        switch (direction) {
            case 'STRONG_LONG':
                return {
                    tone: 'text-emerald-400',
                    chip: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400',
                    accentBar: 'bg-emerald-500/50',
                    icon: <TrendingUp size={20} className="text-emerald-400" />,
                };
            case 'LONG':
                return {
                    tone: 'text-emerald-400',
                    chip: 'border-emerald-500/20 bg-emerald-500/5 text-emerald-400',
                    accentBar: 'bg-emerald-500/40',
                    icon: <TrendingUp size={20} className="text-emerald-400" />,
                };
            case 'STRONG_SHORT':
                return {
                    tone: 'text-rose-400',
                    chip: 'border-rose-500/30 bg-rose-500/10 text-rose-400',
                    accentBar: 'bg-rose-500/50',
                    icon: <TrendingDown size={20} className="text-rose-400" />,
                };
            case 'SHORT':
                return {
                    tone: 'text-rose-400',
                    chip: 'border-rose-500/20 bg-rose-500/5 text-rose-400',
                    accentBar: 'bg-rose-500/40',
                    icon: <TrendingDown size={20} className="text-rose-400" />,
                };
            case 'AVOID':
                return {
                    tone: 'text-amber-400',
                    chip: 'border-amber-500/20 bg-amber-500/5 text-amber-400',
                    accentBar: 'bg-amber-500/40',
                    icon: <AlertTriangle size={20} className="text-amber-400" />,
                };
            default:
                return {
                    tone: 'text-on-surface-variant',
                    chip: 'border-outline-variant/40 bg-surface-container-low text-on-surface-variant',
                    accentBar: 'bg-outline-variant/40',
                    icon: <Minus size={20} className="text-outline" />,
                };
        }
    };

    const styles = getDirectionStyles();
    const isReferenceLoading = reference && isArtifactLoading && !artifactData;

    return (
        <div className="space-y-6 animate-fade-slide-up pb-12">
            <div className="flex items-center justify-between mb-6 px-2">
                <div className="flex items-center gap-3">
                    <Gavel size={18} className="text-amber-400" />
                    <h3 className="text-xs font-bold text-outline uppercase tracking-[0.2em]">Debate Council</h3>
                </div>
                <div className="flex items-center gap-2">
                    {isReferenceLoading && (
                        <AgentLoadingState
                            type="header"
                            title="Loading Verdict…"
                            colorClass="text-amber-400"
                        />
                    )}
                    {conclusion?.debate_rounds !== undefined && (
                        <span className="rounded border border-outline-variant/20 bg-surface-container-low px-2 py-1 text-[10px] font-semibold text-outline uppercase tracking-[0.2em]">
                            Rounds: {conclusion.debate_rounds}
                        </span>
                    )}
                </div>
            </div>

            <div className="relative overflow-hidden rounded-2xl border border-outline-variant/10 bg-surface-container p-6">
                <div className={`absolute inset-y-0 left-0 w-0.5 ${styles.accentBar}`} />
                <div className="absolute top-0 right-0 p-4">
                    <div className="px-2 py-0.5 rounded-full border border-outline-variant/30 bg-surface-container-low text-[8px] font-black text-on-surface-variant uppercase tracking-widest">
                        {conclusion?.risk_profile?.replace('_', ' ')}
                    </div>
                </div>

                <div className="flex items-center justify-between mb-8">
                    <div className="flex items-center gap-3">
                        <Shield size={18} className="text-amber-400" />
                        <h3 className="text-xs font-bold text-outline uppercase tracking-[0.2em]">Investment Verdict</h3>
                    </div>
                    <div className="flex items-center gap-2">
                        <div className={`px-3 py-1.5 rounded-full border text-[10px] font-bold uppercase tracking-[0.2em] ${styles.chip}`}>
                            {direction}
                        </div>
                        {conclusion?.data_quality_warning && (
                            <div className="px-2 py-1 rounded border border-amber-500/40 bg-amber-500/10 text-[9px] font-black text-amber-400 uppercase tracking-widest flex items-center gap-1">
                                <AlertTriangle size={10} /> Data Alert
                            </div>
                        )}
                    </div>
                </div>

                <div className="space-y-6 mb-8">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div className="rounded-xl border border-outline-variant/10 bg-surface-container-low p-4 relative">
                            <div className="absolute inset-y-0 left-0 w-0.5 bg-amber-500/70" />
                            <div className="flex items-center justify-between mb-1">
                                <span className="text-[10px] font-bold text-outline uppercase tracking-[0.2em]">Reward/Risk Ratio</span>
                                <span className="text-amber-400 font-black text-xl">
                                    {conclusion?.rr_ratio ? conclusion.rr_ratio.toFixed(2) + 'x' : 'N/A'}
                                </span>
                            </div>
                            <div className="text-[8px] text-outline uppercase tracking-widest font-mono">
                                {isPreviewOnly ? 'ASYMMETRY CALC_PENDING' : 'WTD_UPSIDE vs WTD_DOWNSIDE'}
                            </div>
                        </div>

                        <div className="rounded-xl border border-outline-variant/10 bg-surface-container-low p-4 relative">
                            <div className="absolute inset-y-0 left-0 w-0.5 bg-cyan-500/70" />
                            <div className="flex items-center justify-between mb-1">
                                <span className="text-[10px] font-bold text-outline uppercase tracking-[0.2em]">Edge (Alpha)</span>
                                <span className={`${(conclusion?.alpha ?? 0) > 0 ? 'text-emerald-400' : 'text-rose-400'} font-black text-xl`}>
                                    {conclusion?.alpha !== undefined ? (conclusion.alpha * 100).toFixed(1) + '%' : 'N/A'}
                                </span>
                            </div>
                            <div className="text-[8px] text-outline uppercase tracking-widest font-mono">
                                {isPreviewOnly ? 'MARKET_EDGE_ESTIMATING' : `vs ${((conclusion?.risk_free_benchmark ?? 0) * 400).toFixed(1)}% RF_RATE`}
                            </div>
                        </div>
                    </div>

                    {isPreviewOnly ? (
                        <div className="rounded-xl border border-outline-variant/10 bg-surface-container-low p-5">
                            <div className="flex items-center gap-3 mb-3">
                                <Zap size={14} className="text-amber-400" />
                                <span className="text-[10px] font-bold text-outline uppercase tracking-[0.2em]">Verdict Summary (Simulation)</span>
                            </div>
                            <p className="text-sm text-on-surface-variant italic leading-relaxed font-serif">
                                &quot;{previewData?.verdict_display || 'Calculating probability cases…'}&quot;
                            </p>
                            <p className="text-[9px] text-outline mt-3 font-mono">
                                {previewData?.debate_rounds_display}
                            </p>
                        </div>
                    ) : (
                        <div className="space-y-4">
                            <div className="space-y-2">
                                <div className="flex justify-between text-[10px] font-black uppercase tracking-widest">
                                    <span className="text-emerald-400 flex items-center gap-1.5">
                                        <div className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                                        Bull Case ({scenarios?.bull_case?.price_implication})
                                    </span>
                                    <span className="text-emerald-400">{scenarios?.bull_case?.probability}%</span>
                                </div>
                                <div className="h-1.5 w-full bg-surface-container rounded-full overflow-hidden border border-outline-variant/20">
                                    <div className="h-full bg-emerald-500 shadow-[0_0_10px_rgba(16,185,129,0.4)]" style={{ width: `${scenarios?.bull_case?.probability}%` }} />
                                </div>
                                <p className="text-[10px] text-on-surface-variant leading-relaxed italic">&quot;{scenarios?.bull_case?.outcome_description}&quot;</p>
                            </div>

                            <div className="space-y-2 opacity-80">
                                <div className="flex justify-between text-[10px] font-black uppercase tracking-widest">
                                    <span className="text-on-surface-variant flex items-center gap-1.5">
                                        <div className="w-1.5 h-1.5 rounded-full bg-slate-500" />
                                        Base Case (Neutral)
                                    </span>
                                    <span className="text-on-surface-variant">{scenarios?.base_case?.probability}%</span>
                                </div>
                                <div className="h-1 w-full bg-surface-container rounded-full overflow-hidden border border-outline-variant/20">
                                    <div className="h-full bg-slate-500" style={{ width: `${scenarios?.base_case?.probability}%` }} />
                                </div>
                                <p className="text-[10px] text-outline leading-relaxed italic">&quot;{scenarios?.base_case?.outcome_description}&quot;</p>
                            </div>

                            <div className="space-y-2">
                                <div className="flex justify-between text-[10px] font-black uppercase tracking-widest">
                                    <span className="text-rose-400 flex items-center gap-1.5">
                                        <div className="w-1.5 h-1.5 rounded-full bg-rose-500" />
                                        Bear Case ({scenarios?.bear_case?.price_implication})
                                    </span>
                                    <span className="text-rose-400">{scenarios?.bear_case?.probability}%</span>
                                </div>
                                <div className="h-1.5 w-full bg-surface-container rounded-full overflow-hidden border border-outline-variant/20">
                                    <div className="h-full bg-rose-500 shadow-[0_0_10px_rgba(244,63,94,0.4)]" style={{ width: `${scenarios?.bear_case?.probability}%` }} />
                                </div>
                                <p className="text-[10px] text-rose-300/60 leading-relaxed italic">&quot;{scenarios?.bear_case?.outcome_description}&quot;</p>
                            </div>
                        </div>
                    )}
                </div>

                <div className="h-px bg-surface-container-low mb-6" />

                <div className="flex items-center justify-between text-[9px] font-black uppercase tracking-[0.2em]">
                    <div className="flex items-center gap-3">
                        <span className="text-outline">Conf_Level:</span>
                        <span className={`${styles.tone} text-sm`}>{conclusion?.conviction ?? 50}%</span>
                    </div>
                    <div className="flex items-center gap-3">
                        <span className="text-outline">Sys_Model:</span>
                        <span className="text-on-surface-variant font-mono tracking-normal">{conclusion?.model_summary || `PRAGMATIC V2.0 (ROUND ${conclusion?.debate_rounds ?? 0})`}</span>
                    </div>
                </div>
            </div>

            <div className="grid grid-cols-1 gap-6">
                <div className="rounded-2xl border border-outline-variant/10 bg-surface-container p-6 relative overflow-hidden group">
                    <div className="absolute top-0 right-0 p-8 opacity-[0.03] group-hover:opacity-[0.1] transition-opacity duration-700">
                        <Shield size={160} />
                    </div>
                    <div className="flex items-center gap-3 mb-5 relative z-10">
                        <div className="p-2 rounded-xl bg-emerald-500/10 border border-emerald-500/20">
                            <CheckCircle2 size={16} className="text-emerald-400" />
                        </div>
                        <h4 className="text-[10px] font-bold text-emerald-400 uppercase tracking-[0.2em]">Dominant Thesis</h4>
                    </div>
                    <p className="text-base text-on-surface leading-relaxed font-black tracking-tight relative z-10 italic">
                        &quot;{isPreviewOnly ? previewData?.thesis_display : artifactData?.winning_thesis}&quot;
                    </p>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <div className="rounded-xl border border-outline-variant/10 bg-surface-container-low p-6 group hover:border-outline-variant/30 transition duration-300">
                        <div className="flex items-center gap-3 mb-4">
                            <div className="p-2 rounded-xl bg-cyan-500/10 border border-cyan-500/20">
                                <Target size={16} className="text-cyan-400" />
                            </div>
                            <h4 className="text-[10px] font-bold text-cyan-400 uppercase tracking-[0.2em]">Primary Catalyst</h4>
                        </div>
                        <p className="text-sm text-on-surface-variant leading-relaxed">
                            {isPreviewOnly ? previewData?.catalyst_display : artifactData?.primary_catalyst}
                        </p>
                    </div>

                    <div className="rounded-xl border border-outline-variant/10 bg-surface-container-low p-6 group hover:border-outline-variant/30 transition duration-300">
                        <div className="flex items-center gap-3 mb-4">
                            <div className="p-2 rounded-xl bg-rose-500/10 border border-rose-500/20">
                                <AlertTriangle size={16} className="text-rose-400" />
                            </div>
                            <h4 className="text-[10px] font-bold text-rose-400 uppercase tracking-[0.2em]">Risk Vectors</h4>
                        </div>
                        <p className="text-sm text-on-surface-variant leading-relaxed font-medium">
                            {isPreviewOnly ? previewData?.risk_display : artifactData?.primary_risk}
                        </p>
                    </div>
                </div>
            </div>

            <div className="rounded-2xl border border-outline-variant/10 bg-surface-container p-6">
                <div className="flex items-center gap-2 mb-6">
                    <Info size={14} className="text-outline" />
                    <h4 className="text-[10px] font-bold text-outline uppercase tracking-[0.2em]">Supporting Audit Factors</h4>
                </div>
                <div className="space-y-3">
                    {conclusion?.supporting_factors?.map((factor: string, i: number) => (
                        <div key={i} className="flex gap-3 text-xs text-on-surface-variant transition-colors p-3 bg-surface-container-low rounded-xl border border-outline-variant/20">
                            <div className="w-1.5 h-1.5 rounded-full bg-slate-700 mt-1.5 shrink-0" />
                            <p className="leading-relaxed">{factor}</p>
                        </div>
                    ))}
                    {(!conclusion?.supporting_factors || conclusion.supporting_factors.length === 0) && (
                        <p className="text-[10px] text-outline italic">No Secondary Factors Recorded</p>
                    )}
                </div>
            </div>

            <div className="flex items-center justify-between px-2 text-[9px] font-bold text-outline-variant uppercase tracking-[0.2em]">
                <div>Ticker: {resolvedTicker || 'N/A'}</div>
                <div className="flex items-center gap-2 opacity-40">
                    <Zap size={10} />
                    <span>Pragmatic V2.0 Engine Active</span>
                </div>
            </div>

            {/* Debate Transcript (History) */}
            {artifactData?.history && artifactData.history.length > 0 && (
                <DebateTranscript history={artifactData.history} />
            )}

            {/* Fact Registry */}
            {artifactData?.facts && artifactData.facts.length > 0 && (
                <DebateFactSheet facts={artifactData.facts} />
            )}
        </div>
    );
};

export const DebateOutput = memo(DebateOutputComponent);
