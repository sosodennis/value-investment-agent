import React from 'react';
import type { AgentInfo } from '@/types/agents';
import { Activity } from 'lucide-react';
import type { ConnectionState, WorkflowActivityState } from '@/features/workflow';

interface AgentWorkspaceTabProps {
    agent: AgentInfo;
    workflow: WorkflowActivityState | null;
    connectionState: ConnectionState;
}

const statusTone: Record<string, string> = {
    queued: 'text-outline', running: 'text-primary', waiting: 'text-warning',
    completed: 'text-success', failed: 'text-error', cancelled: 'text-outline', skipped: 'text-outline',
};

export const AgentWorkspaceTab: React.FC<AgentWorkspaceTabProps> = ({ agent, workflow, connectionState }) => {
    const active = workflow ? [...workflow.active.values()] : [];
    const recent = workflow?.recent ?? [];
    return (
        <div className="p-8 space-y-6 animate-in slide-in-from-bottom-2 duration-300">
            <section className="rounded-2xl border border-outline-variant/30 bg-surface-container-low p-6">
                <div className="mb-5 flex items-center justify-between">
                    <div className="flex items-center gap-3"><Activity size={18} className="text-primary" /><h3 className="text-sm font-bold uppercase tracking-widest">Workflow activity</h3></div>
                    <span className="text-xs text-on-surface-variant">Connection: {connectionState}</span>
                </div>
                {!workflow ? <p className="py-6 text-sm text-on-surface-variant">Load a thread to see its activity snapshot.</p> : <>
                    <div className="mb-5 flex items-center gap-3 text-xs text-on-surface-variant"><span>Run {workflow.runId}</span><span>·</span><span>Status {workflow.runStatus}</span><span>·</span><span>Cursor {workflow.cursor}</span></div>
                    {active.length === 0 ? <p className="py-5 text-sm text-on-surface-variant">No active activities.</p> : <ActivitySet title="Active activities" activities={active} />}
                    {recent.length > 0 ? <ActivitySet title="Recent activities" activities={recent} /> : null}
                </>}
                <p className="mt-5 text-xs text-on-surface-variant">Selected analyst: {agent.name}</p>
            </section>
        </div>
    );
};

function ActivitySet({ title, activities }: { title: string; activities: NonNullable<WorkflowActivityState>['recent'] }) {
    return <section className="mt-5 border-t border-outline-variant/20 pt-4"><h4 className="mb-3 text-[10px] font-black uppercase tracking-widest text-outline">{title}</h4><ul className="space-y-2">
        {activities.map((activity) => <li key={`${activity.activity_id}:${activity.attempt}:${activity.status}`} className="rounded-lg bg-surface-container/60 px-3 py-2" style={{ marginLeft: `${Math.max(0, activity.scope_path.length - 1) * 12}px` }}>
            <div className="flex items-start justify-between gap-3"><div><div className="text-sm text-on-surface">{activity.label}</div><div className="mt-1 text-[10px] uppercase tracking-wide text-outline">{activity.kind} · attempt {activity.attempt} · {activity.scope_path.join(' / ')}</div></div><span className={`shrink-0 text-xs font-semibold ${statusTone[activity.status]}`}>{activity.status}</span></div>
            {activity.progress !== undefined ? <div className="mt-2 flex items-center gap-2"><progress className="h-1.5 flex-1 accent-cyan-400" max={100} value={activity.progress} aria-label={`${activity.label} progress`} /><span className="text-[10px] text-on-surface-variant">{activity.progress}%</span></div> : null}
        </li>)}
    </ul></section>;
}
