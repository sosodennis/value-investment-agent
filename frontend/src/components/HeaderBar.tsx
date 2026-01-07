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
        <header className="h-20 w-full border-b border-slate-900 bg-slate-950 px-8 flex items-center justify-between z-10">
            {/* Brand */}
            <div className="flex items-center gap-3">
                <div className="w-10 h-10 bg-cyan-600 rounded-xl flex items-center justify-center shadow-lg shadow-cyan-900/40">
                    <Zap size={24} className="text-white fill-white" />
                </div>
                <div>
                    <h1 className="text-lg font-black tracking-tighter text-white">
                        FINANCE<span className="text-cyan-500">AI</span> <span className="text-slate-500 font-medium">LAB</span>
                    </h1>
                </div>
            </div>

            {/* Stats Cluster */}
            <div className="hidden lg:flex items-center gap-12">
                <div className="flex flex-col gap-1">
                    <span className="text-[10px] font-bold text-slate-600 uppercase tracking-widest">System</span>
                    <div className="flex items-center gap-1.5">
                        <div className={`w-1.5 h-1.5 rounded-full ${systemStatus === 'online' ? 'bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]' : 'bg-rose-500'}`} />
                        <span className={`text-[11px] font-black uppercase ${systemStatus === 'online' ? 'text-emerald-500' : 'text-rose-500'}`}>
                            {systemStatus}
                        </span>
                    </div>
                </div>

                <div className="flex flex-col gap-1">
                    <span className="text-[10px] font-bold text-slate-600 uppercase tracking-widest">Agents</span>
                    <span className="text-[11px] font-black uppercase text-cyan-500">
                        {activeAgents} Active
                    </span>
                </div>

                <div className="flex flex-col gap-1">
                    <span className="text-[10px] font-bold text-slate-600 uppercase tracking-widest">Stage</span>
                    <span className="text-[11px] font-black uppercase text-cyan-500">
                        {stage}
                    </span>
                </div>
            </div>

            {/* Action Cluster */}
            <div className="flex items-center gap-4">
                {/* Ticker Input Group */}
                <div className="flex items-center bg-slate-900 border border-slate-800 rounded-xl px-4 h-12 focus-within:border-cyan-500/50 transition-all">
                    <div className="bg-emerald-500/10 text-emerald-500 text-[10px] font-bold px-2 py-0.5 rounded border border-emerald-500/20 mr-3">
                        US Stock
                    </div>
                    <input
                        className="bg-transparent border-none outline-none text-sm font-bold text-white w-24 placeholder:text-slate-600"
                        placeholder="TICKER"
                        value={ticker}
                        onChange={(e) => onTickerChange(e.target.value.toUpperCase())}
                    />
                </div>

                {/* Model Selector */}
                <button className="flex items-center gap-3 bg-slate-900 border border-slate-800 rounded-xl px-4 h-12 text-slate-300 hover:bg-slate-800 transition-all">
                    <span className="text-xs font-bold">xAI: Grok 4.1 Fast</span>
                    <ChevronDown size={14} className="text-slate-500" />
                </button>

                {/* Buttons */}
                <button
                    onClick={onStartAnalysis}
                    disabled={isLoading || !ticker}
                    className="flex items-center gap-2 bg-gradient-to-r from-cyan-600 to-teal-600 hover:from-cyan-500 hover:to-teal-500 text-white rounded-xl px-6 h-12 text-xs font-black uppercase tracking-widest transition-all shadow-lg shadow-cyan-900/20 disabled:opacity-50"
                >
                    <Play size={14} className="fill-white" />
                    Start Analysis
                </button>

                <button
                    onClick={onShowHistory}
                    className="flex items-center gap-2 bg-slate-900 border border-slate-800 text-slate-400 hover:bg-slate-800 hover:text-white rounded-xl px-4 h-12 text-xs font-bold transition-all"
                >
                    <Clock size={16} />
                    History
                </button>
            </div>
        </header>
    );
};
