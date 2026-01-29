import React, { memo } from 'react';
import { FileText, Clock, Loader2, Database } from 'lucide-react';
import { AgentStatus, StandardAgentOutput } from '@/types/agents';
import { useArtifact } from '../../hooks/useArtifact';

interface GenericAgentOutputProps {
    agentName: string;
    output: StandardAgentOutput | null;
    status: AgentStatus;
}

const GenericAgentOutputComponent: React.FC<GenericAgentOutputProps> = ({
    agentName,
    output,
    status
}) => {
    // 1. Determine if we have a reference to fetch
    const reference = (output as StandardAgentOutput)?.reference;
    const preview = (output as StandardAgentOutput)?.preview;

    // 2. Fetch artifact if reference exists
    const { data: artifactData, isLoading: isArtifactLoading } = useArtifact<any>(
        reference?.artifact_id
    );

    // 3. Resolve actual data (Artifact > Preview)
    const effectiveData = artifactData || preview;

    if ((status !== 'done' && !effectiveData) || !output) {
        return (
            <div className="flex-1 flex flex-col items-center justify-center p-12 text-center h-full min-h-[300px]">
                <Clock size={48} className="text-slate-900 mb-4 animate-pulse opacity-50" />
                <h4 className="text-slate-500 font-bold text-xs uppercase tracking-widest">Processing...</h4>
                <p className="text-slate-700 text-[10px] mt-2 max-w-[240px]">
                    {agentName} is currently working on its task.
                </p>
                <p className="text-[10px] text-slate-500 mt-2">Status: {status}</p>
            </div>
        );
    }

    const isReferenceLoading = reference && isArtifactLoading && !artifactData;

    return (
        <div className="space-y-6">
            <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-3">
                    <FileText size={18} className="text-indigo-400" />
                    <h3 className="text-sm font-bold text-white uppercase tracking-widest">{agentName} Result</h3>
                </div>
                {isReferenceLoading && (
                    <div className="flex items-center gap-2 text-[10px] text-indigo-400 font-bold uppercase tracking-widest animate-pulse">
                        <Loader2 size={12} className="animate-spin" />
                        <span>Loading Artifact...</span>
                    </div>
                )}
            </div>

            <div className="bg-slate-900/40 border border-slate-800 rounded-2xl p-6 font-mono text-xs overflow-auto max-h-[600px] text-slate-300 relative group">
                <div className="absolute top-4 right-4 opacity-20 group-hover:opacity-100 transition-opacity">
                    <Database size={14} className="text-slate-500" />
                </div>
                {effectiveData ? (
                    <pre className="whitespace-pre-wrap word-break-all">
                        {JSON.stringify(effectiveData, null, 2)}
                    </pre>
                ) : (
                    <div className="flex flex-col items-center justify-center py-12 text-slate-600 italic">
                        <p>Empty result payload.</p>
                    </div>
                )}
            </div>

            {preview && !artifactData && reference && (
                <div className="mt-4 p-3 bg-indigo-500/10 border border-indigo-500/20 rounded-xl flex items-center gap-3">
                    <div className="animate-spin">
                        <Loader2 size={14} className="text-indigo-400" />
                    </div>
                    <p className="text-[10px] text-indigo-300 font-medium italic">
                        Showing lightweight preview. Full artifact data is being retrieved from the secure vault...
                    </p>
                </div>
            )}
        </div>
    );
};

export const GenericAgentOutput = memo(GenericAgentOutputComponent);
