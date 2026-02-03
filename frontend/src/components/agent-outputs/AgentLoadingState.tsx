import React from 'react';
import { Loader2, LucideIcon } from 'lucide-react';

interface AgentLoadingStateProps {
    type: 'full' | 'block' | 'header';
    icon?: LucideIcon;
    title?: string;
    description?: string;
    status?: string;
    className?: string;
    colorClass?: string;
}

export const AgentLoadingState: React.FC<AgentLoadingStateProps> = ({
    type,
    icon: Icon,
    title,
    description,
    status,
    className = "",
    colorClass = "text-indigo-400"
}) => {
    if (type === 'header') {
        return (
            <div className={`flex items-center gap-2 text-[10px] ${colorClass} font-bold uppercase tracking-widest animate-pulse ${className}`}>
                <Loader2 size={12} className="animate-spin" />
                <span>{title || 'Loading...'}</span>
            </div>
        );
    }

    if (type === 'block') {
        return (
            <div className={`p-8 border border-slate-800 rounded-xl bg-slate-900/30 text-center ${className}`}>
                <div className="flex flex-col items-center justify-center gap-3">
                    <Loader2 size={20} className={`${colorClass} animate-spin opacity-50`} />
                    <p className="text-slate-500 text-xs italic">
                        {title || description || "Loading content..."}
                    </p>
                </div>
            </div>
        );
    }

    // Default: 'full'
    return (
        <div className={`flex-1 flex flex-col items-center justify-center p-12 text-center h-full min-h-[300px] animate-in fade-in duration-500 ${className}`}>
            {Icon && (
                <Icon size={48} className={`${colorClass.replace('text-', 'text-slate-900 ')} mb-4 animate-pulse opacity-50`} />
            )}
            {!Icon && (
                <div className="w-12 h-12 rounded-xl bg-slate-900/50 border border-slate-800 flex items-center justify-center mb-4">
                    <Loader2 size={24} className={`${colorClass} animate-spin`} />
                </div>
            )}

            <h4 className="text-slate-500 font-bold text-xs uppercase tracking-widest">
                {title || 'Processing...'}
            </h4>

            {description && (
                <p className="text-slate-700 text-[10px] mt-2 max-w-[240px]">
                    {description}
                </p>
            )}

            {status && (
                <p className="text-[10px] text-slate-500 mt-2 font-mono opacity-60">
                    Status: {status}
                </p>
            )}
        </div>
    );
};
