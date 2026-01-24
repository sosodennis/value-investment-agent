import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import {
    ResponsiveContainer,
    AreaChart,
    Area,
    XAxis,
    YAxis,
    Tooltip as RechartsTooltip,
    ReferenceLine,
    CartesianGrid
} from 'recharts';
import {
    Activity,
    TrendingUp,
    TrendingDown,
    BrainCircuit,
    LineChart,
    Layers,
    ChevronDown,
    ChevronUp,
    Info,
    ShieldCheck,
    Zap,
    AlertTriangle,
    Maximize2,
    Minimize2
} from 'lucide-react';
import { TechnicalSignalOutput } from '../../types/technical';

interface TechnicalAnalysisOutputProps {
    output: TechnicalSignalOutput | null;
}

type Timeframe = '1W' | '2W' | '1M' | '3M' | '1Y' | 'ALL';

// --- 1. Semantic Helpers (語意轉譯層) ---

const getSignalStrengthLabel = (d: number, pValue: number) => {
    if (pValue > 0.05) return { label: "High Noise (Unreliable)", color: "text-slate-500", icon: Activity, description: "The signal is indistinguishable from random market noise." };
    if (d < 0.3) return { label: "Structurally Stable", color: "text-emerald-400", icon: ShieldCheck, description: "Strong statistical memory with a very clear, reliable trend structure." };
    if (d < 0.6) return { label: "Balanced Trend", color: "text-amber-400", icon: TrendingUp, description: "Moderate persistence; market is forming a directional structure." };
    return { label: "Statistical Fragility", color: "text-rose-400", icon: Zap, description: "Frequent regime shifts; trend structure is currently unstable." };
};

const MarketStatusBadge = ({ zScore }: { zScore: number }) => {
    let status = "Market Equilibrium";
    let color = "bg-slate-800/40 border-slate-700 text-slate-300";
    let advice = "Wait & Observe";
    let icon = Activity;

    // 根據 Z-Score 定義市場狀態
    if (zScore > 2.0) {
        status = "Extreme Overheating";
        color = "bg-rose-500/20 border-rose-500/40 text-rose-300";
        advice = "High Reversal Risk - Do Not Chase";
        icon = AlertTriangle;
    } else if (zScore < -2.0) {
        status = "Extreme Fear / Panic";
        color = "bg-emerald-500/20 border-emerald-500/40 text-emerald-300";
        advice = "Panic Selling - Potential Rebound Zone";
        icon = Zap;
    } else if (Math.abs(zScore) > 1.0) {
        const isBullish = zScore > 0;
        status = isBullish ? "Bullish Momentum Building" : "Bearish Undercurrents";
        color = "bg-amber-500/20 border-amber-500/40 text-amber-300";
        advice = "Trend is Active - Monitor Closely";
        icon = isBullish ? TrendingUp : TrendingDown;
    }

    const Icon = icon;

    return (
        <div className={`rounded-xl border p-4 flex items-center justify-between transition-all duration-300 shadow-lg ${color}`}>
            <div className="flex items-center gap-4">
                <div className="p-2 rounded-lg bg-white/5 backdrop-blur-md">
                    <Icon size={24} />
                </div>
                <div>
                    <div className="text-[10px] font-bold uppercase tracking-widest opacity-60 mb-0.5">Market Sentiment</div>
                    <div className="text-xl font-bold tracking-tight">{status}</div>
                </div>
            </div>
            <div className="text-right">
                <div className="text-[10px] font-bold uppercase tracking-widest opacity-60 mb-0.5">Tactical Advice</div>
                <div className="text-sm font-medium italic">{advice}</div>
            </div>
        </div>
    );
};

// --- 2. Visual Components ---

