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
    const direction = conclusion.direction;

    const getDirectionStyles = () => {
        switch (direction) {
            case 'LONG':
                return {
                    color: 'text-emerald-400',
                    bg: 'bg-emerald-500/10',
                    border: 'border-emerald-500/20',
                    icon: <TrendingUp size={24} className="text-emerald-500" />,
                    shadow: 'shadow-emerald-500/20'
                };
            case 'SHORT':
                return {
                    color: 'text-rose-400',
                    bg: 'bg-rose-500/10',
                    border: 'border-rose-500/20',
                    icon: <TrendingDown size={24} className="text-rose-500" />,
                    shadow: 'shadow-rose-500/20'
                };
            default:
                return {
                    color: 'text-slate-400',
                    bg: 'bg-slate-500/10',
                    border: 'border-slate-500/20',
                    icon: <Minus size={24} className="text-slate-500" />,
                    shadow: 'shadow-slate-500/20'
                };
        }
    };

    const styles = getDirectionStyles();

    return (
        <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-700">
            {/* Verdict Header Card */}
            <div className={`p-6 rounded-2xl border ${styles.border} ${styles.bg} backdrop-blur-md shadow-xl ${styles.shadow}`}>
                <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-3">
                        <div className={`p-3 rounded-xl bg-slate-950/50 border ${styles.border} shadow-lg`}>
                            {styles.icon}
                        </div>
                        <div>
                            <div className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">Debate Verdict</div>
                            <div className={`text-2xl font-black tracking-tight ${styles.color}`}>
                                {direction}
                            </div>
                        </div>
                    </div>
                    <div className="text-right">
                        <div className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">Confidence Score</div>
                        <div className="text-2xl font-black text-white px-3 py-1 bg-slate-950/40 rounded-lg border border-slate-800">
                            {(conclusion.confidence_score * 100).toFixed(0)}%
                        </div>
                    </div>
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
                <div>Rounds Concluded: {conclusion.debate_rounds}</div>
                <div>Ticker: {resolvedTicker || 'N/A'}</div>
            </div>
        </div>
    );
};
