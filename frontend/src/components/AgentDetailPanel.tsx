import React, { useState } from 'react';
import Image from 'next/image';
import { AgentInfo } from '@/types/agents';
import { Zap, Activity } from 'lucide-react';
import { Message } from '../types/protocol';
import { useFinancialData } from '../hooks/useFinancialData';
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
            <div className="flex-1 h-full flex flex-col items-center justify-center bg-bg-main/10">
                <div className="w-24 h-24 rounded-full bg-slate-900/50 flex items-center justify-center border border-slate-800 mb-6 shadow-2xl">
                    <Zap size={32} className="text-slate-800" />
                </div>
                <h2 className="text-xl font-bold text-slate-400 tracking-tight text-white/50">Select an Agent</h2>
                <p className="text-slate-600 text-sm mt-2 font-medium">Select an agent from the roster to see analysis details</p>
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
                    <div className="p-8 font-mono text-[10px] text-slate-500 h-full">
                        <div className="flex items-center gap-2 mb-4 text-slate-400">
                            <Activity size={12} />
                            <span className="font-bold uppercase tracking-widest">Execution Trace: {agent.name}</span>
                        </div>
                        <div className="space-y-1">
                            <div>{">"} Scope: {agent.id}</div>
                            <div>{">"} Instance state: {agent.status}</div>
                            {agent.status === 'running' ? (
                                <div className="text-primary/60 animate-pulse">{">"} _awaiting_job_stream...</div>
                            ) : (
                                <div className="text-slate-800">{">"} _stream_detached_</div>
                            )}
                            {agentOutput && <div>{">"} Data context attached: {JSON.stringify(agentOutput).length} bytes</div>}
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};
