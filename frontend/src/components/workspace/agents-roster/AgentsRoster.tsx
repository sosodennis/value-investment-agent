import React from 'react';
import { AgentInfo } from '@/types/agents';
import { AgentCard } from './AgentCard';

interface AgentsRosterProps {
    agents: AgentInfo[];
    selectedAgentId: string | null;
    onAgentSelect: (agentId: string) => void;
    systemStatus?: 'online' | 'offline';
    stage?: string;
    targetTicker?: string;
}

export const AgentsRoster: React.FC<AgentsRosterProps> = ({
    agents,
    selectedAgentId,
    onAgentSelect,
    systemStatus = 'online',
    stage = 'Idle',
    targetTicker = '',
}) => {
    const activeAgents = agents.filter(a => a.status !== 'idle').length;

    return (
        <div className="w-full h-full flex flex-col bg-transparent backdrop-blur-md overflow-hidden shrink-0">
            {/* System Stats Cluster */}
            <div className="flex flex-col gap-4 p-6 border-b border-outline-variant/20">
                <div className="flex items-center justify-between">
                     <div className="flex flex-col gap-1">
                         <span className="text-label">System</span>
                         <div className="flex items-center gap-1.5">
                              <div className={`w-1.5 h-1.5 rounded-full ${systemStatus === 'online' ? 'bg-success shadow-[0_0_8px_rgba(var(--emerald-500-rgb),0.5)]' : 'bg-error'}`} />
                              <span className={`text-[11px] font-black uppercase ${systemStatus === 'online' ? 'text-success' : 'text-error'}`}>{systemStatus}</span>
                         </div>
                     </div>
                     <div className="flex flex-col gap-1 items-end">
                         <span className="text-label">Agents</span>
                         <span className="text-[11px] font-black uppercase text-primary">{activeAgents} Active</span>
                     </div>
                </div>
                <div className="flex items-center justify-between">
                     <div className="flex flex-col gap-1">
                         <span className="text-label">Target</span>
                         <span className="text-[11px] font-black uppercase text-primary">{targetTicker || '---'}</span>
                     </div>
                     <div className="flex flex-col gap-1 items-end">
                         <span className="text-label">Stage</span>
                         <span className="text-[11px] font-black uppercase text-primary">{stage}</span>
                     </div>
                </div>
            </div>

            <div className="px-6 py-5 flex items-center justify-between">
                <h3 className="text-[10px] font-black uppercase tracking-widest text-outline">
                    Agents Roster
                </h3>
                <div className="flex gap-1" aria-hidden="true">
                    <div className="w-1 h-1 bg-outline-variant rounded-full" />
                    <div className="w-1 h-1 bg-outline-variant rounded-full" />
                    <div className="w-1 h-1 bg-outline-variant rounded-full" />
                </div>
            </div>

            <div className="flex-1 overflow-y-auto p-4 space-y-3 custom-scrollbar">
                {agents.map((agent) => (
                    <AgentCard
                        key={agent.id}
                        name={agent.name}
                        role={agent.role || agent.description}
                        avatar={agent.avatar}
                        status={agent.status}
                        isSelected={selectedAgentId === agent.id}
                        onClick={() => onAgentSelect(agent.id)}
                    />
                ))}
                {agents.length === 0 && (
                    <div className="flex flex-col items-center justify-center h-40 text-outline opacity-50">
                        <p className="text-[10px] font-black uppercase tracking-widest">No Active Agents</p>
                    </div>
                )}
            </div>

            <div className="px-6 py-4 uppercase tracking-widest text-[10px]">
                <div className="flex items-center gap-3 px-2">
                    <div className="w-2 h-2 rounded-full bg-success animate-pulse shadow-[0_0_8px_rgba(var(--emerald-500-rgb),0.5)]" />
                    <span className="font-bold text-outline">
                        Synchronized
                    </span>
                </div>
            </div>
        </div>
    );
};
