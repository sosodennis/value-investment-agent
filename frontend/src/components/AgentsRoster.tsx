import React from 'react';
import { AgentInfo } from '../types/agents';
import { AgentCard } from './AgentCard';

interface AgentsRosterProps {
    agents: AgentInfo[];
    selectedAgentId: string | null;
    onAgentSelect: (agentId: string) => void;
}

export const AgentsRoster: React.FC<AgentsRosterProps> = ({
    agents,
    selectedAgentId,
    onAgentSelect,
}) => {
    return (
        <aside className="w-80 h-full flex flex-col border-r border-slate-900 bg-slate-950/20 backdrop-blur-sm overflow-hidden shrink-0">
            <div className="p-6 border-b border-slate-900 flex items-center justify-between">
                <h3 className="text-xs font-bold text-slate-500 uppercase tracking-[0.2em]">
                    Agents Roster
                </h3>
                <div className="flex gap-1">
                    <div className="w-1 h-1 bg-slate-800 rounded-full" />
                    <div className="w-1 h-1 bg-slate-800 rounded-full" />
                    <div className="w-1 h-1 bg-slate-800 rounded-full" />
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
                    <div className="flex flex-col items-center justify-center h-40 text-slate-700 opacity-50">
                        <p className="text-[10px] font-bold uppercase tracking-widest">No Active Agents</p>
                    </div>
                )}
            </div>

            <div className="p-4 border-t border-slate-900 bg-slate-950/40">
                <div className="flex items-center gap-3 px-2">
                    <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse shadow-[0_0_8px_rgba(16,185,129,0.5)]" />
                    <span className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">
                        Synchronized
                    </span>
                </div>
            </div>
        </aside>
    );
};
