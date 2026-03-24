import React from 'react';
import { AgentInfo } from '@/types/agents';
import { Message } from '@/types/protocol';
import {
    InterruptRequestData,
    InterruptResumePayload,
    isInterruptRequestData,
} from '@/types/interrupts';
import { LayoutPanelTop, Activity, Clock } from 'lucide-react';
import { DynamicInterruptForm } from '@/components/workspace/DynamicInterruptForm';
import { useAgentActivity } from '@/hooks/useAgentActivity';

interface AgentWorkspaceTabProps {
    agent: AgentInfo;
    threadId?: string | null;
    currentNode?: string | null;
    currentStatus?: string | null;
    messages: Message[];
    onSubmitCommand?: (payload: InterruptResumePayload) => Promise<void>;
    projectionUpdatedAt?: number | null;
}

export const AgentWorkspaceTab: React.FC<AgentWorkspaceTabProps> = ({
    agent,
    threadId,
    currentNode,
    currentStatus,
    messages,
    onSubmitCommand,
    projectionUpdatedAt = null
}) => {
    const ACTIVITY_LIMIT = 5;
    const {
        events: activityEvents,
        hasMore: hasMoreActivity,
        isLoading: isActivityLoading,
        loadMore: loadMoreActivity,
    } = useAgentActivity(threadId, agent.id, ACTIVITY_LIMIT);
    const canLoadMoreActivity =
        Boolean(threadId) && hasMoreActivity && !isActivityLoading;

    const formatLag = (ms: number): string => {
        if (ms < 1000) return 'now';
        const totalSeconds = Math.floor(ms / 1000);
        if (totalSeconds < 60) return `${totalSeconds}s`;
        const minutes = Math.floor(totalSeconds / 60);
        const seconds = totalSeconds % 60;
        if (minutes < 60) return `${minutes}m ${seconds}s`;
        const hours = Math.floor(minutes / 60);
        const remMinutes = minutes % 60;
        return `${hours}h ${remMinutes}m`;
    };

    const now = Date.now();
    const lagMs =
        projectionUpdatedAt && projectionUpdatedAt > 0
            ? Math.max(0, now - projectionUpdatedAt)
            : null;
    const staleThresholdMs = 30_000;
    const isStale = lagMs !== null && lagMs > staleThresholdMs;
    const projectionLabel =
        lagMs === null
            ? 'Sync pending'
            : isStale
              ? `Lagging ${formatLag(lagMs)}`
              : `Synced ${formatLag(lagMs)} ago`;
    const projectionTime =
        lagMs === null
            ? null
            : new Date(projectionUpdatedAt as number).toLocaleTimeString([], {
                  hour12: false,
                  hour: '2-digit',
                  minute: '2-digit',
                  second: '2-digit',
              });
    const projectionTone = isStale ? 'text-warning' : 'text-on-surface-variant';
    const projectionBorder = isStale ? 'border-warning/30' : 'border-outline-variant/30';
    const projectionBg = isStale ? 'bg-warning/10' : 'bg-surface-container/60';
    const projectionTitle =
        lagMs === null
            ? 'Projection sync is not available yet.'
            : `Projection last updated at ${projectionTime}. Read model may lag live execution.`;
    const interruptMessages = messages.filter(
        (message): message is Message & { data: InterruptRequestData } =>
            !!message.isInteractive &&
            message.agentId === agent.id &&
            isInterruptRequestData(message.data)
    );

    return (
        <div className="p-8 space-y-8 animate-in slide-in-from-bottom-2 duration-300">
            {/* Current Active Step */}
            <section className="bg-surface-container-low border border-outline-variant/30 rounded-2xl p-6 backdrop-blur-sm">
                <div className="flex items-center justify-between mb-6">
                    <div className="flex items-center gap-3">
                        <LayoutPanelTop size={18} className="text-primary" />
                        <h3 className="text-sm font-bold text-on-surface uppercase tracking-widest">Active Workspace</h3>
                    </div>
                    <div className="flex items-center gap-2">
                        {agent.status === 'running' && (
                            <div className="flex items-center gap-2 px-3 py-1 bg-primary/10 border border-primary/20 rounded-full">
                                <div className="w-1.5 h-1.5 bg-primary rounded-full animate-pulse shadow-[0_0_5px_rgba(var(--cyan-500-rgb),1)]" />
                                <span className="text-[10px] font-bold text-primary uppercase tracking-tighter">Live Session</span>
                            </div>
                        )}
                        <div
                            className={`flex items-center gap-2 px-3 py-1 rounded-full border ${projectionBg} ${projectionBorder}`}
                            title={projectionTitle}
                        >
                            <Clock size={12} className={projectionTone} />
                            <span className="text-[10px] font-bold uppercase tracking-tighter text-outline">Projection</span>
                            <span className={`text-[10px] font-bold uppercase tracking-tighter ${projectionTone}`}>
                                {projectionLabel}
                            </span>
                        </div>
                    </div>
                </div>

                <div className="flex flex-col gap-4">
                    <div className="bg-surface-container border border-outline-variant/30 rounded-xl p-5 flex items-center justify-between">
                        <div>
                            <div className="text-[10px] font-black uppercase tracking-widest text-outline mb-1">Current Task</div>
                            <div className="text-lg font-bold text-on-surface capitalize">{currentNode || (agent.status === 'running' ? 'Initializing...' : 'Idle')}</div>
                        </div>
                        <div className="text-right">
                            <div className="text-[10px] font-black uppercase tracking-widest text-outline mb-1">Status</div>
                            <div className={`text-sm font-bold ${currentStatus === 'attention' ? 'text-warning' : 'text-primary'}`}>
                                {currentStatus || (agent.status === 'running' ? 'In Progress' : 'Waiting')}
                            </div>
                        </div>
                    </div>

                    {/* Active Interrupts (Scoped) */}
                    {interruptMessages.map((msg) => (
                        <div key={msg.id} className="mt-4">
                            <DynamicInterruptForm
                                schema={msg.data.schema}
                                uiSchema={msg.data.ui_schema}
                                title={msg.data.title}
                                description={msg.data.description}
                                onSubmit={(data) => onSubmitCommand?.(data)}
                            />
                        </div>
                    ))}
                </div>
            </section>

            {/* Recent Activity Feed */}
            <section className="bg-surface-container-low border border-outline-variant/30 rounded-2xl p-6">
                <div className="flex items-center gap-3 mb-6">
                    <Activity size={16} className="text-outline" />
                    <h3 className="text-[10px] font-black uppercase tracking-widest text-outline">Activity History</h3>
                </div>

                <div className="flex items-center justify-between text-[10px] text-on-surface-variant mb-4 uppercase tracking-widest">
                    <span>
                        {`Showing last ${Math.max(
                            ACTIVITY_LIMIT,
                            activityEvents.length
                        )} events`}
                    </span>
                    <button
                        type="button"
                        onClick={() => loadMoreActivity()}
                        disabled={!canLoadMoreActivity}
                        className={`text-[10px] font-bold uppercase tracking-widest transition-colors ${
                            canLoadMoreActivity
                                ? 'text-primary hover:text-primary-variant'
                                : 'text-outline/50 cursor-not-allowed'
                        }`}
                    >
                        {hasMoreActivity ? 'View full history' : 'Full history loaded'}
                    </button>
                </div>

                <div className="space-y-4">
                    {(() => {
                        if (activityEvents.length === 0) {
                            return (
                                <div className="py-8 text-center bg-surface-container/30 rounded-xl border border-dashed border-outline-variant/30">
                                    <Clock size={20} className="text-outline mx-auto mb-2" />
                                    <span className="text-[10px] font-black uppercase tracking-widest text-outline">No recent activity in last 5 events</span>
                                </div>
                            );
                        }

                        return activityEvents.map((step, idx) => {
                            const isCurrent = step.isCurrent;
                            const isRunning = step.status === 'running' && isCurrent;
                            const statusTone =
                                step.status === 'error'
                                    ? 'text-error'
                                    : step.status === 'attention' || step.status === 'degraded'
                                      ? 'text-warning'
                                      : isRunning
                                        ? 'text-primary animate-pulse'
                                        : step.status === 'done'
                                          ? 'text-success'
                                          : 'text-slate-600 group-hover:text-slate-500';
                            return (
                            <div key={step.id} className="flex gap-4 group">
                                <div className="flex flex-col items-center gap-1">
                                    <div
                                        className={`w-2 h-2 rounded-full mt-1 ${
                                            isCurrent
                                                ? 'bg-primary shadow-[0_0_5px_rgba(var(--cyan-500-rgb),1)]'
                                                : 'bg-slate-800 group-hover:bg-slate-700'
                                        }`}
                                    />
                                    {idx !== activityEvents.length - 1 && <div className="w-[1px] flex-1 bg-border-main" />}
                                </div>
                                <div className="flex-1 pb-4">
                                    <div className="flex justify-between items-start">
                                        <span className={`text-xs font-bold leading-none capitalize ${isCurrent ? 'text-on-surface' : 'text-on-surface-variant'}`}>
                                            {step.node.replace(/_/g, ' ')}
                                        </span>
                                        <span className="text-[9px] text-outline font-mono">
                                            {new Date(step.timestamp).toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                                        </span>
                                    </div>
                                    <div className={`text-[10px] mt-1 uppercase tracking-tighter transition-all ${statusTone}`}>
                                        {step.status}
                                    </div>
                                </div>
                            </div>
                            );
                        });
                    })()}
                </div>
            </section>
        </div>
    );
};
