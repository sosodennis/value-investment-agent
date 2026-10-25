import React, { useState } from 'react';
import Image from 'next/image';
import { AgentInfo, StandardAgentOutput } from '@/types/agents';
import { Zap, Activity } from 'lucide-react';
import { useFinancialData } from '@/hooks/useFinancialData';
import { AgentWorkspaceTab } from './AgentWorkspaceTab';
import { AgentOutputTab } from './AgentOutputTab';
import type { ConnectionState, TickerSelectionResponse, WorkflowActivity, WorkflowActivityState } from '@/features/workflow';

type DetailTab = 'Workspace' | 'Output' | 'Logs';
const DETAIL_TABS: DetailTab[] = ['Workspace', 'Output', 'Logs'];

interface AgentDetailPanelProps {
    agent: AgentInfo | null;
    agentOutput?: StandardAgentOutput | null;
    allAgentOutputs?: Record<string, StandardAgentOutput | null>;
    workflow: WorkflowActivityState | null;
    connectionState: ConnectionState;
    onCancelRun?: () => Promise<void>;
    onResumeInteraction?: (activity: WorkflowActivity, response: TickerSelectionResponse) => Promise<void>;
    isSubmitting?: boolean;
}

export const AgentDetailPanel: React.FC<AgentDetailPanelProps> = ({
    agent,
    agentOutput,
    allAgentOutputs = {},
    workflow,
    connectionState,
    onCancelRun,
    onResumeInteraction,
    isSubmitting = false,
}) => {
    const [activeTab, setActiveTab] = useState<DetailTab>('Workspace');

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

                <div className="flex items-center justify-between gap-8">
                    {onCancelRun && workflow && ['queued', 'running', 'waiting'].includes(workflow.runStatus) ? <button type="button" onClick={() => void onCancelRun()} className="rounded border border-error/40 px-3 py-2 text-xs font-semibold text-error hover:bg-error/10">Cancel run</button> : null}
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
            </div>

            {/* Main Content Scroll Area */}
            <div className="flex-1 overflow-y-auto custom-scrollbar bg-surface/50">
                {activeTab === 'Workspace' && (
                    <AgentWorkspaceTab
                        agent={agent}
                        workflow={workflow}
                        connectionState={connectionState}
                        onResumeInteraction={onResumeInteraction}
                        isSubmitting={isSubmitting}
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
                        <div className="terminal-text space-y-2 opacity-80">
                            <div className="flex gap-4"><span className="text-primary/80">[{connectionState.toUpperCase()}]</span><span className="text-on-surface-variant">Workflow run {workflow?.runId ?? 'not loaded'} · {workflow?.runStatus ?? 'idle'} · cursor {workflow?.cursor ?? 0}</span></div>
                            {(workflow?.recent ?? []).map((activity) => <div key={`${activity.activity_id}:${activity.attempt}:${activity.status}`} className="flex gap-4"><span className="text-outline shrink-0">{activity.scope_path.join(' / ')}</span><span className="text-on-surface-variant">{activity.label}: {activity.status}{activity.progress === undefined ? '' : ` (${activity.progress}%)`}</span></div>)}
                            {workflow?.recent.length === 0 ? <div className="text-on-surface-variant">No workflow activity has been recorded.</div> : null}

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
