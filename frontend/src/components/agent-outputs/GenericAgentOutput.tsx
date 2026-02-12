import React, { memo } from 'react';
import { FileText, Clock, Loader2, Database, AlertCircle, ChevronDown, ChevronUp } from 'lucide-react';
import { AgentStatus } from '@/types/agents';
import { GenericOutputViewModel } from '@/types/agents/output-adapter';
import { parseUnknownArtifact } from '@/types/agents/artifact-parsers';
import { useArtifact } from '../../hooks/useArtifact';

interface GenericAgentOutputProps {
    agentName: string;
    viewModel: GenericOutputViewModel;
    status: AgentStatus;
}

const GenericAgentOutputComponent: React.FC<GenericAgentOutputProps> = ({
    agentName,
    viewModel,
    status
}) => {
    const reference = viewModel.reference;
    const preview = viewModel.preview;
    const errorLogs = viewModel.errorLogs;

    const [isLogsExpanded, setIsLogsExpanded] = React.useState(false);

    const { data: artifactData, isLoading: isArtifactLoading } = useArtifact(
        reference?.artifact_id,
        parseUnknownArtifact,
        'generic_output.artifact'
    );

    const fallbackPayload: Record<string, unknown> = {};
    if (viewModel.summary !== null) {
        fallbackPayload.summary = viewModel.summary;
    }
    if (preview !== null) {
        fallbackPayload.preview = preview;
    }
    if (reference !== null) {
        fallbackPayload.reference = reference;
    }
    if (errorLogs.length > 0) {
        fallbackPayload.error_logs = errorLogs;
    }

    const hasFallbackPayload = Object.keys(fallbackPayload).length > 0;
    const effectiveData = artifactData || (hasFallbackPayload ? fallbackPayload : null);

    if (status !== 'done' && !effectiveData) {
        return (
            <div className="flex-1 flex flex-col items-center justify-center p-12 text-center h-full min-h-[300px]">
                <Clock size={48} className="text-slate-900 mb-4 animate-pulse opacity-50" />
                <h4 className="text-label">Processing...</h4>
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
                    <FileText size={18} className="text-primary" />
                    <h3 className="text-sm font-bold text-white uppercase tracking-widest">{agentName} Result</h3>
                </div>
                {isReferenceLoading && (
                    <div className="flex items-center gap-2 text-[10px] text-primary font-bold uppercase tracking-widest animate-pulse">
                        <Loader2 size={12} className="animate-spin" />
                        <span>Loading Artifact...</span>
                    </div>
                )}
            </div>

            <div className="bg-bg-main/40 border border-border-main rounded-2xl p-6 font-mono text-xs overflow-auto max-h-[600px] text-slate-300 relative group">
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
                <div className="mt-4 p-3 bg-primary/10 border border-primary/20 rounded-xl flex items-center gap-3">
                    <div className="animate-spin">
                        <Loader2 size={14} className="text-primary" />
                    </div>
                    <p className="text-[10px] text-primary/80 font-medium italic">
                        Showing lightweight preview. Full artifact data is being retrieved from the secure vault...
                    </p>
                </div>
            )}

            {errorLogs.length > 0 && (
                <div className="mt-6 border border-border-main/50 rounded-xl overflow-hidden bg-bg-main/20">
                    <button
                        onClick={() => setIsLogsExpanded(!isLogsExpanded)}
                        className="w-full flex items-center justify-between p-4 hover:bg-slate-800/30 transition-colors"
                    >
                        <div className="flex items-center gap-2">
                            <AlertCircle size={14} className={status === 'error' ? 'text-error' : 'text-warning'} />
                            <span className="text-[10px] font-bold text-white uppercase tracking-widest">
                                System Logs ({errorLogs.length})
                            </span>
                        </div>
                        {isLogsExpanded ? <ChevronUp size={14} className="text-slate-500" /> : <ChevronDown size={14} className="text-slate-500" />}
                    </button>

                    {isLogsExpanded && (
                        <div className="border-t border-border-main/50 p-1 space-y-1">
                            {errorLogs.map((log, idx: number) => (
                                <div key={idx} className="p-3 bg-slate-900/40 rounded-lg flex gap-3">
                                    <div className="mt-0.5">
                                        <div className={`w-1.5 h-1.5 rounded-full mt-1 ${log.severity === 'error' ? 'bg-error' : 'bg-warning'}`} />
                                    </div>
                                    <div className="flex-1 min-w-0">
                                        <div className="flex items-center justify-between mb-1">
                                            <span className="text-[9px] font-bold text-slate-400 uppercase tracking-tight">Node: {log.node}</span>
                                            {log.timestamp && <span className="text-[8px] text-slate-600 font-mono">{log.timestamp}</span>}
                                        </div>
                                        <p className="text-[10px] text-slate-300 leading-relaxed break-words">{log.error}</p>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
};

export const GenericAgentOutput = memo(GenericAgentOutputComponent);
