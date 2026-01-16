import React from 'react';
import { Shield, Target, AlertTriangle, TrendingUp, TrendingDown, Minus, Info, CheckCircle2 } from 'lucide-react';
import { DebateAgentOutput } from '../../types/debate';

interface DebateOutputProps {
    output: DebateAgentOutput | null;
    resolvedTicker?: string | null;
}

export const DebateOutput: React.FC<DebateOutputProps> = ({ output, resolvedTicker }) => {
    if (!output || !output.conclusion) {
        return (
            <div className="flex flex-col items-center justify-center h-full text-slate-500 py-12">
                <Shield size={48} className="text-slate-800 mb-4 opacity-50" />
                <p className="text-sm font-bold uppercase tracking-widest">No Debate Verdict Available</p>
                <p className="text-[10px] mt-2 opacity-60">Wait for the debate between Bull and Bear agents to conclude.</p>
            </div>
        );
    }

    const { conclusion } = output;
    const direction = conclusion.final_verdict;
    const scenarios = conclusion.scenario_analysis;

    const getDirectionStyles = () => {
        switch (direction) {
            case 'LONG':
                return {
                    color: 'text-emerald-400',
                    bg: 'bg-emerald-500/10',
                    border: 'border-emerald-500/20',
                    icon: <TrendingUp size={20} className="text-emerald-500" />,
                };
            case 'SHORT':
                return {
                    color: 'text-rose-400',
                    bg: 'bg-rose-500/10',
                    border: 'border-rose-500/20',
                    icon: <TrendingDown size={20} className="text-rose-500" />,
                };
            default:
                return {
                    color: 'text-slate-400',
                    bg: 'bg-slate-500/10',
                    border: 'border-slate-500/20',
                    icon: <Minus size={20} className="text-slate-500" />,
                };
        }
    };

    const styles = getDirectionStyles();

    return (
        <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-700 pb-12">
            {/* Verdict Header Card - Bayesian V6.0 */}
            <div className={`rounded-2xl border p-6 backdrop-blur-md ${styles.bg} ${styles.border} relative overflow-hidden`}>
                {/* Risk Profile Badge */}
                <div className="absolute top-0 right-0 p-4">
                    <div className="px-2 py-0.5 rounded border border-white/10 bg-white/5 text-[9px] font-bold text-slate-400 uppercase tracking-widest">
                        {conclusion.risk_profile?.replace('_', ' ')}
                    </div>
                </div>

                {/* Header with Verdict Label */}
                <div className="flex items-center justify-between mb-6">
                    <div className="flex items-center gap-3">
                        <Shield size={18} className="text-cyan-400" />
                        <h3 className="text-sm font-bold text-white uppercase tracking-widest">Debate Verdict</h3>
                    </div>
                    <div className={`px-4 py-1.5 rounded-full border text-xs font-bold uppercase tracking-widest bg-slate-950/40 ${styles.border} ${styles.color}`}>
                        {direction}
                    </div>
                </div>

                {/* Risk Override Warning */}
                {conclusion.risk_override && (
                    <div className="mb-6 p-3 rounded-xl bg-orange-500/10 border border-orange-500/20 flex items-start gap-3">
                        <AlertTriangle size={14} className="text-orange-400 mt-0.5 shrink-0" />
                        <div className="text-[10px] text-orange-200/80 leading-relaxed font-medium">
                            <span className="text-orange-400 font-bold uppercase tracking-tighter mr-1">[Risk Override]</span>
                            Safety lock triggered. Position size restricted due to high bear probability relative to {conclusion.risk_profile} tolerance.
                        </div>
                    </div>
                )}

                {/* Scenario Analysis - Updated V6.0 */}
                <div className="space-y-4 mb-6">
                    <div className="flex items-center justify-between">
                        <h4 className="text-[10px] font-bold text-slate-500 uppercase tracking-widest flex items-center gap-2">
                            <Info size={12} /> Probabilistic Logic (Normalized)
                        </h4>
                        {conclusion.expected_value !== undefined && (
                            <div className="text-[10px] font-bold tracking-widest">
                                <span className="text-slate-500 mr-2">EV:</span>
                                <span className={conclusion.expected_value > 0 ? 'text-emerald-400' : 'text-rose-400'}>
                                    {(conclusion.expected_value * 100).toFixed(1)}%
                                </span>
                            </div>
                        )}
                    </div>

                    {/* CAPM Metrics Row */}
                    {conclusion.hurdle_rate !== undefined && (
                        <div className="flex items-center gap-4 text-[10px] p-2.5 bg-slate-800/30 rounded-lg border border-slate-700/30">
                            <div className="flex items-center gap-1.5">
                                <span className="text-slate-500">β Beta:</span>
                                <span className="text-cyan-400 font-bold">
                                    {conclusion.beta?.toFixed(2) || 'N/A'}
                                </span>
                            </div>
                            <div className="flex items-center gap-1.5">
                                <span className="text-slate-500">Hurdle:</span>
                                <span className="text-amber-400 font-bold">
                                    {(conclusion.hurdle_rate * 100).toFixed(1)}%
                                </span>
                            </div>
                            <div className="flex items-center gap-1.5">
                                <span className="text-slate-500">EV vs Hurdle:</span>
                                <span className={
                                    (conclusion.expected_value || 0) > conclusion.hurdle_rate
                                        ? 'text-emerald-400 font-bold'
                                        : 'text-rose-400 font-bold'
                                }>
                                    {(conclusion.expected_value || 0) > conclusion.hurdle_rate ? '✓ PASS' : '✗ FAIL'}
                                </span>
                            </div>
                            {conclusion.data_source && (
                                <div className="ml-auto text-[9px] text-slate-600">
                                    {conclusion.data_source === 'REAL_TIME' ? '📊 Live' : '📁 Static'}
                                </div>
                            )}
                        </div>
                    )}
                    <div className="grid grid-cols-1 gap-3">
                        {/* Bull Case */}
                        <div className="space-y-1.5">
                            <div className="flex justify-between text-[10px] uppercase font-bold tracking-tight">
                                <span className="text-emerald-400">Bull Case ({scenarios.bull_case.price_implication})</span>
                                <span className="text-emerald-500">
                                    {((conclusion.p_bull ?? scenarios.bull_case.probability) * 100).toFixed(0)}%
                                </span>
                            </div>
                            <div className="h-1.5 w-full bg-slate-800 rounded-full overflow-hidden">
                                <div
                                    className="h-full bg-emerald-500 transition-all duration-1000"
                                    style={{ width: `${(conclusion.p_bull ?? scenarios.bull_case.probability) * 100}%` }}
                                />
                            </div>
                            <p className="text-[9px] text-slate-500 leading-tight italic">{scenarios.bull_case.outcome_description}</p>
                        </div>

                        {/* Base Case */}
                        <div className="space-y-1.5">
                            <div className="flex justify-between text-[10px] uppercase font-bold tracking-tight">
                                <span className="text-slate-400">Base Case (Neutral)</span>
                                <span className="text-slate-400">
                                    {((1 - (conclusion.p_bull ?? 0) - (conclusion.p_bear ?? 0)) * 100).toFixed(0)}%
                                </span>
                            </div>
                            <div className="h-1.5 w-full bg-slate-800 rounded-full overflow-hidden">
                                <div
                                    className="h-full bg-slate-500 transition-all duration-1000"
                                    style={{ width: `${(1 - (conclusion.p_bull ?? 0) - (conclusion.p_bear ?? 0)) * 100}%` }}
                                />
                            </div>
                            <p className="text-[9px] text-slate-500 leading-tight italic">{scenarios.base_case.outcome_description}</p>
                        </div>

                        {/* Bear Case */}
                        <div className="space-y-1.5">
                            <div className="flex justify-between text-[10px] uppercase font-bold tracking-tight">
                                <span className="text-rose-400">Bear Case ({scenarios.bear_case.price_implication})</span>
                                <span className="text-rose-500">
                                    {((conclusion.p_bear ?? scenarios.bear_case.probability) * 100).toFixed(0)}%
                                </span>
                            </div>
                            <div className="h-1.5 w-full bg-slate-800 rounded-full overflow-hidden">
                                <div
                                    className="h-full bg-rose-500 transition-all duration-1000"
                                    style={{ width: `${(conclusion.p_bear ?? scenarios.bear_case.probability) * 100}%` }}
                                />
                            </div>
                            <p className="text-[9px] text-slate-500 leading-tight italic">{scenarios.bear_case.outcome_description}</p>
                        </div>
                    </div>
                </div>

                <div className="h-px bg-white/5 mb-4" />

                {/* Bayesian Confidence */}
                <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-widest">
                    <span className="text-slate-500">Quant Conviction:</span>
                    <span className={`${styles.color} text-sm font-black`}>
                        {(conclusion.kelly_confidence * 100).toFixed(0)}%
                    </span>
                    <span className="text-slate-600 ml-auto">(Round {conclusion.debate_rounds})</span>
                </div>
            </div>

            {/* Signal Collapse Grid */}
            <div className="grid grid-cols-1 gap-6">
                {/* Winning Thesis */}
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
                        &quot;{conclusion.winning_thesis}&quot;
                    </p>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    {/* Primary Catalyst */}
                    <div className="bg-slate-900/40 border border-slate-800/50 rounded-2xl p-6 group">
                        <div className="flex items-center gap-2 mb-4">
                            <div className="p-1.5 rounded-lg bg-cyan-500/10 border border-cyan-500/20">
                                <Target size={14} className="text-cyan-400" />
                            </div>
                            <h4 className="text-[10px] font-bold text-cyan-400 uppercase tracking-widest">Primary Catalyst</h4>
                        </div>
                        <p className="text-xs text-slate-300 leading-relaxed group-hover:text-white transition-colors">
                            {conclusion.primary_catalyst}
                        </p>
                    </div>

                    {/* Primary Risk */}
                    <div className="bg-slate-900/40 border border-slate-800/50 rounded-2xl p-6 group border-rose-500/10">
                        <div className="flex items-center gap-2 mb-4">
                            <div className="p-1.5 rounded-lg bg-rose-500/10 border border-rose-500/20">
                                <AlertTriangle size={14} className="text-rose-400" />
                            </div>
                            <h4 className="text-[10px] font-bold text-rose-400 uppercase tracking-widest">Critical Failure Mode</h4>
                        </div>
                        <p className="text-xs text-rose-200/80 leading-relaxed group-hover:text-rose-100 transition-colors font-medium">
                            {conclusion.primary_risk}
                        </p>
                    </div>
                </div>
            </div>

            {/* Supporting Factors */}
            <div className="bg-slate-950/30 border border-slate-900 rounded-2xl p-6">
                <div className="flex items-center gap-2 mb-6">
                    <Info size={14} className="text-slate-500" />
                    <h4 className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Supporting Audit Factors</h4>
                </div>
                <div className="space-y-3">
                    {conclusion.supporting_factors.map((factor, i) => (
                        <div key={i} className="flex gap-3 text-xs text-slate-400 hover:text-slate-300 transition-colors p-3 bg-slate-900/20 rounded-xl border border-slate-800/30">
                            <div className="w-1.5 h-1.5 rounded-full bg-slate-700 mt-1.5 shrink-0" />
                            <p className="leading-relaxed">{factor}</p>
                        </div>
                    ))}
                    {conclusion.supporting_factors.length === 0 && (
                        <p className="text-[10px] text-slate-600 italic">No secondary factors recorded.</p>
                    )}
                </div>
            </div>

            {/* Debate Metadata */}
            <div className="flex items-center justify-between px-2 text-[9px] font-bold text-slate-700 uppercase tracking-[0.2em]">
                <div>Ticker: {resolvedTicker || 'N/A'}</div>
            </div>
        </div>
    );
};
