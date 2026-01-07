import React, { useState } from 'react';
import { AgentInfo, DimensionScore } from '../types/agents';
import { TrendingUp, BarChart3, FileText, Zap, MessageSquare, ListFilter, Activity } from 'lucide-react';
import { Message } from '../hooks/useAgent';

interface AgentDetailPanelProps {
    agent: AgentInfo | null;
    messages: Message[];
    onSubmitCommand?: (payload: any) => Promise<void>;
}

export const AgentDetailPanel: React.FC<AgentDetailPanelProps> = ({ agent, messages, onSubmitCommand }) => {
    const [activeTab, setActiveTab] = useState<'Score' | 'History' | 'Output' | 'Logs'>('History');

    if (!agent) {
        return (
            <div className="flex-1 h-full flex flex-col items-center justify-center bg-slate-950/10">
                <div className="w-24 h-24 rounded-full bg-slate-900/50 flex items-center justify-center border border-slate-800 mb-6">
                    <Zap size={32} className="text-slate-800" />
                </div>
                <h2 className="text-xl font-bold text-slate-400 tracking-tight">Select an Agent</h2>
                <p className="text-slate-600 text-sm mt-2 font-medium">Select an agent from the roster to see analysis details</p>
            </div>
        );
    }

    // Filter messages for this agent
    const agentMessages = messages.filter(m => m.agentId === agent.id || (m.role === 'user' && m.agentId === agent.id));

    // Mock Dimension Scores for preview
    const dimensionScores: DimensionScore[] = [
        { name: 'Fundamental', score: 85, color: 'bg-emerald-500' },
        { name: 'News', score: 45, color: 'bg-rose-500' },
        { name: 'Risk', score: 72, color: 'bg-emerald-500' },
        { name: 'Sentiment', score: 72, color: 'bg-cyan-500' },
        { name: 'Technical', score: 72, color: 'bg-cyan-500' },
    ];

    return (
        <div className="flex-1 h-full flex flex-col overflow-hidden animate-in fade-in duration-500 bg-slate-950/40">
            {/* Header / Tabs */}
            <div className="px-8 pt-6 border-b border-slate-900 bg-slate-950/20 backdrop-blur-md shrink-0">
                <div className="flex items-center gap-4 mb-6">
                    <img src={agent.avatar} alt={agent.name} className="w-10 h-10 rounded-xl bg-slate-900 p-1 border border-slate-800 shadow-xl" />
                    <div>
                        <h2 className="text-lg font-bold text-white tracking-tight">{agent.name}</h2>
                        <div className="flex items-center gap-2">
                            <span className="text-[10px] font-bold text-cyan-500 uppercase tracking-widest">{agent.role}</span>
                            <div className="w-1 h-1 bg-slate-800 rounded-full" />
                            <span className={`text-[10px] font-bold uppercase tracking-widest ${agent.status === 'running' ? 'text-emerald-500 animate-pulse' : 'text-slate-500'}`}>
                                {agent.status}
                            </span>
                        </div>
                    </div>
                </div>

                <div className="flex gap-8">
                    {(['Score', 'History', 'Output', 'Logs'] as const).map((tab) => (
                        <button
                            key={tab}
                            onClick={() => setActiveTab(tab)}
                            className={`pb-4 px-2 text-xs font-bold uppercase tracking-widest transition-all relative
                ${activeTab === tab ? 'text-cyan-400' : 'text-slate-600 hover:text-slate-400'}
              `}
                        >
                            {tab}
                            {activeTab === tab && (
                                <div className="absolute bottom-0 left-0 w-full h-0.5 bg-cyan-500 shadow-[0_0_8px_rgba(34,211,238,0.5)]" />
                            )}
                        </button>
                    ))}
                </div>
            </div>

            {/* Main Content Scroll Area */}
            <div className="flex-1 overflow-y-auto custom-scrollbar">
                {activeTab === 'Score' && (
                    <div className="p-8 space-y-8 animate-in slide-in-from-bottom-2 duration-300">
                        {/* Dimension Scores Card */}
                        <section className="bg-slate-900/20 border border-slate-800/50 rounded-2xl p-8 backdrop-blur-sm">
                            <div className="flex items-center gap-3 mb-8">
                                <BarChart3 size={18} className="text-cyan-400" />
                                <h3 className="text-sm font-bold text-white uppercase tracking-widest">Dimension Scores</h3>
                            </div>

                            <div className="space-y-6">
                                {dimensionScores.map((score) => (
                                    <div key={score.name} className="space-y-2">
                                        <div className="flex justify-between items-center text-[10px] font-bold uppercase tracking-widest">
                                            <span className="text-slate-400">{score.name}</span>
                                            <span className="text-white">{score.score}%</span>
                                        </div>
                                        <div className="h-1.5 w-full bg-slate-900 rounded-full overflow-hidden">
                                            <div
                                                className={`h-full ${score.color} transition-all duration-1000 ease-out shadow-[0_0_10px_rgba(34,211,238,0.2)]`}
                                                style={{ width: `${score.score}%` }}
                                            />
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </section>

                        {/* Financial Metrics */}
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                            <section className="bg-slate-900/20 border border-slate-800/50 rounded-2xl p-6">
                                <h3 className="text-sm font-bold text-white mb-6 flex items-center gap-2">
                                    <TrendingUp size={16} className="text-cyan-400" />
                                    Financial Health
                                </h3>
                                <div className="space-y-4">
                                    {[
                                        { label: 'P/B Ratio', value: '1.2x', trend: 'neutral' },
                                        { label: 'P/E Ratio', value: '24.5', trend: 'up' },
                                        { label: 'Debt/Equity', value: '0.45', trend: 'down' },
                                    ].map(m => (
                                        <div key={m.label} className="flex justify-between items-center border-b border-slate-900 pb-3">
                                            <span className="text-[11px] text-slate-500 font-medium">{m.label}</span>
                                            <span className="text-xs font-bold text-slate-200">{m.value}</span>
                                        </div>
                                    ))}
                                </div>
                            </section>

                            <section className="bg-slate-900/20 border border-slate-800/50 rounded-2xl p-6">
                                <h3 className="text-sm font-bold text-white mb-6 flex items-center gap-2">
                                    <FileText size={16} className="text-cyan-400" />
                                    Agent Summary
                                </h3>
                                <p className="text-xs text-slate-400 leading-relaxed">
                                    {agent.description}. Current status is <span className="text-cyan-400 font-bold">{agent.status}</span>.
                                    Waiting for further instructions or processing current stream data.
                                </p>
                            </section>
                        </div>
                    </div>
                )}

                {activeTab === 'History' && (
                    <div className="flex flex-col h-full animate-in slide-in-from-bottom-2 duration-300">
                        {agentMessages.length === 0 ? (
                            <div className="flex-1 flex flex-col items-center justify-center p-12 text-center">
                                <MessageSquare size={48} className="text-slate-900 mb-4" />
                                <h4 className="text-slate-500 font-bold text-xs uppercase tracking-widest">No activity yet</h4>
                                <p className="text-slate-700 text-[10px] mt-2 max-w-[200px]">This agent has not generated any messages or outputs for this session yet.</p>
                            </div>
                        ) : (
                            <div className="p-8 space-y-6">
                                {agentMessages.map((msg, i) => (
                                    <div key={msg.id || i} className={`group flex flex-col ${msg.role === 'user' ? 'items-end' : 'items-start'}`}>
                                        <div className={`max-w-[85%] rounded-2xl p-4 text-sm leading-relaxed border ${msg.role === 'user' ? 'bg-cyan-600/10 border-cyan-500/20 text-cyan-50' : 'bg-slate-900/40 border-slate-800/50 text-slate-300'}`}>
                                            {msg.content}

                                            {/* Financial Report View */}
                                            {msg.type === 'financial_report' && (
                                                <div className="mt-4 p-4 bg-slate-950/50 rounded-xl border border-slate-800/50">
                                                    <div className="flex items-center gap-2 mb-3 text-cyan-400">
                                                        <BarChart3 size={14} />
                                                        <span className="text-[10px] font-bold uppercase tracking-widest">Extracted Financials</span>
                                                    </div>
                                                    <div className="text-[10px] text-slate-400 italic">
                                                        Detailed financial metrics successfully extracted from SEC EDGAR. Switch to the "Score" tab for the full analysis.
                                                    </div>
                                                </div>
                                            )}

                                            {/* Interactive Ticker Selection */}
                                            {msg.type === 'interrupt_ticker' && msg.isInteractive && (
                                                <div className="mt-6 space-y-4">
                                                    <div className="flex items-center gap-2 text-amber-500">
                                                        <Zap size={14} className="animate-pulse" />
                                                        <span className="text-[10px] font-bold uppercase tracking-widest">Ticker Resolution Required</span>
                                                    </div>
                                                    <div className="grid grid-cols-1 gap-2">
                                                        {msg.data?.candidates?.map((c: any) => (
                                                            <button
                                                                key={c.symbol}
                                                                onClick={() => onSubmitCommand?.({ selected_symbol: c.symbol })}
                                                                className="flex items-center justify-between p-3 bg-slate-950/80 border border-slate-800 hover:border-cyan-500/50 hover:bg-cyan-500/5 transition-all rounded-xl text-left"
                                                            >
                                                                <div>
                                                                    <div className="text-xs font-bold text-white">{c.symbol}</div>
                                                                    <div className="text-[9px] text-slate-500 uppercase">{c.name}</div>
                                                                </div>
                                                                <div className="text-[9px] font-bold text-slate-600 bg-slate-900 px-2 py-0.5 rounded">
                                                                    {(c.confidence * 100).toFixed(0)}% Match
                                                                </div>
                                                            </button>
                                                        ))}
                                                    </div>
                                                </div>
                                            )}

                                            {/* Interactive Approval Request */}
                                            {msg.type === 'interrupt_approval' && msg.isInteractive && (
                                                <div className="mt-6 space-y-4">
                                                    <div className="flex items-center gap-2 text-amber-500">
                                                        <Zap size={14} className="animate-pulse" />
                                                        <span className="text-[10px] font-bold uppercase tracking-widest">Review & Approval Needed</span>
                                                    </div>
                                                    <div className="p-4 bg-slate-950/80 border border-slate-800 rounded-xl space-y-3">
                                                        <div className="flex justify-between items-center pb-2 border-b border-slate-900">
                                                            <span className="text-[10px] text-slate-500 uppercase font-bold">Analysis Target</span>
                                                            <span className="text-xs font-bold text-white">{msg.data?.details?.ticker}</span>
                                                        </div>
                                                        <div className="flex justify-between items-center pb-2 border-b border-slate-900">
                                                            <span className="text-[10px] text-slate-500 uppercase font-bold">Model Engine</span>
                                                            <span className="text-xs font-bold text-cyan-400 capitalize">{msg.data?.details?.model}</span>
                                                        </div>
                                                        <div className="flex justify-between items-center">
                                                            <span className="text-[10px] text-slate-500 uppercase font-bold">Audit Status</span>
                                                            <span className={`text-[10px] font-bold uppercase ${msg.data?.details?.audit_passed ? 'text-emerald-500' : 'text-rose-500'}`}>
                                                                {msg.data?.details?.audit_passed ? 'Passed' : 'Attention Required'}
                                                            </span>
                                                        </div>

                                                        <div className="pt-3 flex gap-2">
                                                            <button
                                                                onClick={() => onSubmitCommand?.({ approved: true })}
                                                                className="flex-1 bg-emerald-600 hover:bg-emerald-500 text-white text-[10px] font-bold py-2 rounded-lg transition-all uppercase tracking-widest shadow-lg shadow-emerald-500/20"
                                                            >
                                                                Approve Plan
                                                            </button>
                                                            <button
                                                                onClick={() => onSubmitCommand?.({ approved: false })}
                                                                className="flex-1 bg-slate-800 hover:bg-slate-700 text-slate-300 text-[10px] font-bold py-2 rounded-lg transition-all uppercase tracking-widest"
                                                            >
                                                                Reject
                                                            </button>
                                                        </div>
                                                    </div>
                                                </div>
                                            )}

                                            {msg.isInteractive && !msg.type?.startsWith('interrupt') && (
                                                <div className="mt-4 pt-4 border-t border-slate-800/50 flex gap-2">
                                                    <span className="text-[10px] font-bold text-amber-500 uppercase tracking-widest animate-pulse">Waiting for action...</span>
                                                </div>
                                            )}
                                        </div>
                                        <span className="mt-2 px-2 text-[9px] font-bold text-slate-700 uppercase tracking-widest">{msg.role}</span>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                )}

                {activeTab === 'Output' && (
                    <div className="p-8 flex items-center justify-center text-slate-600 h-full italic text-xs">
                        Final structured artifacts will appear here upon node completion.
                    </div>
                )}

                {activeTab === 'Logs' && (
                    <div className="p-8 font-mono text-[10px] text-slate-500 h-full">
                        <div className="flex items-center gap-2 mb-4 text-slate-400">
                            <Activity size={12} />
                            <span className="font-bold uppercase tracking-widest">System Execution Trace</span>
                        </div>
                        <div className="space-y-1">
                            <div>{">"} Initializing agent: {agent.id}</div>
                            <div>{">"} State: {agent.status}</div>
                            <div>{">"} Memory: Persisted (Postgres)</div>
                            <div className="text-cyan-900 animate-pulse">{">"} _awaiting_event_stream...</div>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};
