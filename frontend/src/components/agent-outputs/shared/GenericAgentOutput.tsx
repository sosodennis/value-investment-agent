import React, { memo } from 'react';
import { FileText, Clock, Database, AlertCircle, ChevronDown, Loader2 } from 'lucide-react';
import { AgentStatus } from '@/types/agents';
import { GenericOutputViewModel } from '@/types/agents/output-adapter';
import { parseUnknownArtifact } from '@/types/agents/artifact-parsers';
import { UnknownRecord } from '@/types/preview';
import { useArtifact } from '../../../hooks/useArtifact';
import { AgentLoadingState } from './AgentLoadingState';

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

    const fallbackPayload: UnknownRecord = {};
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
            <AgentLoadingState
                type="full"
                icon={Clock}
                title="Processing…"
                description={`${agentName} is currently working on its task.`}
                status={status}
                colorClass="text-primary"
            />
        );
    }

    const isReferenceLoading = reference && isArtifactLoading && !artifactData;

    return (
        <div className="space-y-6">
            <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-3">
                    <FileText size={18} className="text-primary" />
                    <h3 className="text-sm font-bold text-on-surface uppercase tracking-widest">{agentName} Result</h3>
                </div>
                {isReferenceLoading && (
                    <AgentLoadingState
                        type="header"
                        title="Loading Artifact…"
                        colorClass="text-primary"
                    />
                )}
            </div>

            <div className="bg-surface border border-outline-variant/30 rounded-2xl p-6 font-mono text-xs overflow-auto max-h-[600px] text-on-surface-variant relative group">
                <div className="absolute top-4 right-4 opacity-20 group-hover:opacity-100 transition-opacity">
                    <Database size={14} className="text-outline" />
                </div>
                {effectiveData ? (
                    <pre className="whitespace-pre-wrap word-break-all">
                        {JSON.stringify(effectiveData, null, 2)}
                    </pre>
                ) : (
                    <div className="flex flex-col items-center justify-center py-12 text-outline italic">
                        <p>Empty Result Payload</p>
                    </div>
                )}
            </div>

            {preview && !artifactData && reference && (
                <div className="mt-4 p-3 bg-primary/10 border border-primary/20 rounded-xl flex items-center gap-3">
                    <div className="animate-spin">
                        <Loader2 size={14} className="text-primary" />
                    </div>
                    <p className="text-[10px] text-primary/80 font-medium italic">
                        Showing lightweight preview. Full artifact data is being retrieved from the secure vault…
                    </p>
                </div>
            )}

            {errorLogs.length > 0 && (
                <div className="mt-6 border border-outline-variant/30 rounded-xl overflow-hidden bg-surface">
                    <button
                        onClick={() => setIsLogsExpanded(!isLogsExpanded)}
                        className="w-full flex items-center justify-between p-4 hover:bg-surface-container-high transition-colors"
                    >
                        <div className="flex items-center gap-2">
                            <AlertCircle size={14} className={status === 'error' ? 'text-error' : 'text-warning'} />
                            <span className="text-[10px] font-bold text-on-surface uppercase tracking-widest">
                                System Logs ({errorLogs.length})
                            </span>
                        </div>
                        <ChevronDown
                            size={14}
                            className={`text-outline expandable-chevron ${isLogsExpanded ? 'rotate-180' : ''}`}
                        />
                    </button>

                    <div
                        className={`expandable-panel ${
                            isLogsExpanded ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0'
                        }`}
                    >
                        <div className="overflow-hidden">
                            <div className="border-t border-outline-variant/30 p-1 space-y-1">
                                {errorLogs.map((log, idx: number) => (
                                    <div key={idx} className="p-3 bg-surface-container-low rounded-lg flex gap-3">
                                        <div className="mt-0.5">
                                            <div className={`w-1.5 h-1.5 rounded-full mt-1 ${log.severity === 'error' ? 'bg-error' : 'bg-warning'}`} />
                                        </div>
                                        <div className="flex-1 min-w-0">
                                            <div className="flex items-center justify-between mb-1">
                                                <span className="text-[9px] font-bold text-on-surface-variant uppercase tracking-tight">Node: {log.node}</span>
                                                {log.timestamp && <span className="text-[8px] text-outline font-mono">{log.timestamp}</span>}
                                            </div>
                                            <p className="text-[10px] text-on-surface-variant leading-relaxed break-words">{log.error}</p>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export const GenericAgentOutput = memo(GenericAgentOutputComponent);