const ProbabilityGauge = ({ value }: { value: number }) => {
    // Value is 0-100% Probability
    // 0-16%: Extreme Low (Oversold) - Emerald
    // 16-84%: Noise / Trend - Slate/Blue
    // 84-100%: Extreme High (Overbought) - Rose

    let colorClass = 'bg-slate-600';
    let label = 'Neutral';
    let labelColor = 'text-slate-400';

    if (value > 95) {
        colorClass = 'bg-rose-500 shadow-[0_0_15px_rgba(244,63,94,0.6)]';
        label = 'Extreme High (Bubble)';
        labelColor = 'text-rose-400';
    } else if (value > 84) {
        colorClass = 'bg-rose-400';
        label = 'High Prob (Overheating)';
        labelColor = 'text-rose-300';
    } else if (value < 5) {
        colorClass = 'bg-emerald-500 shadow-[0_0_15px_rgba(16,185,129,0.6)]';
        label = 'Extreme Low (Deep Value)';
        labelColor = 'text-emerald-400';
    } else if (value < 16) {
        colorClass = 'bg-emerald-400';
        label = 'Low Prob (Discounted)';
        labelColor = 'text-emerald-300';
    }

    return (
        <div className="w-full">
            <div className="flex justify-between items-end mb-2">
                <span className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Statistical Strength (CDF)</span>
                <div className="text-right">
                    <span className={`text-[10px] font-black uppercase ${labelColor} mr-2`}>{label}</span>
                    <span className={`text-sm font-mono font-bold ${labelColor}`}>{value.toFixed(1)}%</span>
                </div>
            </div>

            {/* Gauge Track */}
            <div className="h-3 bg-slate-900 rounded-full relative overflow-hidden border border-slate-800">
                {/* Zones Background */}
                <div className="absolute inset-0 flex opacity-20">
                    <div className="w-[16%] bg-emerald-500/50 h-full border-r border-slate-900/50"></div>
                    <div className="w-[68%] bg-slate-500/10 h-full"></div>
                    <div className="w-[16%] bg-rose-500/50 h-full border-l border-slate-900/50"></div>
                </div>

                {/* Marker */}
                <div
                    className="absolute h-full w-1.5 bg-white shadow-[0_0_10px_white] z-10 transition-all duration-700 ease-out"
                    style={{ left: `calc(${value}% - 3px)` }}
                />

                {/* Fill Bar (Optional, simpler to just show marker for probability) */}
                <div
                    className={`h-full opacity-60 transition-all duration-700 ease-out ${colorClass}`}
                    style={{ width: `${value}%` }}
                />
            </div>

            <div className="flex justify-between text-[8px] font-mono text-slate-600 mt-1 uppercase">
                <span>-2σ (2.3%)</span>
                <span>MEAN (50%)</span>
                <span>+2σ (97.7%)</span>
            </div>
        </div>
    );
};

// --- 3. Main Component ---

