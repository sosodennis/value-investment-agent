import React, { useState } from 'react';
import Image from 'next/image';
import { AgentInfo, StandardAgentOutput } from '@/types/agents';
import { InterruptResumePayload } from '@/types/interrupts';
import { Zap, Activity } from 'lucide-react';
import { Message } from '@/types/protocol';
import { useFinancialData } from '@/hooks/useFinancialData';
import { AgentWorkspaceTab } from './AgentWorkspaceTab';
import { AgentOutputTab } from './AgentOutputTab';
import { useAgentActivity } from '@/hooks/useAgentActivity';

type DetailTab = 'Workspace' | 'Output' | 'Logs';
const DETAIL_TABS: DetailTab[] = ['Workspace', 'Output', 'Logs'];

interface AgentDetailPanelProps {
    agent: AgentInfo | null;
    agentOutput?: StandardAgentOutput | null;
    messages: Message[];
    onSubmitCommand?: (payload: InterruptResumePayload) => Promise<void>;
    allAgentOutputs?: Record<string, StandardAgentOutput | null>;
    currentNode?: string | null;
    currentStatus?: string | null;
    threadId?: string | null;
    projectionUpdatedAt?: number | null;
}

export const AgentDetailPanel: React.FC<AgentDetailPanelProps> = ({
    agent,
    agentOutput,
    messages,
    onSubmitCommand,
    allAgentOutputs = {},
    currentNode,
    currentStatus,
    threadId,
    projectionUpdatedAt = null
}) => {
    const [activeTab, setActiveTab] = useState<DetailTab>('Workspace');
    const LOG_ACTIVITY_LIMIT = 20;
    const LOG_ACTIVITY_PAGE_SIZE = 50;
    const {
        events: logEvents,
        hasMore: hasMoreLogs,
        isLoading: isLogsLoading,
        loadMore: loadMoreLogs,
    } = useAgentActivity(
        threadId,
        agent?.id ?? null,
        LOG_ACTIVITY_LIMIT,
        LOG_ACTIVITY_PAGE_SIZE
    );
    const canLoadMoreLogs =
        Boolean(threadId) && hasMoreLogs && !isLogsLoading;

    // Use our new hook to derive all financial data
    const {
        resolvedTicker,
        rawOutput
    } = useFinancialData(agent?.id || '', allAgentOutputs);

    if (!agent) {
        return (
            <div className="flex-1 h-full flex flex-col items-center justify-center bg-surface p-12">
                <div className="tech-card p-12 flex flex-col items-center justify-center max-w-md w-full animate-fade-in text-center group bg-surface-container-low border border-outline-variant/30 rounded-[24px]">
                    <div className="w-20 h-20 rounded-2xl bg-surface-container flex items-center justify-center border border-outline-variant/30 mb-8 shadow-lg transition-transform duration-500 group-hover:rotate-12 group-hover:scale-110">
                        <Zap size={32} className="text-on-surface-variant group-hover:text-primary transition-colors" />
                    </div>
                    <h2 className="text-[10px] font-black uppercase tracking-widest text-primary mb-2">System Awaiting Selection</h2>
                    <h3 className="text-xl font-black text-on-surface tracking-widest uppercase mb-4">Initialize Analyst</h3>
                    <p className="text-on-surface-variant text-xs font-medium leading-relaxed">
                        Select an intelligence agent from the roster to deploy and view real-time valuation analysis, audit logs, and risk models.
                    </p>
                    <div className="mt-8 flex gap-2">
                        <div className="w-1.5 h-1.5 rounded-full bg-primary/40" />
                        <div className="w-1.5 h-1.5 rounded-full bg-primary/20" />
                        <div className="w-1.5 h-1.5 rounded-full bg-primary/10" />
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className="flex-1 h-full flex flex-col overflow-hidden animate-in fade-in duration-500 bg-surface">
            {/* Header / Tabs */}
            <div className="px-8 pt-6 bg-transparent shrink-0">
                <div className="flex items-center gap-4 mb-6">
                    <Image
                        src={agent.avatar}
                        alt={agent.name}
                        width={40}
                        height={40}
                        className="w-10 h-10 rounded-xl bg-surface-container-low p-1 border border-outline-variant/30 shadow-md"
                    />
                    <div>
                        <h2 className="text-lg font-bold text-on-surface tracking-tight">{agent.name}</h2>
                        <div className="flex items-center gap-2">
                            <span className="text-[10px] font-bold text-primary uppercase tracking-widest">{agent.role}</span>
                            <div className="w-1 h-1 bg-outline-variant rounded-full" />
                            <span className={`text-[10px] font-bold uppercase tracking-widest ${agent.status === 'running' ? 'text-primary animate-pulse' : 'text-on-surface-variant'}`}>
                                {agent.status}
                            </span>
                        </div>
                    </div>
                </div>

                <div className="flex gap-8">
                    {DETAIL_TABS.map((tab) => (
                        <button
                            key={tab}
                            onClick={() => setActiveTab(tab)}
                            className={`pb-4 px-2 text-[10px] font-bold uppercase tracking-widest transition-colors relative
                ${activeTab === tab ? 'text-primary' : 'text-on-surface-variant hover:text-on-surface'}
              `}
                        >
                            {tab}
                            {activeTab === tab && (
                                <div className="absolute bottom-0 left-0 w-full h-0.5 bg-primary shadow-[0_0_8px_rgba(var(--primary-rgb),0.5)]" />
                            )}
                        </button>
                    ))}
                </div>
            </div>

            {/* Main Content Scroll Area */}
            <div className="flex-1 overflow-y-auto custom-scrollbar bg-surface/50">
                {activeTab === 'Workspace' && (
                    <AgentWorkspaceTab
                        agent={agent}
                        threadId={threadId}
                        currentNode={currentNode}
                        currentStatus={currentStatus}
                        messages={messages}
                        onSubmitCommand={onSubmitCommand}
                        projectionUpdatedAt={projectionUpdatedAt}
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
                    <div className="p-8 h-full bg-surface-container/30">
                        <div className="flex items-center gap-3 mb-6 border-b border-outline-variant/30 pb-4">
                            <Activity size={12} className="text-primary" />
                            <span className="text-[10px] font-black text-outline uppercase tracking-[0.3em]">System Trace :: {agent.name}</span>
                        </div>
                        <div className="flex items-center justify-between text-[9px] uppercase tracking-widest text-on-surface-variant mb-4">
                            <span>
                                {`Showing last ${Math.max(
                                    LOG_ACTIVITY_LIMIT,
                                    logEvents.length
                                )} events`}
                            </span>
                            <button
                                type="button"
                                onClick={() => loadMoreLogs()}
                                disabled={!canLoadMoreLogs}
                                className={`font-bold transition-colors ${
                                    canLoadMoreLogs
                                        ? 'text-primary hover:text-primary-variant'
                                        : 'text-outline/50 cursor-not-allowed'
                                }`}
                            >
                                {hasMoreLogs ? 'View full history' : 'Full history loaded'}
                            </button>
                        </div>
                        <div className="terminal-text space-y-2 opacity-80">
                            <div className="flex gap-4">
                                <span className="text-outline shrink-0">10:48:02</span>
                                <span className="text-primary/80">[INIT]</span>
                                <span className="text-on-surface-variant">Deploying context for {agent.id}...</span>
                            </div>

                            {/* Dynamic Activity Feed mapping */}
                            {logEvents.map((step) => {
                                const isCurrent = step.isCurrent;
                                const isRunning = step.status === 'running' && isCurrent;
                                const statusLabel = isRunning
                                    ? 'WAIT'
                                    : step.status.toUpperCase();
                                const statusTone =
                                    step.status === 'error'
                                        ? 'text-error'
                                        : step.status === 'attention' || step.status === 'degraded'
                                          ? 'text-warning'
                                          : isRunning
                                            ? 'text-primary animate-pulse'
                                            : 'text-emerald-500/80';
                                return (
                                    <div key={step.id} className="flex gap-4">
                                        <span className="text-outline shrink-0">
                                            {new Date(step.timestamp).toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                                        </span>
                                        <span className={`uppercase tracking-tighter ${statusTone}`}>
                                            [{statusLabel}]
                                        </span>
                                        <span className="text-on-surface-variant">
                                            {step.node.replace(/_/g, ' ')}: {step.status}
                                        </span>
                                    </div>
                                );
                            })}

                            {/* Fallback Current Status if no feed yet */}
                            {logEvents.length === 0 && (
                                <div key="current-status" className="flex gap-4">
                                    <span className="text-outline shrink-0">--:--:--</span>
                                    <span className={`font-bold uppercase tracking-widest ${agent.status === 'running' ? 'text-primary animate-pulse' : 'text-on-surface-variant'}`}>
                                        [{agent.status === 'running' ? 'WAIT' : 'DONE'}]
                                    </span>
                                    <span className="text-on-surface-variant">
                                        {agent.status === 'running' ? 'Awaiting job stream from LangGraph…' : 'Stream detached, artifacts persistent.'}
                                    </span>
                                </div>
                            )}

                            {agentOutput && (
                                <div className="flex gap-4">
                                    <span className="text-outline shrink-0">10:48:21</span>
                                    <span className="text-primary/80">[DATA]</span>
                                    <span className="text-on-surface-variant truncate">Context: {JSON.stringify(agentOutput).slice(0, 60)}... ({JSON.stringify(agentOutput).length} bytes)</span>
                                </div>
                            )}
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};
