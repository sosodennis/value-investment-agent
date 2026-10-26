import React, { memo } from 'react';
import { AlertCircle, ChevronDown, Database, FileText } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';
import type { AgentStatus } from '@/types/agents';
import type { GenericOutputViewModel } from '@/types/agents/output-adapter';
import { parseUnknownArtifact } from '@/types/agents/artifact-parsers';
import type { UnknownRecord } from '@/types/preview';
import { useArtifact } from '../../../../hooks/useArtifact';
import { AgentLoadingState } from './AgentLoadingState';
import { ArtifactLoadError } from './ArtifactLoadError';

interface GenericAgentOutputProps {
    agentName: string;
    viewModel: GenericOutputViewModel;
    status: AgentStatus;
}

const GenericAgentOutputComponent: React.FC<GenericAgentOutputProps> = ({
    agentName,
    viewModel,
    status,
}) => {
    const reference = viewModel.reference;
    const preview = viewModel.preview;
    const errorLogs = viewModel.errorLogs;
    const [isLogsExpanded, setIsLogsExpanded] = React.useState(false);
    const {
        data: artifactData,
        isLoading: isArtifactLoading,
        error: artifactError,
        retry,
        isRetrying,
        retryable,
    } = useArtifact(reference?.artifact_id, parseUnknownArtifact, 'generic_output.artifact');

    const fallbackPayload: UnknownRecord = {};
    if (viewModel.summary !== null) fallbackPayload.summary = viewModel.summary;
    if (preview !== null) fallbackPayload.preview = preview;
    if (reference !== null) fallbackPayload.reference = reference;
    if (errorLogs.length > 0) fallbackPayload.error_logs = errorLogs;

    const hasFallbackPayload = Object.keys(fallbackPayload).length > 0;
    const effectiveData = artifactData ?? (hasFallbackPayload ? fallbackPayload : null);

    if (status !== 'done' && status !== 'error' && !effectiveData) {
        return (
            <AgentLoadingState
                type="full"
                icon={FileText}
                title="Processing…"
                description={`${agentName} is currently working on its task.`}
                status={status}
            />
        );
    }

    const isReferenceLoading = reference !== null && isArtifactLoading && artifactData === undefined;
    const artifactErrorMessage = artifactError instanceof Error
        ? artifactError.message
        : artifactError
            ? 'The full report could not be loaded.'
            : null;

    return (
        <div className="grid gap-4">
            <Card>
                <CardHeader className="flex-row items-center justify-between gap-3">
                    <CardTitle className="flex items-center gap-2 text-base">
                        <FileText aria-hidden="true" className="size-4 text-primary" />
                        {agentName} result
                    </CardTitle>
                    <div className="flex items-center gap-2">
                        {reference ? <Badge variant="outline">Artifact {reference.artifact_id}</Badge> : null}
                        {isReferenceLoading ? <AgentLoadingState type="header" title="Loading full report…" /> : null}
                    </div>
                </CardHeader>
                <CardContent className="grid gap-3">
                    {artifactErrorMessage ? (
                        <ArtifactLoadError
                            title="Full report unavailable"
                            error={artifactErrorMessage}
                            retry={retry}
                            isRetrying={isRetrying}
                            retryable={retryable}
                        />
                    ) : null}
                    {effectiveData ? (
                        <pre className="max-h-[600px] overflow-auto rounded-md bg-muted/50 p-4 font-mono text-xs leading-5 text-foreground">
                            {JSON.stringify(effectiveData, null, 2)}
                        </pre>
                    ) : (
                        <EmptyState
                            className="min-h-32 rounded-md bg-muted/40 px-4"
                            icon={<Database aria-hidden="true" />}
                            title={status === 'error' ? 'No result was produced' : 'No result data'}
                            description={status === 'error' ? 'The agent finished with an error before producing output.' : 'The completed agent run did not include a report payload.'}
                        />
                    )}
                    {preview && !artifactData && reference ? (
                        <p className="text-sm text-muted-foreground" role="status">
                            Showing the available preview while the full report loads.
                        </p>
                    ) : null}
                </CardContent>
            </Card>

            {errorLogs.length > 0 ? (
                <Card>
                    <div className="flex items-center justify-between gap-3 p-4">
                        <div className="flex items-center gap-2 text-sm font-medium">
                            <AlertCircle aria-hidden="true" className={status === 'error' ? 'size-4 text-destructive' : 'size-4 text-warning'} />
                            System logs <Badge variant={status === 'error' ? 'destructive' : 'outline'}>{errorLogs.length}</Badge>
                        </div>
                        <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            aria-expanded={isLogsExpanded}
                            onClick={() => setIsLogsExpanded((expanded) => !expanded)}
                        >
                            {isLogsExpanded ? 'Hide' : 'Show'}
                            <ChevronDown aria-hidden="true" className={`size-4 transition-transform ${isLogsExpanded ? 'rotate-180' : ''}`} />
                        </Button>
                    </div>
                    {isLogsExpanded ? (
                        <CardContent className="grid gap-2 border-t border-border/40 pt-4">
                            {errorLogs.map((log, index) => (
                                <div key={`${log.node}-${log.timestamp ?? index}`} className="grid gap-1 rounded-md bg-muted/50 p-3 text-sm">
                                    <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
                                        <span>Node: {log.node}</span>
                                        {log.timestamp ? <time>{log.timestamp}</time> : null}
                                    </div>
                                    <p className="break-words text-foreground">{log.error}</p>
                                </div>
                            ))}
                        </CardContent>
                    ) : null}
                </Card>
            ) : null}
        </div>
    );
};

export const GenericAgentOutput = memo(GenericAgentOutputComponent);
