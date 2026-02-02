import React from 'react';
import { Zap, ChevronDown, Play, Clock } from 'lucide-react';

interface HeaderBarProps {
    systemStatus: 'online' | 'offline';
    activeAgents: number;
    stage: string;
    ticker: string;
    onTickerChange: (v: string) => void;
    onStartAnalysis: () => void;
    onShowHistory: () => void;
    isLoading: boolean;
}

export const HeaderBar: React.FC<HeaderBarProps> = ({
    systemStatus,
    activeAgents,
    stage,
    ticker,
    onTickerChange,
    onStartAnalysis,
    onShowHistory,
    isLoading,
}) => {
    return (
        <header className="h-20 w-full border-b border-border-main bg-bg-main px-8 flex items-center justify-between z-10">
            {/* Brand */}
            <div className="flex items-center gap-3">
                <div className="w-10 h-10 bg-primary rounded-xl flex items-center justify-center shadow-lg shadow-primary/20">
                    <Zap size={24} className="text-white fill-white" />
                </div>
                <div>
                    <h1 className="text-lg font-black tracking-tighter text-white">
                        FINANCE<span className="text-primary text-cyan-500">AI</span> <span className="text-slate-500 font-medium">LAB</span>
                    </h1>
                </div>
            </div>

            {/* Stats Cluster */}
            <nav className="hidden lg:flex items-center gap-12" aria-label="System Stats">
                <div className="flex flex-col gap-1">
                    <span className="text-label">System</span>
                    <div className="flex items-center gap-1.5">
                        <div className={`w-1.5 h-1.5 rounded-full ${systemStatus === 'online' ? 'bg-success shadow-[0_0_8px_rgba(var(--emerald-500-rgb),0.5)]' : 'bg-error'}`} />
                        <span className={`text-[11px] font-black uppercase ${systemStatus === 'online' ? 'text-success' : 'text-error'}`}>
                            {systemStatus}
                        </span>
                    </div>
                </div>

                <div className="flex flex-col gap-1">
                    <span className="text-label">Agents</span>
                    <span className="text-[11px] font-black uppercase text-primary">
                        {activeAgents} Active
                    </span>
                </div>

                <div className="flex flex-col gap-1">
                    <span className="text-label">Stage</span>
                    <span className="text-[11px] font-black uppercase text-primary">
                        {stage}
                    </span>
                </div>
            </nav>

            {/* Action Cluster */}
            <div className="flex items-center gap-4">
                {/* Ticker Input Group */}
                <div className="flex items-center bg-slate-900 border border-slate-800 rounded-xl px-4 h-12 focus-within:border-primary/50 transition-all">
                    <div className="bg-success/10 text-success text-[10px] font-bold px-2 py-0.5 rounded border border-success/20 mr-3">
                        US Stock
                    </div>
                    <input
                        className="bg-transparent border-none outline-none text-sm font-bold text-white w-24 placeholder:text-slate-600"
                        placeholder="TICKER"
                        aria-label="Stock Ticker"
                        value={ticker}
                        onChange={(e) => onTickerChange(e.target.value.toUpperCase())}
                    />
                </div>

                {/* Model Selector */}
                <button
                    className="flex items-center gap-3 bg-slate-900 border border-slate-800 rounded-xl px-4 h-12 text-slate-300 hover:bg-slate-800 transition-all"
                    aria-label="Select Model"
                >
                    <span className="text-xs font-bold">xAI: Grok 4.1 Fast</span>
                    <ChevronDown size={14} className="text-slate-500" />
                </button>

                {/* Buttons */}
                <button
                    onClick={onStartAnalysis}
                    disabled={isLoading || !ticker}
                    className="flex items-center gap-2 bg-gradient-to-r from-primary to-teal-600 hover:opacity-90 text-white rounded-xl px-6 h-12 text-xs font-black uppercase tracking-widest transition-all shadow-lg shadow-primary/10 disabled:opacity-50"
                    aria-label="Start Analysis"
                >
                    <Play size={14} className="fill-white" />
                    Start Analysis
                </button>

                <button
                    onClick={onShowHistory}
                    className="flex items-center gap-2 bg-slate-900 border border-slate-800 text-slate-400 hover:bg-slate-800 hover:text-white rounded-xl px-4 h-12 text-xs font-bold transition-all"
                    aria-label="Show History"
                >
                    <Clock size={16} />
                    History
                </button>
            </div>
        </header>
    );
};
