import React from 'react';
import { AgentStatus } from '../types/agents';
import { CheckCircle2, Circle, Loader2, AlertCircle } from 'lucide-react';

interface AgentCardProps {
    name: string;
    role: string;
    avatar: string;
    status: AgentStatus;
    isSelected: boolean;
    onClick: () => void;
}

export const AgentCard: React.FC<AgentCardProps> = ({
    name,
    role,
    avatar,
    status,
    isSelected,
    onClick,
}) => {
    const getStatusColor = () => {
        switch (status) {
            case 'done': return 'border-emerald-500/50 text-emerald-400';
            case 'running': return 'border-cyan-500/50 text-cyan-400';
            case 'attention': return 'border-amber-500/50 text-amber-400';
            case 'error': return 'border-rose-500/50 text-rose-400';
            default: return 'border-slate-800 text-slate-500';
        }
    };

    const getStatusIcon = () => {
        switch (status) {
            case 'done': return <CheckCircle2 size={16} className="text-emerald-500" />;
            case 'running': return <Loader2 size={16} className="text-cyan-500 animate-spin" />;
            case 'attention': return <AlertCircle size={16} className="text-amber-500" />;
            default: return <Circle size={14} className="text-slate-700" />;
        }
    };

    return (
        <div
            onClick={onClick}
            className={`
        relative flex items-center gap-4 p-4 rounded-xl border-2 transition-all cursor-pointer overflow-hidden
        ${isSelected ? 'bg-slate-900/80 border-cyan-500/30' : 'bg-slate-950/40 border-slate-900 hover:border-slate-800'}
        ${status === 'running' ? 'shadow-[0_0_15px_rgba(34,211,238,0.1)]' : ''}
      `}
        >
            {/* Avatar with status ring */}
            <div className="relative shrink-0">
                <div className={`w-12 h-12 rounded-full overflow-hidden border-2 p-0.5 ${getStatusColor()}`}>
                    <img src={avatar} alt={name} className="w-full h-full rounded-full object-cover grayscale-[0.2]" />
                </div>
                {status === 'done' && (
                    <div className="absolute -bottom-1 -right-1 bg-slate-950 rounded-full p-0.5">
                        <CheckCircle2 size={14} className="text-emerald-500" />
                    </div>
                )}
            </div>

            {/* Content */}
            <div className="flex-1 min-w-0">
                <h4 className={`text-sm font-bold truncate ${isSelected ? 'text-white' : 'text-slate-200'}`}>
                    {name}
                </h4>
                <p className="text-[10px] font-medium text-slate-500 uppercase tracking-tighter truncate">
                    {role}
                </p>
                <p className={`text-[10px] font-bold mt-1 capitalize ${getStatusColor()}`}>
                    {status === 'running' ? 'Processing...' : status}
                </p>
            </div>

            {/* Selection/Status Indicator */}
            <div className="shrink-0 flex items-center justify-center w-6">
                {isSelected ? (
                    <div className="w-1.5 h-6 bg-cyan-500 rounded-full blur-[2px] opacity-80" />
                ) : (
                    getStatusIcon()
                )}
            </div>

            {/* Bottom Progress Bar for Running state */}
            {status === 'running' && (
                <div className="absolute bottom-0 left-0 h-[2px] bg-cyan-500/50 w-full overflow-hidden">
                    <div className="h-full bg-cyan-400 w-1/3 animate-shimmer" />
                </div>
            )}
        </div>
    );
};
