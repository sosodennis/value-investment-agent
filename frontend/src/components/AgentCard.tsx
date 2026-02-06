import React from 'react';
import { AgentStatus } from '@/types/agents';
import { CheckCircle2 } from 'lucide-react';

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
    const getStatusStyles = () => {
        switch (status) {
            case 'done': return {
                border: 'border-success/50',
                text: 'text-success',
                bg: 'bg-success/5'
            };
            case 'running': return {
                border: 'border-primary/50',
                text: 'text-primary',
                bg: 'bg-primary/5'
            };
            case 'attention': return {
                border: 'border-warning/50',
                text: 'text-warning',
                bg: 'bg-warning/5'
            };
            case 'error': return {
                border: 'border-error/50',
                text: 'text-error',
                bg: 'bg-error/5'
            };
            case 'degraded': return {
                border: 'border-warning/50',
                text: 'text-warning',
                bg: 'bg-warning/5'
            };
            default: return {
                border: 'border-border-main',
                text: 'text-slate-500',
                bg: 'bg-transparent'
            };
        }
    };

    const styles = getStatusStyles();

    return (
        <div
            onClick={onClick}
            className={`
        relative flex items-center gap-4 p-4 rounded-xl border transition-all cursor-pointer overflow-hidden
        ${isSelected ? 'bg-slate-900/80 border-primary/30' : 'bg-bg-main/40 border-border-main hover:border-border-subtle'}
        ${status === 'running' ? 'shadow-[0_0_15px_rgba(var(--primary-rgb),0.1)]' : ''}
      `}
        >
            {/* Avatar with status ring */}
            <div className="relative shrink-0">
                <div className={`w-12 h-12 rounded-full overflow-hidden border p-0.5 ${styles.border}`}>
                    <img
                        src={avatar}
                        alt={name}
                        width={48}
                        height={48}
                        className="w-full h-full rounded-full object-cover grayscale-[0.2]"
                    />
                </div>
                {status === 'done' && (
                    <div className="absolute -bottom-1 -right-1 bg-bg-main rounded-full p-0.5">
                        <CheckCircle2 size={14} className="text-success" />
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
                <p className={`text-[10px] font-bold mt-1 capitalize ${styles.text}`}>
                    {status === 'running' ? 'Processing...' :
                        status === 'attention' ? 'Human Assist' :
                            status === 'degraded' ? 'Degraded Performance' :
                                status}
                </p>
            </div>

            {/* SelectionIndicator */}
            <div className="shrink-0 flex items-center justify-center w-6">
                <div className={`
                    w-4 h-4 rounded-full border flex items-center justify-center transition-all
                    ${isSelected ? 'border-primary bg-primary/10' : 'border-slate-800 bg-transparent'}
                `}>
                    {isSelected && (
                        <div className="w-1.5 h-1.5 bg-primary rounded-full shadow-[0_0_8px_rgba(var(--primary-rgb),0.8)]" />
                    )}
                </div>
            </div>

            {/* Bottom Progress Bar for Running state */}
            {status === 'running' && (
                <div className="absolute bottom-0 left-0 h-[1px] bg-primary/30 w-full overflow-hidden">
                    <div className="h-full bg-primary w-1/3 animate-shimmer" />
                </div>
            )}
        </div>
    );
};
