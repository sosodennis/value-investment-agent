import React from 'react';
import { FileText, Clock } from 'lucide-react';

import { AgentStatus } from '@/types/agents';

interface GenericAgentOutputProps {
    agentName: string;
    output: any | null;
    status: AgentStatus;
}

export const GenericAgentOutput: React.FC<GenericAgentOutputProps> = ({
    agentName,
    output,
    status
}) => {
    if (status !== 'done' || !output) {
        return (
            <div className="flex-1 flex flex-col items-center justify-center p-12 text-center h-full">
                <Clock size={48} className="text-slate-900 mb-4 animate-pulse opacity-50" />
                <h4 className="text-slate-500 font-bold text-xs uppercase tracking-widest">Processing...</h4>
                <p className="text-slate-700 text-[10px] mt-2 max-w-[240px]">
                    This agent is currently working on its task.
                </p>
                <p className="text-[10px] text-slate-500 mt-2">Status: {status}</p>
            </div>
        );
    }

    return (
        <div className="space-y-6">
            <div className="flex items-center gap-3 mb-2">
                <FileText size={18} className="text-indigo-400" />
                <h3 className="text-sm font-bold text-white uppercase tracking-widest">{agentName} Result</h3>
            </div>
            <div className="bg-slate-900/40 border border-slate-800 rounded-2xl p-6 font-mono text-xs overflow-auto max-h-[600px] text-slate-300">
                <pre>{JSON.stringify(output, null, 2)}</pre>
            </div>
        </div>
    );
};
