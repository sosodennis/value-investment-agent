import React, { useState } from 'react';
import Image from 'next/image';
import { AgentInfo, DimensionScore } from '../types/agents';
import { TrendingUp, BarChart3, FileText, Zap, MessageSquare, ListFilter, Activity, LayoutPanelTop, CheckCircle2, Clock } from 'lucide-react';
import { Message } from '../types/protocol';
import { NewsResearchOutput as NewsOutputType } from '../types/news';
import { FundamentalAnalysisOutput, NewsResearchOutput as NewsResearchOutputPanel, GenericAgentOutput, DebateOutput, TechnicalAnalysisOutput } from './agent-outputs';
import { TechnicalSignalOutput } from '../types/technical';
import { DynamicInterruptForm } from './DynamicInterruptForm';

interface AgentDetailPanelProps {
    agent: AgentInfo | null;
    agentOutput?: any;
    messages: Message[];
    onSubmitCommand?: (payload: any) => Promise<void>;
    financialReports?: any[];
    resolvedTicker?: string | null;
    currentNode?: string | null;
    currentStatus?: string | null;
    activityFeed?: { id: string, node: string, agentId?: string, status: string, timestamp: number }[];
}

export const AgentDetailPanel: React.FC<AgentDetailPanelProps> = ({
    agent,
    agentOutput,
    messages,
    onSubmitCommand,
    financialReports = [],
    resolvedTicker,
    currentNode,
    currentStatus,
    activityFeed = []
}) => {
    const [activeTab, setActiveTab] = useState<'Workspace' | 'Score' | 'History' | 'Output' | 'Logs'>('Workspace');

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
    const agentMessages = messages.filter(m => m.agentId === agent.id);

    // Get specific reports from agentOutput if available (for Planner)
    const agentReports = agentOutput?.financial_reports || (agent.id === 'fundamental_analysis' ? financialReports : []);
    const latestReport = agentReports.length > 0 ? agentReports[0] : null;

    const getScore = (val: any, min: number, max: number) => {
        if (val === null || val === undefined) return 50;
        const score = ((val - min) / (max - min)) * 100;
        return Math.min(Math.max(Math.round(score), 0), 100);
    };

    const getFieldValue = (field: any) => {
        if (!field) return 0;
        return typeof field.value === 'number' ? field.value : parseFloat(String(field.value)) || 0;
    };

    const latestBase = latestReport?.base;
    const previousBase = agentReports.length > 1 ? agentReports[1].base : null;

    const roe = latestBase ? (getFieldValue(latestBase.net_income) / (getFieldValue(latestBase.total_equity) || 1)) : 0;
    const debtToEquity = latestBase ? (getFieldValue(latestBase.total_liabilities) / (getFieldValue(latestBase.total_equity) || 1)) : 0;

    // Calculate growth if we have at least two years
    const currentRev = latestBase ? getFieldValue(latestBase.total_revenue) : 0;
    const prevRev = previousBase ? getFieldValue(previousBase.total_revenue) : 0;
    const revenueGrowth = (currentRev && prevRev) ? (currentRev - prevRev) / prevRev : 0.05; // Fallback to 5% if no prev year

    const peRatio = latestBase ? getFieldValue(latestBase.pe_ratio) : 20; // Default to 20 if missing

    // Dimension Scores - Scoped logic
    const dimensionScores: DimensionScore[] = [
        {
            name: 'Fundamental',
            score: latestBase ? getScore(roe, 0, 0.3) :
                (agent.id === 'fundamental_analysis' ? 85 : 0),
            color: 'bg-emerald-500'
        },
        {
            name: 'Efficiency',
            score: latestBase ? getScore(roe > 0.15 ? 0.8 : 0.5, 0, 1) : // Higher score if ROE is healthy
                (agent.id === 'fundamental_analysis' ? 65 : 0),
            color: 'bg-cyan-500'
        },
        {
            name: 'Risk',
            score: latestBase ? 100 - getScore(debtToEquity, 0, 2) :
                (agent.id === 'technical_analysis' && agentOutput ?
                    (agentOutput.signal_state?.risk_level === 'low' ? 90 :
                        agentOutput.signal_state?.risk_level === 'medium' ? 60 : 20) :
                    (agent.id === 'auditor' ? 90 : (agent.id === 'fundamental_analysis' ? 72 : 0))),
            color: 'bg-emerald-500'
        },
        {
            name: 'Growth',
            score: latestBase ? getScore(revenueGrowth, -0.1, 0.3) :
                (agent.id === 'fundamental_analysis' ? 60 : 0),
            color: 'bg-cyan-500'
        },
        {
            name: 'Valuation',
            score: latestBase ? 100 - getScore(peRatio, 10, 40) :
                (agent.id === 'technical_analysis' && agentOutput ?
                    (Math.abs(agentOutput.signal_state?.z_score || 0) > 2 ? 80 : 50) : // Z-score anomaly implies actionable valuation gap
                    (agent.id === 'calculator' ? 88 : (agent.id === 'fundamental_analysis' ? 40 : 0))),
            color: 'bg-rose-500'
        },
    ];

    const financialMetrics = [
        { label: 'ROE', value: latestBase ? `${(roe * 100).toFixed(1)}%` : 'N/A' },
        { label: 'P/E Ratio', value: latestBase && peRatio ? peRatio.toFixed(1) : 'N/A' },
        { label: 'Debt/Equity', value: latestBase ? debtToEquity.toFixed(2) : 'N/A' },
        { label: 'Rev Growth', value: latestBase && revenueGrowth ? `${(revenueGrowth * 100).toFixed(1)}%` : 'N/A' },
    ];

    return (
        <div className="flex-1 h-full flex flex-col overflow-hidden animate-in fade-in duration-500 bg-slate-950/40">
            {/* Header / Tabs */}
            <div className="px-8 pt-6 border-b border-slate-900 bg-slate-950/20 backdrop-blur-md shrink-0">
                <div className="flex items-center gap-4 mb-6">
                    <Image
                        src={agent.avatar}
                        alt={agent.name}
                        width={40}
                        height={40}
                        className="w-10 h-10 rounded-xl bg-slate-900 p-1 border border-slate-800 shadow-xl"
                    />
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
                    {(['Workspace', 'Score', 'History', 'Output', 'Logs'] as const).map((tab) => (
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
                {activeTab === 'Workspace' && (
                    <div className="p-8 space-y-8 animate-in slide-in-from-bottom-2 duration-300">
                        {/* Current Active Step */}
                        <section className="bg-slate-900/20 border border-slate-800/50 rounded-2xl p-6 backdrop-blur-sm">
                            <div className="flex items-center justify-between mb-6">
                                <div className="flex items-center gap-3">
                                    <LayoutPanelTop size={18} className="text-cyan-400" />
                                    <h3 className="text-sm font-bold text-white uppercase tracking-widest">Active Workspace</h3>
                                </div>
                                {agent.status === 'running' && (
                                    <div className="flex items-center gap-2 px-3 py-1 bg-cyan-500/10 border border-cyan-500/20 rounded-full">
                                        <div className="w-1.5 h-1.5 bg-cyan-500 rounded-full animate-pulse shadow-[0_0_5px_rgba(34,211,238,1)]" />
                                        <span className="text-[10px] font-bold text-cyan-500 uppercase tracking-tighter">Live Session</span>
                                    </div>
                                )}
                            </div>

                            <div className="flex flex-col gap-4">
                                <div className="bg-slate-950/50 border border-slate-800/80 rounded-xl p-5 flex items-center justify-between">
                                    <div>
                                        <div className="text-[10px] text-slate-500 font-bold uppercase tracking-widest mb-1">Current Task</div>
                                        <div className="text-lg font-bold text-white capitalize">{currentNode || (agent.status === 'running' ? 'Initializing...' : 'Idle')}</div>
                                    </div>
                                    <div className="text-right">
                                        <div className="text-[10px] text-slate-500 font-bold uppercase tracking-widest mb-1">Status</div>
                                        <div className={`text-sm font-bold ${currentStatus === 'attention' ? 'text-amber-500' : 'text-cyan-400'}`}>
                                            {currentStatus || (agent.status === 'running' ? 'In Progress' : 'Waiting')}
                                        </div>
                                    </div>
                                </div>

                                {/* Active Interrupts (Scoped) */}
                                {messages.filter(m => {
                                    if (!m.isInteractive) return false;

                                    // Strict Check: The backend MUST explicitly assign the interrupt to this agent.
                                    // We no longer guess based on node names.
                                    return m.agentId === agent.id;
                                }).map((msg) => (
                                    <div key={msg.id} className="mt-4">
                                        {msg.data?.schema ? (
                                            <DynamicInterruptForm
                                                schema={msg.data.schema}
                                                uiSchema={msg.data.ui_schema}
                                                title={msg.data.title}
                                                description={msg.data.description}
                                                onSubmit={(data) => onSubmitCommand?.(data)}
                                            />
                                        ) : (
                                            <div className="bg-amber-500/10 border border-amber-500/20 rounded-xl p-4 text-xs text-amber-200">
                                                Interruption requested, but no UI schema provided.
                                            </div>
                                        )}
                                    </div>
                                ))}
                            </div>
                        </section>

                        {/* Recent Activity Feed */}
                        <section className="bg-slate-900/10 border border-slate-900 rounded-2xl p-6">
                            <div className="flex items-center gap-3 mb-6">
                                <Activity size={16} className="text-slate-500" />
                                <h3 className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Activity History</h3>
                            </div>

                            <div className="space-y-4">
                                {(() => {
                                    // 1. Filter by agent
                                    const filteredFeed = activityFeed.filter(step =>
                                        step.agentId === agent.id
                                    );

                                    if (filteredFeed.length === 0) {
                                        return (
                                            <div className="py-8 text-center bg-slate-950/30 rounded-xl border border-dashed border-slate-900">
                                                <Clock size={20} className="text-slate-800 mx-auto mb-2" />
                                                <span className="text-[10px] text-slate-700 font-bold uppercase">No history tracked</span>
                                            </div>
                                        );
                                    }

                                    // 2. Map to unique nodes to avoid duplication in display if backend emits multiple events
                                    //    We take the LATEST status for each node name.
                                    const latestByNode = new Map<string, typeof filteredFeed[0]>();
                                    filteredFeed.forEach(step => {
                                        latestByNode.set(step.node, step);
                                    });

                                    // 3. Convert back to array and sort by timestamp (newest first)
                                    const displayFeed = Array.from(latestByNode.values())
                                        .sort((a, b) => b.timestamp - a.timestamp);

                                    return displayFeed.map((step, idx) => (
                                        <div key={step.id} className="flex gap-4 group">
                                            <div className="flex flex-col items-center gap-1">
                                                <div className={`w-2 h-2 rounded-full mt-1 ${idx === 0 ? 'bg-cyan-500 shadow-[0_0_5px_rgba(34,211,238,1)]' : 'bg-slate-800 group-hover:bg-slate-700'}`} />
                                                {idx !== displayFeed.length - 1 && <div className="w-[1px] flex-1 bg-slate-900" />}
                                            </div>
                                            <div className="flex-1 pb-4">
                                                <div className="flex justify-between items-start">
                                                    <span className={`text-xs font-bold leading-none capitalize ${idx === 0 ? 'text-slate-200' : 'text-slate-50'}`}>
                                                        {step.node.replace(/_/g, ' ')}
                                                    </span>
                                                    <span className="text-[9px] text-slate-700 font-mono">
                                                        {new Date(step.timestamp).toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                                                    </span>
                                                </div>
                                                <div className={`text-[10px] mt-1 uppercase tracking-tighter transition-all ${step.status === 'running' ? 'text-cyan-500 animate-pulse' : 'text-slate-600 group-hover:text-slate-500'}`}>
                                                    {step.status}
                                                </div>
                                            </div>
                                        </div>
                                    ));
                                })()}
                            </div>
                        </section>
                    </div>
                )}
                {activeTab === 'Score' && (
                    <div className="p-8 space-y-8 animate-in slide-in-from-bottom-2 duration-300">
                        {/* Dimension Scores Card */}
                        <section className="bg-slate-900/20 border border-slate-800/50 rounded-2xl p-8 backdrop-blur-sm">
                            <div className="flex items-center gap-3 mb-8">
                                <BarChart3 size={18} className="text-cyan-400" />
                                <h3 className="text-sm font-bold text-white uppercase tracking-widest">Analysis Dimensions</h3>
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
                                    Core Metrics
                                </h3>
                                <div className="space-y-4">
                                    {financialMetrics.map(m => (
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
                                    Agent Context
                                </h3>
                                <div className="text-xs text-slate-400 leading-relaxed space-y-2">
                                    <p>
                                        {agent.description}. Current status is <span className="text-cyan-400 font-bold">{agent.status}</span>.
                                    </p>
                                    <p>
                                        {latestReport ? (
                                            `Analyzing financial data for ${latestReport.ticker || 'selected company'} showing a ROE of ${(latestReport.roe * 100).toFixed(1)}%.`
                                        ) : (
                                            'Waiting for financial data to be extracted and processed.'
                                        )}
                                    </p>
                                </div>
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
                                                        Detailed financial metrics successfully extracted from SEC EDGAR. Switch to the &quot;Score&quot; tab for the full analysis.
                                                    </div>
                                                </div>
                                            )}

                                            {/* Dynamic Interrupt Forms (SDUI) */}
                                            {msg.isInteractive && msg.data?.schema && (
                                                <div className="mt-6">
                                                    <DynamicInterruptForm
                                                        schema={msg.data.schema}
                                                        uiSchema={msg.data.ui_schema}
                                                        title={msg.data.title}
                                                        description={msg.data.description}
                                                        onSubmit={(data) => onSubmitCommand?.(data)}
                                                    />
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

                {/* Output tab - kept mounted for performance, hidden via CSS */}
                <div className={`p-8 h-full ${activeTab === 'Output' ? 'block animate-in slide-in-from-bottom-2 duration-300' : 'hidden'}`}>
                    {agent.id === 'fundamental_analysis' ? (
                        <FundamentalAnalysisOutput
                            reports={agentReports}
                            resolvedTicker={resolvedTicker}
                            status={agent.status}
                        />
                    ) : agent.id === 'financial_news_research' ? (
                        <NewsResearchOutputPanel
                            output={agentOutput as NewsOutputType | null}
                            resolvedTicker={resolvedTicker}
                            status={agent.status}
                        />
                    ) : agent.id === 'debate' ? (
                        <DebateOutput
                            output={agentOutput}
                            resolvedTicker={resolvedTicker}
                            status={agent.status}
                        />
                    ) : agent.id === 'technical_analysis' ? (
                        <TechnicalAnalysisOutput
                            output={agentOutput as TechnicalSignalOutput | null}
                            status={agent.status}
                        />
                    ) : (
                        <GenericAgentOutput
                            agentName={agent.name}
                            output={agentOutput}
                            status={agent.status}
                        />
                    )}
                </div>

                {activeTab === 'Logs' && (
                    <div className="p-8 font-mono text-[10px] text-slate-500 h-full">
                        <div className="flex items-center gap-2 mb-4 text-slate-400">
                            <Activity size={12} />
                            <span className="font-bold uppercase tracking-widest">System Execution Trace: {agent.name}</span>
                        </div>
                        <div className="space-y-1">
                            <div>{">"} Initializing component: {agent.id}</div>
                            <div>{">"} Instance state: {agent.status}</div>
                            <div>{">"} Memory Scope: Scoped to {agent.id}</div>
                            {agent.status === 'running' ? (
                                <div className="text-cyan-900 animate-pulse">{">"} _awaiting_event_stream...</div>
                            ) : (
                                <div className="text-slate-800">{">"} _stream_detached_</div>
                            )}
                            {agentOutput && <div>{">"} Scoped data attached (size: {JSON.stringify(agentOutput).length} bytes)</div>}
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};
