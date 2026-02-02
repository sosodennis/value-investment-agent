import React from 'react';
import { AgentInfo } from '@/types/agents';
import { Message } from '@/types/protocol';
import { LayoutPanelTop, Activity, Clock } from 'lucide-react';
import { DynamicInterruptForm } from '../DynamicInterruptForm';

interface AgentWorkspaceTabProps {
    agent: AgentInfo;
    currentNode?: string | null;
    currentStatus?: string | null;
    messages: Message[];
    onSubmitCommand?: (payload: any) => Promise<void>;
    activityFeed?: { id: string, node: string, agentId?: string, status: string, timestamp: number }[];
}

export const AgentWorkspaceTab: React.FC<AgentWorkspaceTabProps> = ({
    agent,
    currentNode,
    currentStatus,
    messages,
    onSubmitCommand,
    activityFeed = []
}) => {
    return (
        <div className="p-8 space-y-8 animate-in slide-in-from-bottom-2 duration-300">
            {/* Current Active Step */}
            <section className="bg-bg-main/20 border border-border-subtle rounded-2xl p-6 backdrop-blur-sm">
                <div className="flex items-center justify-between mb-6">
                    <div className="flex items-center gap-3">
                        <LayoutPanelTop size={18} className="text-primary" />
                        <h3 className="text-sm font-bold text-white uppercase tracking-widest">Active Workspace</h3>
                    </div>
                    {agent.status === 'running' && (
                        <div className="flex items-center gap-2 px-3 py-1 bg-primary/10 border border-primary/20 rounded-full">
                            <div className="w-1.5 h-1.5 bg-primary rounded-full animate-pulse shadow-[0_0_5px_rgba(var(--cyan-500-rgb),1)]" />
                            <span className="text-[10px] font-bold text-primary uppercase tracking-tighter">Live Session</span>
                        </div>
                    )}
                </div>

                <div className="flex flex-col gap-4">
                    <div className="bg-bg-main/50 border border-border-main rounded-xl p-5 flex items-center justify-between">
                        <div>
                            <div className="text-label mb-1">Current Task</div>
                            <div className="text-lg font-bold text-white capitalize">{currentNode || (agent.status === 'running' ? 'Initializing...' : 'Idle')}</div>
                        </div>
                        <div className="text-right">
                            <div className="text-label mb-1">Status</div>
                            <div className={`text-sm font-bold ${currentStatus === 'attention' ? 'text-warning' : 'text-primary'}`}>
                                {currentStatus || (agent.status === 'running' ? 'In Progress' : 'Waiting')}
                            </div>
                        </div>
                    </div>

                    {/* Active Interrupts (Scoped) */}
                    {messages.filter(m => {
                        if (!m.isInteractive) return false;
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
                                <div className="bg-warning/10 border border-warning/20 rounded-xl p-4 text-xs text-warning/80">
                                    Interruption requested, but no UI schema provided.
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            </section>

            {/* Recent Activity Feed */}
            <section className="bg-bg-main/10 border border-border-main rounded-2xl p-6">
                <div className="flex items-center gap-3 mb-6">
                    <Activity size={16} className="text-slate-500" />
                    <h3 className="text-label">Activity History</h3>
                </div>

                <div className="space-y-4">
                    {(() => {
                        const filteredFeed = activityFeed.filter(step => step.agentId === agent.id);

                        if (filteredFeed.length === 0) {
                            return (
                                <div className="py-8 text-center bg-bg-main/30 rounded-xl border border-dashed border-border-main">
                                    <Clock size={20} className="text-slate-800 mx-auto mb-2" />
                                    <span className="text-label">No history tracked</span>
                                </div>
                            );
                        }

                        const latestByNode = new Map<string, typeof filteredFeed[0]>();
                        filteredFeed.forEach(step => {
                            latestByNode.set(step.node, step);
                        });

                        const displayFeed = Array.from(latestByNode.values())
                            .sort((a, b) => b.timestamp - a.timestamp);

                        return displayFeed.map((step, idx) => (
                            <div key={step.id} className="flex gap-4 group">
                                <div className="flex flex-col items-center gap-1">
                                    <div className={`w-2 h-2 rounded-full mt-1 ${idx === 0 ? 'bg-primary shadow-[0_0_5px_rgba(var(--cyan-500-rgb),1)]' : 'bg-slate-800 group-hover:bg-slate-700'}`} />
                                    {idx !== displayFeed.length - 1 && <div className="w-[1px] flex-1 bg-border-main" />}
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
                                    <div className={`text-[10px] mt-1 uppercase tracking-tighter transition-all ${step.status === 'running' ? 'text-primary animate-pulse' : 'text-slate-600 group-hover:text-slate-500'}`}>
                                        {step.status}
                                    </div>
                                </div>
                            </div>
                        ));
                    })()}
                </div>
            </section>
        </div>
    );
};
