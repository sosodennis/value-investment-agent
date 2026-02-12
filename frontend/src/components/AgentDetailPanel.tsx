import React, { useState } from 'react';
import Image from 'next/image';
import { AgentInfo, StandardAgentOutput } from '@/types/agents';
import { InterruptResumePayload } from '@/types/interrupts';
import { Zap, Activity } from 'lucide-react';
import { Message } from '../types/protocol';
import { useFinancialData } from '../hooks/useFinancialData';
import { AgentWorkspaceTab } from './agent-detail/AgentWorkspaceTab';
import { AgentScoreTab } from './agent-detail/AgentScoreTab';
import { AgentHistoryTab } from './agent-detail/AgentHistoryTab';
import { AgentOutputTab } from './agent-detail/AgentOutputTab';

interface AgentDetailPanelProps {
    agent: AgentInfo | null;
    agentOutput?: StandardAgentOutput | null;
    messages: Message[];
    onSubmitCommand?: (payload: InterruptResumePayload) => Promise<void>;
    allAgentOutputs?: Record<string, StandardAgentOutput | null>;
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

    // Use our new hook to derive all financial data
    const {
        resolvedTicker,
        dimensionScores,
        financialMetrics,
        latestReport,
        rawOutput
    } = useFinancialData(agent?.id || '', allAgentOutputs);

    if (!agent) {
        return (
            <div className="flex-1 h-full flex flex-col items-center justify-center bg-bg-main/10 p-12">
                <div className="tech-card p-12 flex flex-col items-center justify-center max-w-md w-full animate-fade-in text-center group">
                    <div className="w-20 h-20 rounded-2xl bg-slate-900 flex items-center justify-center border border-white/5 mb-8 shadow-2xl transition-transform duration-500 group-hover:rotate-12 group-hover:scale-110">
                        <Zap size={32} className="text-slate-800 group-hover:text-cyan-500 transition-colors" />
                    </div>
                    <h2 className="text-label mb-2">System Awaiting Selection</h2>
                    <h3 className="text-xl font-black text-white tracking-widest uppercase mb-4">Initialize Analyst</h3>
                    <p className="text-slate-500 text-xs font-medium leading-relaxed">
                        Select an intelligence agent from the roster to deploy and view real-time valuation analysis, audit logs, and risk models.
                    </p>
                    <div className="mt-8 flex gap-2">
                        <div className="w-1.5 h-1.5 rounded-full bg-cyan-500/20" />
                        <div className="w-1.5 h-1.5 rounded-full bg-cyan-500/10" />
                        <div className="w-1.5 h-1.5 rounded-full bg-cyan-500/5" />
                    </div>
                </div>
            </div>
        );
    }

    // Filter messages for this agent
    const agentMessages = messages.filter(m => m.agentId === agent.id);

    return (
        <div className="flex-1 h-full flex flex-col overflow-hidden animate-in fade-in duration-500 bg-bg-main/40">
            {/* Header / Tabs */}
            <div className="px-8 pt-6 border-b border-border-main bg-bg-main/20 backdrop-blur-md shrink-0">
                <div className="flex items-center gap-4 mb-6">
                    <Image
                        src={agent.avatar}
                        alt={agent.name}
                        width={40}
                        height={40}
                        className="w-10 h-10 rounded-xl bg-slate-900 p-1 border border-border-subtle shadow-xl"
                    />
                    <div>
                        <h2 className="text-lg font-bold text-white tracking-tight">{agent.name}</h2>
                        <div className="flex items-center gap-2">
                            <span className="text-[10px] font-bold text-primary uppercase tracking-widest">{agent.role}</span>
                            <div className="w-1 h-1 bg-slate-800 rounded-full" />
                            <span className={`text-[10px] font-bold uppercase tracking-widest ${agent.status === 'running' ? 'text-success animate-pulse' : 'text-slate-500'}`}>
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
                            className={`pb-4 px-2 text-[10px] font-bold uppercase tracking-widest transition-all relative
                ${activeTab === tab ? 'text-primary' : 'text-slate-600 hover:text-slate-400'}
              `}
                        >
                            {tab}
                            {activeTab === tab && (
                                <div className="absolute bottom-0 left-0 w-full h-0.5 bg-primary shadow-[0_0_8px_rgba(var(--cyan-500-rgb),0.5)]" />
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
                <div className={`h-full ${activeTab === 'Output' ? 'block' : 'hidden'}`}>
                    <AgentOutputTab
                        agent={agent}
                        rawOutput={rawOutput}
                        resolvedTicker={resolvedTicker}
                        status={agent.status}
                    />
                </div>

                {activeTab === 'Logs' && (
                    <div className="p-8 h-full bg-slate-950/20">
                        <div className="flex items-center gap-3 mb-6 border-b border-white/5 pb-4">
                            <Activity size={12} className="text-cyan-500" />
                            <span className="text-label tracking-[0.3em]">System Trace :: {agent.name}</span>
                        </div>
                        <div className="terminal-text space-y-2 opacity-80">
                            <div className="flex gap-4">
                                <span className="text-slate-600 shrink-0">10:48:02</span>
                                <span className="text-cyan-500/80">[INIT]</span>
                                <span className="text-slate-300">Deploying context for {agent.id}...</span>
                            </div>

                            {/* Dynamic Activity Feed mapping */}
                            {activityFeed
                                .filter(step => step.agentId === agent.id)
                                .map((step) => (
                                    <div key={step.id} className="flex gap-4">
                                        <span className="text-slate-600 shrink-0">
                                            {new Date(step.timestamp).toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                                        </span>
                                        <span className={`uppercase tracking-tighter ${step.status === 'running' ? 'text-primary animate-pulse' : 'text-emerald-500/80'}`}>
                                            [{step.status === 'running' ? 'WAIT' : 'DONE'}]
                                        </span>
                                        <span className="text-slate-300">
                                            {step.node.replace(/_/g, ' ')}: {step.status}
                                        </span>
                                    </div>
                                ))}

                            {/* Fallback Current Status if no feed yet */}
                            {activityFeed.filter(step => step.agentId === agent.id).length === 0 && (
                                <div key="current-status" className="flex gap-4">
                                    <span className="text-slate-600 shrink-0">--:--:--</span>
                                    <span className={`font-bold uppercase tracking-widest ${agent.status === 'running' ? 'text-primary animate-pulse' : 'text-slate-500'}`}>
                                        [{agent.status === 'running' ? 'WAIT' : 'DONE'}]
                                    </span>
                                    <span className="text-slate-300">
                                        {agent.status === 'running' ? 'Awaiting job stream from LangGraph...' : 'Stream detached, artifacts persistent.'}
                                    </span>
                                </div>
                            )}

                            {agentOutput && (
                                <div className="flex gap-4">
                                    <span className="text-slate-600 shrink-0">10:48:21</span>
                                    <span className="text-cyan-500/80">[DATA]</span>
                                    <span className="text-slate-400 truncate">Context: {JSON.stringify(agentOutput).slice(0, 60)}... ({JSON.stringify(agentOutput).length} bytes)</span>
                                </div>
                            )}
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};
