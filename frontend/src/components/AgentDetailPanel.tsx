import React, { useState } from 'react';
import Image from 'next/image';
import { AgentInfo, DimensionScore } from '@/types/agents';
import { Zap, Activity } from 'lucide-react';
import { Message } from '../types/protocol';
import { AgentWorkspaceTab } from './agent-detail/AgentWorkspaceTab';
import { AgentScoreTab } from './agent-detail/AgentScoreTab';
import { AgentHistoryTab } from './agent-detail/AgentHistoryTab';
import { AgentOutputTab } from './agent-detail/AgentOutputTab';

interface AgentDetailPanelProps {
    agent: AgentInfo | null;
    agentOutput?: any;
    messages: Message[];
    onSubmitCommand?: (payload: any) => Promise<void>;
    allAgentOutputs?: Record<string, any>;
    currentNode?: string | null;
    currentStatus?: string | null;
    activityFeed?: { id: string, node: string, agentId?: string, status: string, timestamp: number }[];
}

export const AgentDetailPanel: React.FC<AgentDetailPanelProps> = ({
    agent,
    agentOutput,
    messages,
    onSubmitCommand,
    allAgentOutputs = {},
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

    // Unified Output Resolution
    const rawOutput = agentOutput?.[agent.id] || agentOutput;
    const outputData = rawOutput?.artifact?.preview || rawOutput?.preview;

    console.log(`[AgentDetailPanel] DEBUG ${agent.id}:`, {
        agentId: agent.id,
        hasRawOutput: !!rawOutput,
        previewFound: !!outputData,
    });

    // Unified Ticker Resolution
    const intentOutput = allAgentOutputs['intent_extraction'];
    const intentRaw = intentOutput?.['intent_extraction'] || intentOutput;

    const resolvedTicker = intentRaw?.artifact?.preview?.resolved_ticker ||
        intentRaw?.preview?.resolved_ticker ||
        outputData?.ticker;

    // Get specific reports from resolved outputData
    const agentReports = outputData?.financial_reports || [];
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
    const revenueGrowth = (currentRev && prevRev) ? (currentRev - prevRev) / prevRev : 0.05;

    const peRatio = latestBase ? getFieldValue(latestBase.pe_ratio) : 20;

    // Dimension Scores
    const dimensionScores: DimensionScore[] = [
        {
            name: 'Fundamental',
            score: latestBase ? getScore(roe, 0, 0.3) :
                (agent.id === 'fundamental_analysis' ? 85 : 0),
            color: 'bg-emerald-500'
        },
        {
            name: 'Efficiency',
            score: latestBase ? getScore(roe > 0.15 ? 0.8 : 0.5, 0, 1) :
                (agent.id === 'fundamental_analysis' ? 65 : 0),
            color: 'bg-cyan-500'
        },
        {
            name: 'Risk',
            score: latestBase ? 100 - getScore(debtToEquity, 0, 2) :
                (agent.id === 'technical_analysis' && outputData ?
                    (outputData.signal_state?.risk_level === 'low' ? 90 :
                        outputData.signal_state?.risk_level === 'medium' ? 60 : 20) :
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
                (outputData?.valuation_score !== undefined ? outputData.valuation_score :
                    (agent.id === 'technical_analysis' && outputData ?
                        (Math.abs(outputData.signal_state?.z_score || 0) > 2 ? 80 : 50) :
                        (agent.id === 'calculator' ? 88 : (agent.id === 'fundamental_analysis' ? 40 : 0)))),
            color: 'bg-rose-500'
        },
    ];

    const financialMetrics = [
        { label: 'ROE', value: latestBase ? `${(roe * 100).toFixed(1)}%` : (outputData?.key_metrics?.ROE || 'N/A') },
        { label: 'P/E Ratio', value: latestBase && peRatio ? peRatio.toFixed(1) : 'N/A' },
        { label: 'Debt/Equity', value: latestBase ? debtToEquity.toFixed(2) : 'N/A' },
        { label: 'Revenue', value: latestBase ? `$${(currentRev / 1e9).toFixed(1)}B` : (outputData?.key_metrics?.Revenue || 'N/A') },
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
                    <AgentWorkspaceTab
                        agent={agent}
                        currentNode={currentNode}
                        currentStatus={currentStatus}
                        messages={messages}
                        onSubmitCommand={onSubmitCommand}
                        activityFeed={activityFeed}
                    />
                )}
                {activeTab === 'Score' && (
                    <AgentScoreTab
                        agent={agent}
                        dimensionScores={dimensionScores}
                        financialMetrics={financialMetrics}
                        latestReport={latestReport}
                    />
                )}

                {activeTab === 'History' && (
                    <AgentHistoryTab
                        agentMessages={agentMessages}
                        onSubmitCommand={onSubmitCommand}
                    />
                )}

                {/* Output tab - kept mounted for performance, hidden via CSS */}
                <div className={`p-0 h-full ${activeTab === 'Output' ? 'block' : 'hidden'}`}>
                    <AgentOutputTab
                        agent={agent}
                        rawOutput={rawOutput}
                        resolvedTicker={resolvedTicker}
                        status={agent.status}
                    />
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
