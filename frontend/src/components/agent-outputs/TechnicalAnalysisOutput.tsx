import React from 'react';
import {
    ResponsiveContainer,
    AreaChart,
    Area,
    XAxis,
    YAxis,
    Tooltip,
    ReferenceLine,
    CartesianGrid
} from 'recharts';
import {
    Activity,
    TrendingUp,
    AlertTriangle,
    BrainCircuit,
    Zap,
    LineChart,
    TrendingDown
} from 'lucide-react';
import { TechnicalSignalOutput, RiskLevel, StatisticalState, MemoryStrength } from '../../types/technical';

interface TechnicalAnalysisOutputProps {
    output: TechnicalSignalOutput | null;
    resolvedTicker?: string | null;
}

export const TechnicalAnalysisOutput: React.FC<TechnicalAnalysisOutputProps> = ({
    output,
    resolvedTicker
}) => {
    if (!output) {
        return (
            <div className="flex flex-col items-center justify-center p-12 text-slate-500">
                <Activity className="w-12 h-12 mb-4 opacity-50" />
                <p className="font-bold uppercase tracking-widest text-xs">Waiting for Analysis</p>
            </div>
        );
    }

    const { frac_diff_metrics, signal_state, semantic_tags, llm_interpretation, raw_data } = output;

    // Prepare chart data if available
    const chartData = raw_data?.fracdiff_series
        ? Object.entries(raw_data.fracdiff_series)
            .map(([date, value]) => ({
                date: new Date(date).toLocaleDateString(),
                value: value,
                timestamp: new Date(date).getTime()
            }))
            .sort((a, b) => a.timestamp - b.timestamp)
        : [];

    const getRiskColor = (level: RiskLevel) => {
        switch (level) {
            case RiskLevel.LOW: return 'text-emerald-400';
            case RiskLevel.MEDIUM: return 'text-amber-400';
            case RiskLevel.CRITICAL: return 'text-rose-400';
            default: return 'text-slate-400';
        }
    };

    const getRiskBg = (level: RiskLevel) => {
        switch (level) {
            case RiskLevel.LOW: return 'bg-emerald-400/10 border-emerald-400/20';
            case RiskLevel.MEDIUM: return 'bg-amber-400/10 border-amber-400/20';
            case RiskLevel.CRITICAL: return 'bg-rose-400/10 border-rose-400/20';
            default: return 'bg-slate-400/10 border-slate-400/20';
        }
    };

    return (
        <div className="space-y-6 animate-in fade-in duration-500">
            {/* Header with Ticker */}
            <div className="flex items-center justify-between border-b border-slate-800 pb-4">
                <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-lg bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-center">
                        <LineChart className="text-cyan-400" size={20} />
                    </div>
                    <div>
                        <h3 className="text-lg font-bold text-white tracking-tight">Technical Analysis</h3>
                        <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Statistical Signal Detection</p>
                    </div>
                </div>
                <div className="px-3 py-1 bg-slate-800 border border-slate-700 rounded-lg font-mono text-cyan-400 text-sm font-bold">
                    {output.ticker || resolvedTicker || "N/A"}
                </div>
            </div>

            {/* Parameters Card */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-4 flex flex-col items-center justify-center text-center backdrop-blur-sm">
                    <div className="text-[10px] uppercase font-bold text-slate-500 tracking-widest mb-1">Optimal d</div>
                    <div className="text-2xl font-bold text-cyan-400 font-mono">{frac_diff_metrics.optimal_d.toFixed(2)}</div>
                    <div className="flex flex-col gap-1 mt-2">
                        <div className={`px-2 py-0.5 rounded text-[9px] font-bold uppercase ${frac_diff_metrics.memory_strength === MemoryStrength.STRUCTURALLY_STABLE ? 'bg-emerald-400/10 text-emerald-400' : frac_diff_metrics.memory_strength === MemoryStrength.FRAGILE ? 'bg-rose-400/10 text-rose-400' : 'bg-slate-800 text-slate-400'}`}>
                            {frac_diff_metrics.memory_strength.replace('_', ' ')}
                        </div>
                        <div className="text-[8px] text-slate-600 font-mono">
                            ADF: {frac_diff_metrics.adf_statistic.toFixed(2)} (p={frac_diff_metrics.adf_pvalue.toFixed(4)})
                        </div>
                    </div>
                </div>

                <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-4 flex flex-col items-center justify-center text-center backdrop-blur-sm">
                    <div className="text-[10px] uppercase font-bold text-slate-500 tracking-widest mb-1">Z-Score</div>
                    <div className={`text-2xl font-bold font-mono ${Math.abs(signal_state.z_score) > 2 ? 'text-amber-400' : 'text-emerald-400'}`}>
                        {signal_state.z_score.toFixed(2)}
                    </div>
                    <div className={`mt-2 px-2 py-0.5 rounded text-[9px] font-bold uppercase ${signal_state.statistical_state === StatisticalState.STATISTICAL_ANOMALY ? 'bg-amber-400/10 text-amber-400' : signal_state.statistical_state === StatisticalState.DEVIATING ? 'bg-cyan-400/10 text-cyan-400' : 'bg-slate-800 text-slate-400'}`}>
                        {signal_state.statistical_state}
                    </div>
                </div>

                <div className={`border rounded-xl p-4 flex flex-col items-center justify-center text-center backdrop-blur-sm ${getRiskBg(signal_state.risk_level)}`}>
                    <div className="text-[10px] uppercase font-bold text-slate-500 tracking-widest mb-1">Risk Level</div>
                    <div className={`text-2xl font-bold uppercase ${getRiskColor(signal_state.risk_level)}`}>
                        {signal_state.risk_level}
                    </div>
                    <div className="mt-2 flex items-center gap-1 text-[9px] font-bold uppercase text-slate-400">
                        {signal_state.risk_level === RiskLevel.CRITICAL && <AlertTriangle size={10} />}
                        {signal_state.direction === 'BULLISH' || signal_state.direction === 'up' ? <TrendingUp size={10} className="text-emerald-400" /> : <TrendingDown size={10} className="text-rose-400" />}
                        {signal_state.direction.replace('_', ' ')}
                    </div>
                </div>
            </div>

            {/* FracDiff Chart */}
            {chartData.length > 0 && (
                <div className="bg-slate-900/20 border border-slate-800 rounded-xl p-4 backdrop-blur-sm">
                    <div className="flex items-center gap-2 mb-4 px-2">
                        <LineChart size={14} className="text-cyan-400" />
                        <span className="text-xs font-bold text-white uppercase tracking-widest">Fractionally Differentiated Series (Stationary)</span>
                    </div>
                    <div className="h-48 w-full">
                        <ResponsiveContainer width="100%" height="100%">
                            <AreaChart data={chartData}>
                                <defs>
                                    <linearGradient id="colorValue" x1="0" y1="0" x2="0" y2="1">
                                        <stop offset="5%" stopColor="#22d3ee" stopOpacity={0.3} />
                                        <stop offset="95%" stopColor="#22d3ee" stopOpacity={0} />
                                    </linearGradient>
                                </defs>
                                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
                                <XAxis
                                    dataKey="date"
                                    stroke="#475569"
                                    tick={{ fontSize: 10 }}
                                    tickMargin={10}
                                    interval="preserveStartEnd"
                                />
                                <YAxis
                                    stroke="#475569"
                                    tick={{ fontSize: 10 }}
                                    domain={['auto', 'auto']}
                                />
                                <Tooltip
                                    contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b', borderRadius: '8px' }}
                                    itemStyle={{ color: '#22d3ee', fontSize: '12px' }}
                                    labelStyle={{ color: '#94a3b8', fontSize: '10px', marginBottom: '4px' }}
                                />
                                {/* Mean Reversion Bands usually at +/- 2 std dev (approx output scale) */}
                                <ReferenceLine y={0} stroke="#94a3b8" strokeDasharray="3 3" opacity={0.5} />
                                <Area
                                    type="monotone"
                                    dataKey="value"
                                    stroke="#22d3ee"
                                    strokeWidth={2}
                                    fillOpacity={1}
                                    fill="url(#colorValue)"
                                />
                            </AreaChart>
                        </ResponsiveContainer>
                    </div>
                </div>
            )}

            {/* Analysis Section */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {/* Semantic Tags */}
                <div className="bg-slate-900/20 border border-slate-800 rounded-xl p-5 backdrop-blur-sm">
                    <div className="flex items-center gap-2 mb-4">
                        <Zap size={14} className="text-amber-400" />
                        <span className="text-xs font-bold text-white uppercase tracking-widest">Detected Signals</span>
                    </div>
                    <div className="flex flex-wrap gap-2">
                        {semantic_tags.map(tag => (
                            <span key={tag} className="px-2 py-1 bg-slate-800 border border-slate-700 rounded text-[10px] font-mono text-cyan-300">
                                {tag}
                            </span>
                        ))}
                    </div>
                </div>

                {/* LLM Interpretation */}
                <div className="bg-slate-900/20 border border-slate-800 rounded-xl p-5 backdrop-blur-sm">
                    <div className="flex items-center gap-2 mb-4">
                        <BrainCircuit size={14} className="text-purple-400" />
                        <span className="text-xs font-bold text-white uppercase tracking-widest">AI Interpretation</span>
                    </div>
                    <div className="text-xs text-slate-300 leading-relaxed">
                        {llm_interpretation || "Generating interpretation..."}
                    </div>
                </div>
            </div>
        </div>
    );
};