export const TechnicalAnalysisOutput: React.FC<TechnicalAnalysisOutputProps> = ({
    output
}) => {
    const [showAdvanced, setShowAdvanced] = useState(false);
    const [isAutoFit, setIsAutoFit] = useState(false);
    const [timeframe, setTimeframe] = useState<Timeframe>('ALL');

    // Data Processing & Outlier Filtering
    // [CRITICAL FIX] Use z_score_series instead of fracdiff_series for chart
    // This ensures the data mathematically aligns with +/- 2.0 thresholds
    const chartData = React.useMemo(() => {
        if (!output?.raw_data?.z_score_series) return [];

        return Object.entries(output.raw_data.z_score_series)
            .filter(([_, value]) => {
                // [CRITICAL FIX] 2. 過濾掉 "暖身期" 的 0.0 數據
                // FracDiff 算法前 100+ 天因為數據不足會填 0，畫出來會像一條死魚，必須藏起來
                if (Math.abs(value) < 0.0001) return false;
                return true;
            })
            .map(([date, value]) => {
                // [FIX] Clamp extreme outliers to +/- 10.0 for visualization
                let displayValue = value;
                if (value > 10) displayValue = 10;
                if (value < -10) displayValue = -10;

                return {
                    date: new Date(date).toLocaleDateString(undefined, { month: 'numeric', day: 'numeric' }),
                    value: displayValue,
                    originalValue: value, // Keep original for tooltip
                    timestamp: new Date(date).getTime()
                };
            })
            .sort((a, b) => a.timestamp - b.timestamp);
    }, [output]);

    // Filter chart data by timeframe
    const filteredChartData = React.useMemo(() => {
        if (timeframe === 'ALL' || chartData.length === 0) return chartData;

        const latestTimestamp = chartData[chartData.length - 1].timestamp;
        let cutoffTime: number;

        const now = new Date(latestTimestamp);
        switch (timeframe) {
            case '1W':
                cutoffTime = new Date(now).setDate(now.getDate() - 7);
                break;
            case '2W':
                cutoffTime = new Date(now).setDate(now.getDate() - 14);
                break;
            case '1M':
                cutoffTime = new Date(now).setMonth(now.getMonth() - 1);
                break;
            case '3M':
                cutoffTime = new Date(now).setMonth(now.getMonth() - 3);
                break;
            case '1Y':
                cutoffTime = new Date(now).setFullYear(now.getFullYear() - 1);
                break;
            default:
                return chartData;
        }

        return chartData.filter(d => d.timestamp >= cutoffTime);
    }, [chartData, timeframe]);

    if (!output) return (
        <div className="flex flex-col items-center justify-center p-12 text-slate-500">
            <Activity className="w-12 h-12 mb-4 animate-pulse opacity-50" />
            <p className="font-bold uppercase tracking-widest text-[10px]">Processing Statistical Framework...</p>
        </div>
    );

    const { frac_diff_metrics, signal_state, llm_interpretation, semantic_tags } = output;
    const strength = getSignalStrengthLabel(frac_diff_metrics.optimal_d, frac_diff_metrics.adf_pvalue);
    const StrengthIcon = strength.icon;

    // [CRITICAL FIX] Pre-calculate Y-Axis Domain
    // 我們在這裡直接算出數值，並排除無效數據 (NaN/null)，確保穩定性
    const dataValues = filteredChartData
        .map(d => d.value)
        .filter(v => typeof v === 'number' && !isNaN(v) && isFinite(v));

    // 1. Fixed Range Mode: Strictly defined to visualize the standard deviation context
    // We clip outliers here to force a consistent visual scale for risk verification
    const fixedDomain: [number, number] = [-3, 3];

    // 2. Auto-Fit Mode: Fits the visible data range (including outliers up to clamp limit)
    const autoMax = dataValues.length > 0 ? Math.max(...dataValues) + 0.1 : 'auto';
    const autoMin = dataValues.length > 0 ? Math.min(...dataValues) - 0.1 : 'auto';

    // 決定當前使用哪個 Domain (Explicitly cast to [any, any] for Recharts compatibility)
    const currentDomain: [any, any] = isAutoFit
        ? [autoMin, autoMax]
        : fixedDomain;

    return (
        <div className="space-y-6 animate-in fade-in slide-in-from-bottom-2 duration-700">

            {/* Header Section */}
            <header className="space-y-4">
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-cyan-500/20 to-blue-600/20 border border-cyan-500/30 flex items-center justify-center shadow-inner">
                            <LineChart className="text-cyan-400" size={20} />
                        </div>
                        <div>
                            <h3 className="text-xl font-bold text-white tracking-tight">Technical Intelligence</h3>
                            <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-widest text-slate-500">
                                <span className="text-cyan-400">{output.ticker}</span>
                                <span className="opacity-30">|</span>
                                <span>Advanced FracDiff Analysis</span>
                            </div>
                        </div>
                    </div>
                </div>
                <MarketStatusBadge zScore={signal_state.z_score} />
            </header>

            {/* AI Interpretation */}
            <section className="bg-slate-900/60 border border-indigo-500/20 rounded-2xl p-6 relative overflow-hidden group shadow-2xl backdrop-blur-xl">
                <div className="absolute top-0 right-0 p-4 opacity-10 group-hover:opacity-20 transition-opacity">
                    <BrainCircuit size={80} className="text-indigo-400" />
                </div>
                <div className="flex items-center gap-2 mb-4">
                    <BrainCircuit size={18} className="text-indigo-400" />
                    <span className="text-xs font-black text-indigo-200 uppercase tracking-[0.2em]">Analyst Perspective</span>
                </div>
                <div className="text-base text-slate-200 leading-relaxed font-light italic">
                    {llm_interpretation ? (
                        <ReactMarkdown
                            components={{
                                strong: ({ node, ...props }) => <span className="font-bold text-indigo-300 not-italic" {...props} />,
                                p: ({ node, ...props }) => <p className="mb-2 last:mb-0" {...props} />
                            }}
                        >
                            {llm_interpretation}
                        </ReactMarkdown>
                    ) : (
                        "Synthesizing market dynamics into actionable intelligence..."
                    )}
                </div>
                <div className="flex flex-wrap gap-2 mt-6">
                    {semantic_tags.map(tag => (
                        <span key={tag} className="px-3 py-1 bg-indigo-500/10 border border-indigo-500/20 rounded-full text-[10px] font-bold text-indigo-300 uppercase tracking-wider">
                            #{tag.replace('_', ' ')}
                        </span>
                    ))}
                </div>
            </section>

            {/* Confluence Dashboard (Requires 'confluence' field in backend) */}
            {signal_state.confluence && (
                <section className="bg-slate-900/30 border border-slate-800 rounded-2xl p-6 shadow-inner">
                    <div className="flex items-center gap-2 mb-6">
                        <Layers size={16} className="text-purple-400" />
                        <span className="text-xs font-black text-white uppercase tracking-[0.2em]">Confluence Dashboard</span>
                        <div className="ml-auto flex items-center gap-1 group relative">
                            <Info size={12} className="text-slate-500 hover:text-slate-300 cursor-help" />
                            <div className="absolute bottom-full right-0 mb-2 w-64 p-2 bg-slate-950 border border-slate-800 rounded shadow-2xl text-[10px] text-slate-400 opacity-0 group-hover:opacity-100 transition-opacity z-50 pointer-events-none">
                                We aggregate multiple non-correlated indicators (RSI, Bollinger, MACD, OBV) to confirm the statistical signal.
                            </div>
                        </div>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
                        <div className="space-y-3">
                            <ProbabilityGauge value={signal_state.confluence.statistical_strength} />
                        </div>
                        <div className="flex flex-col justify-center border-l border-slate-800 pl-8">
                            <span className="text-[10px] text-slate-400 font-black uppercase mb-3">Volatility Structure</span>
                            <div className="flex items-center gap-3">
                                <div className={`w-3 h-3 rounded-full shadow-[0_0_15px_rgba(0,0,0,0.5)] ${signal_state.confluence.bollinger_state.includes('BREAKOUT') ? 'bg-amber-400 animate-pulse' : 'bg-slate-700'}`} />
                                <span className="text-sm font-bold text-slate-100 tracking-tight">{signal_state.confluence.bollinger_state.replace('_', ' ')}</span>
                            </div>
                        </div>
                        <div className="flex flex-col justify-center gap-3 border-l border-slate-800 pl-8">
                            <div className="flex justify-between items-center bg-slate-950/50 px-3 py-2 rounded-lg border border-slate-800/50">
                                <span className="text-[10px] text-slate-500 font-bold">MOMENTUM</span>
                                <span className="text-xs font-mono font-bold text-cyan-400">{signal_state.confluence.macd_momentum}</span>
                            </div>
                            <div className="flex justify-between items-center bg-slate-950/50 px-3 py-2 rounded-lg border border-slate-800/50">
                                <span className="text-[10px] text-slate-500 font-bold">VOLUME</span>
                                <span className="text-xs font-mono font-bold text-cyan-400">{signal_state.confluence.obv_state.replace('_', ' ')}</span>
                            </div>
                        </div>
                    </div>
                </section>
            )}

            {/* Technical Charts (Progressive Disclosure) */}
            <section className="border border-slate-800 rounded-2xl overflow-hidden transition-all duration-300">
                <button
                    onClick={() => setShowAdvanced(!showAdvanced)}
                    className="w-full flex items-center justify-between p-4 bg-slate-900/20 hover:bg-slate-900/40 transition-colors"
                >
                    <div className="flex items-center gap-2">
                        <Activity size={14} className="text-slate-500" />
                        <span className="text-[10px] font-black text-slate-500 uppercase tracking-widest">Statistical Evidence & Charts</span>
                    </div>
                    {showAdvanced ? <ChevronUp size={16} className="text-slate-500" /> : <ChevronDown size={16} className="text-slate-500" />}
                </button>

                {showAdvanced && (
                    <div className="p-6 space-y-8 animate-in slide-in-from-top-2 duration-300">
                        {/* Metrics Cards */}
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                            <div className="bg-slate-950/50 p-4 rounded-xl border border-slate-800 relative group overflow-hidden">
                                <div className="text-[9px] font-black text-slate-500 uppercase mb-2">Signal Quality</div>
                                <div className={`flex items-center gap-2 text-lg font-bold ${strength.color}`}>
                                    <StrengthIcon size={18} />
                                    {strength.label}
                                </div>
                                <p className="text-[9px] text-slate-400 mt-2 leading-tight">{strength.description}</p>
                            </div>
                            <div className="bg-slate-950/50 p-4 rounded-xl border border-slate-800 flex flex-col justify-center text-center">
                                <div className="text-[9px] font-black text-slate-500 uppercase mb-1">Standard Deviation (Z)</div>
                                <div className={`text-2xl font-mono font-bold ${Math.abs(signal_state.z_score) > 2 ? 'text-amber-400' : 'text-white'}`}>
                                    {signal_state.z_score > 0 ? '+' : ''}{signal_state.z_score.toFixed(3)}
                                </div>
                            </div>
                            <div className="bg-slate-950/50 p-4 rounded-xl border border-slate-800 flex flex-col justify-center text-center group relative cursor-help">
                                <div className="text-[9px] font-black text-slate-500 uppercase mb-1">Confidence Check (ADF)</div>
                                <div className={`text-2xl font-mono font-bold ${frac_diff_metrics.adf_pvalue < 0.05 ? 'text-emerald-500' : 'text-rose-500'}`}>
                                    {frac_diff_metrics.adf_pvalue.toFixed(4)}
                                </div>
                                <div className="text-[8px] text-slate-600 font-bold uppercase mt-1 tracking-tighter">P-Value (Target &lt; 0.05)</div>
                            </div>
                        </div>

                        {/* Chart with Stable Domain & Zoom Controls */}
                        <div className="bg-slate-950/40 border border-slate-800 rounded-xl p-6 relative">
                            <div className="flex items-center justify-between mb-6">
                                <div className="flex items-center gap-2">
                                    <Activity size={14} className="text-cyan-400 opacity-50" />
                                    <span className="text-[10px] font-black text-slate-400 uppercase tracking-widest">FracDiff Stream</span>
                                </div>
                                <div className="flex items-center gap-4">
                                    {/* Timeframe Selectors */}
                                    <div className="flex items-center bg-slate-800/50 rounded-lg p-0.5 border border-slate-700/50">
                                        {(['1W', '2W', '1M', '3M', '1Y', 'ALL'] as Timeframe[]).map((tf) => (
                                            <button
                                                key={tf}
                                                onClick={() => setTimeframe(tf)}
                                                className={`px-2 py-1 rounded text-[9px] font-bold transition-all ${timeframe === tf
                                                    ? 'bg-cyan-500/20 text-cyan-400 shadow-[0_0_10px_rgba(34,211,238,0.1)]'
                                                    : 'text-slate-500 hover:text-slate-300'
                                                    }`}
                                            >
                                                {tf}
                                            </button>
                                        ))}
                                    </div>

                                    {/* Legend (Only in fixed mode) */}
                                    {!isAutoFit && (
                                        <div className="flex items-center gap-2 text-[8px] font-bold text-slate-500 uppercase">
                                            <div className="w-2 h-[2px] bg-rose-500 opacity-50" /> Anomaly Threshold (±2)
                                        </div>
                                    )}

                                    {/* Zoom Toggle Button */}
                                    <button
                                        onClick={() => setIsAutoFit(!isAutoFit)}
                                        className={`flex items-center gap-1.5 px-2 py-1 rounded border text-[9px] font-bold uppercase transition-all
                                            ${isAutoFit
                                                ? 'bg-cyan-500/20 border-cyan-500/50 text-cyan-300'
                                                : 'bg-slate-800 border-slate-700 text-slate-400 hover:text-slate-200'
                                            }`}
                                        title={isAutoFit ? "Reset Zoom" : "Auto Fit Waveform"}
                                    >
                                        {isAutoFit ? <Minimize2 size={10} /> : <Maximize2 size={10} />}
                                        {isAutoFit ? "Reset View" : "Zoom Fit"}
                                    </button>
                                </div>
                            </div>

                            <div className="h-64 w-full">
                                <ResponsiveContainer width="100%" height="100%">
                                    <AreaChart
                                        data={filteredChartData}
                                        margin={{ top: 10, right: 40, left: 0, bottom: 0 }}
                                    >
                                        <defs>
                                            <linearGradient id="colorValue" x1="0" y1="0" x2="0" y2="1">
                                                <stop offset="5%" stopColor="#22d3ee" stopOpacity={0.15} />
                                                <stop offset="95%" stopColor="#22d3ee" stopOpacity={0} />
                                            </linearGradient>
                                        </defs>
                                        <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
                                        <XAxis
                                            dataKey="date"
                                            stroke="#334155"
                                            tick={{ fontSize: 9, fontWeight: 700 }}
                                            minTickGap={40}
                                            axisLine={false}
                                        />
                                        <YAxis
                                            stroke="#334155"
                                            tick={{ fontSize: 9, fontWeight: 700 }}
                                            domain={currentDomain}
                                            axisLine={false}
                                            tickFormatter={(val) => (typeof val === 'number' ? val.toFixed(1) : val)}
                                        />
                                        <RechartsTooltip
                                            contentStyle={{ backgroundColor: '#020617', borderColor: '#1e293b', borderRadius: '8px', padding: '12px' }}
                                            labelStyle={{ color: '#64748b', fontSize: '10px', fontWeight: 800, marginBottom: '4px', textTransform: 'uppercase' }}
                                            itemStyle={{ color: '#22d3ee', fontSize: '12px', fontWeight: 700 }}
                                            formatter={(value: number, name: string, props: any) => {
                                                const original = props.payload.originalValue;
                                                return [original ? original.toFixed(4) : value.toFixed(4), "Z-Score"];
                                            }}
                                        />
                                        <Area
                                            type="monotone"
                                            dataKey="value"
                                            stroke="#22d3ee"
                                            strokeWidth={2.5}
                                            fill="url(#colorValue)"
                                            animationDuration={500}
                                        />

                                        {/* Benchmark Lines: In Auto Mode, only show if they are relevant to the visible range */
                                            /* This prevents the chart from "zooming out" just to show empty space */
                                            (!isAutoFit || (autoMax as number) > 1.8) && (
                                                <ReferenceLine
                                                    y={2}
                                                    stroke="#f43f5e"
                                                    strokeDasharray="4 4"
                                                    opacity={0.8}
                                                    label={{ value: 'Overbought', position: 'insideTopRight', fill: '#f43f5e', fontSize: 10, fontWeight: 'bold' }}
                                                />
                                            )}

                                        {(!isAutoFit || (autoMin as number) < -1.8) && (
                                            <ReferenceLine
                                                y={-2}
                                                stroke="#f43f5e"
                                                strokeDasharray="4 4"
                                                opacity={0.8}
                                                label={{ value: 'Oversold', position: 'insideBottomRight', fill: '#f43f5e', fontSize: 10, fontWeight: 'bold' }}
                                            />
                                        )}

                                        <ReferenceLine y={0} stroke="#475569" strokeOpacity={0.2} />
                                    </AreaChart>
                                </ResponsiveContainer>
                            </div>
                        </div>
                    </div>
                )}
            </section>
        </div>
    );
};
