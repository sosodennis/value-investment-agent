import { useCallback, useEffect, useRef, useState } from 'react';
import { clientLogger } from '@/lib/logger';
import type { AgentStatus, StandardAgentOutput } from '@/types/agents';
import { buildArtifactUrl } from '@/features/artifacts/api';
import { applyWorkflowEvent, boundedReconnectDelay, cancelWorkflowRun, consumeWorkflowEvents, createWorkflowActivityState, getActivitySnapshot, resumeWorkflowRun, retryWorkflowRun, startWorkflowRun, type InteractionId, type InteractionResponse, type WorkflowActivitySnapshot, type WorkflowInteraction } from '@/features/workflow';
import { useAgentReducer } from './useAgentReducer';

const makeThreadId = () => `thread_${crypto.randomUUID()}`;
const toError = (value: unknown, fallback: string) => value instanceof Error ? value.message : fallback;
const isAbortError = (value: unknown) => {
    if (typeof value !== 'object' || value === null) return false;
    const hasAbortName = 'name' in value && value.name === 'AbortError';
    const hasAbortMessage = 'message' in value && value.message === 'signal is aborted without reason';
    return hasAbortName || hasAbortMessage;
};
const STANDARD_OUTPUT_KINDS: readonly StandardAgentOutput['kind'][] = [
    'intent_extraction.output',
    'fundamental_analysis.output',
    'financial_news_research.output',
    'technical_analysis.output',
    'debate.output',
];

const isStandardOutputKind = (value: string): value is StandardAgentOutput['kind'] =>
    STANDARD_OUTPUT_KINDS.some((kind) => kind === value);

const isPreviewRecord = (value: unknown): value is Record<string, unknown> =>
    typeof value === 'object' && value !== null && !Array.isArray(value);

const hasDegradedPreview = (output: StandardAgentOutput): boolean => {
    const preview = output.preview;
    if (!isPreviewRecord(preview)) return false;
    const status = preview.status;
    return status === 'degraded' || status === 'abstained';
};

export function useAgent(assistantId = 'agent') {
    void assistantId;
    const { state, initSession, setRun, hydrateWorkflow, processWorkflowEvent, setConnection, addUserMessage, setError, reset } = useAgentReducer();
    const [isLoading, setIsLoading] = useState(false);
    const [submittingInteractionId, setSubmittingInteractionId] = useState<InteractionId | null>(null);
    const [hasMore] = useState(false);
    const operationRef = useRef<AbortController | null>(null);
    const submittingInteractionRef = useRef<InteractionId | null>(null);

    useEffect(() => () => {
        operationRef.current?.abort();
        operationRef.current = null;
    }, []);

    const beginOperation = useCallback(() => {
        operationRef.current?.abort();
        const operation = new AbortController();
        operationRef.current = operation;
        submittingInteractionRef.current = null;
        setSubmittingInteractionId(null);
        setConnection('disconnected');
        return operation;
    }, [setConnection]);

    const isCurrentOperation = useCallback((operation: AbortController) =>
        operationRef.current === operation && !operation.signal.aborted, []);

    const attachStream = useCallback(async (threadId: string, initialSnapshot: WorkflowActivitySnapshot, operation: AbortController, expectedRunId: string = initialSnapshot.run_id) => {
        if (!isCurrentOperation(operation)) return;
        if (initialSnapshot.run_id !== expectedRunId) throw new TypeError('activity snapshot run identity mismatch.');
        let attempt = 0;
        let snapshot = initialSnapshot;
        let cursor = snapshot.cursor;
        let projection = createWorkflowActivityState(snapshot);
        while (isCurrentOperation(operation) && attempt < 5) {
            try {
                setConnection(attempt === 0 ? 'connecting' : 'reconnecting');
                await consumeWorkflowEvents(threadId, cursor, operation.signal, (event) => {
                    if (!isCurrentOperation(operation)) return true;
                    if (event.run_id !== expectedRunId || event.thread_id !== threadId) throw new TypeError('workflow event identity mismatch.');
                    const next = applyWorkflowEvent(projection, event);
                    if (next.gapDetected) throw new Error('workflow sequence gap requires snapshot recovery.');
                    projection = next;
                    cursor = next.cursor;
                    processWorkflowEvent(event);
                    return event.event_name === 'workflow.activity'
                        && event.payload.activity_id === 'workflow'
                        && ['completed', 'failed', 'cancelled'].includes(event.payload.status);
                }, expectedRunId, () => {
                    if (isCurrentOperation(operation)) setConnection('connected');
                });
                if (!isCurrentOperation(operation)) return;
                snapshot = await getActivitySnapshot(threadId, { runId: expectedRunId, signal: operation.signal });
                if (!isCurrentOperation(operation)) return;
                if (snapshot.run_id !== expectedRunId) throw new TypeError('activity snapshot run identity mismatch.');
                hydrateWorkflow(snapshot);
                if (['completed', 'failed', 'cancelled'].includes(snapshot.run_status)) { setConnection('closed'); return; }
                cursor = snapshot.cursor;
                projection = createWorkflowActivityState(snapshot);
            } catch (error) {
                if (!isCurrentOperation(operation)) return;
                if (isAbortError(error)) { setConnection('disconnected'); return; }
                clientLogger.error('workflow.stream.error', { threadId, attempt, error: toError(error, 'stream failed') });
                snapshot = await getActivitySnapshot(threadId, { runId: expectedRunId, signal: operation.signal });
                if (!isCurrentOperation(operation)) return;
                if (snapshot.run_id !== expectedRunId) throw new TypeError('activity snapshot run identity mismatch.');
                hydrateWorkflow(snapshot);
                if (['completed', 'failed', 'cancelled'].includes(snapshot.run_status)) { setConnection('closed'); return; }
                cursor = snapshot.cursor;
                projection = createWorkflowActivityState(snapshot);
            }
            attempt += 1;
            if (attempt < 5) await new Promise((resolve) => setTimeout(resolve, boundedReconnectDelay(attempt)));
        }
        if (isCurrentOperation(operation)) setConnection('closed');
    }, [hydrateWorkflow, isCurrentOperation, processWorkflowEvent, setConnection]);

    const sendMessage = useCallback(async (
        content: string,
        newSession = false,
        valuationRequest?: Record<string, unknown>,
    ) => {
        const operation = beginOperation();
        setIsLoading(true);
        const threadId = newSession || !state.threadId ? makeThreadId() : state.threadId;
        if (threadId !== state.threadId) initSession(threadId);
        addUserMessage({ id: `user_${Date.now()}`, role: 'user', content, type: 'text' });
        try {
            const run = await startWorkflowRun(threadId, {
                message: content,
                valuation_request: valuationRequest,
            }, { signal: operation.signal });
            if (!isCurrentOperation(operation)) return;
            setRun(run.run_id);
            const snapshot = await getActivitySnapshot(threadId, { runId: run.run_id, signal: operation.signal });
            if (!isCurrentOperation(operation)) return;
            if (snapshot.run_id !== run.run_id) throw new TypeError('activity snapshot run identity mismatch.');
            hydrateWorkflow(snapshot);
            setIsLoading(false);
            await attachStream(threadId, snapshot, operation, run.run_id);
        } catch (error) {
            if (isCurrentOperation(operation) && !isAbortError(error)) setError(toError(error, 'Failed to start workflow run.'));
        } finally { if (isCurrentOperation(operation)) setIsLoading(false); }
    }, [addUserMessage, attachStream, beginOperation, hydrateWorkflow, initSession, isCurrentOperation, setError, setRun, state.threadId]);

    const submitCommand = useCallback(async (interaction: WorkflowInteraction, response: InteractionResponse) => {
        const currentInteraction = state.workflow?.interactions.get(interaction.identity.interaction_id);
        if (
            !state.threadId
            || !state.runId
            || !currentInteraction
            || currentInteraction.status !== 'pending'
            || currentInteraction.identity.thread_id !== state.threadId
            || currentInteraction.identity.run_id !== state.runId
        ) {
            setError('The workflow interaction is no longer available.');
            return;
        }
        const interactionId = currentInteraction.identity.interaction_id;
        if (submittingInteractionRef.current === interactionId) return;
        const operation = beginOperation();
        submittingInteractionRef.current = interactionId;
        setSubmittingInteractionId(interactionId);
        const text = `Selected ${response.selected_symbol}`;
        addUserMessage({ id: `user_${Date.now()}`, role: 'user', content: text, type: 'text' });
        try {
            const run = await resumeWorkflowRun(state.threadId, state.runId, {
                identity: currentInteraction.identity,
                response,
            }, { signal: operation.signal });
            if (!isCurrentOperation(operation)) return;
            setRun(run.run_id);
            const snapshot = await getActivitySnapshot(state.threadId, { runId: run.run_id, signal: operation.signal });
            if (!isCurrentOperation(operation)) return;
            hydrateWorkflow(snapshot);
            setIsLoading(false);
            await attachStream(state.threadId, snapshot, operation, run.run_id);
        } catch (error) {
            if (isCurrentOperation(operation) && !isAbortError(error)) setError(toError(error, 'Failed to resume workflow run.'));
        } finally {
            if (isCurrentOperation(operation) && submittingInteractionRef.current === interactionId) {
                submittingInteractionRef.current = null;
                setSubmittingInteractionId(null);
            }
            if (isCurrentOperation(operation)) setIsLoading(false);
        }
    }, [addUserMessage, attachStream, beginOperation, hydrateWorkflow, isCurrentOperation, setError, setRun, state.runId, state.threadId, state.workflow]);

    const retryRun = useCallback(async () => {
        const failure = state.workflow?.failure;
        if (!state.threadId || !state.runId || !failure?.retryable || !failure.checkpoint) {
            setError('This workflow failure cannot be retried.');
            return;
        }
        const operation = beginOperation();
        setIsLoading(true);
        try {
            const retry = await retryWorkflowRun(
                state.threadId,
                state.runId,
                failure.checkpoint,
                crypto.randomUUID(),
                { signal: operation.signal },
            );
            if (!isCurrentOperation(operation)) return;
            setRun(retry.run_id);
            const snapshot = await getActivitySnapshot(state.threadId, { runId: retry.run_id, signal: operation.signal });
            if (!isCurrentOperation(operation)) return;
            hydrateWorkflow(snapshot);
            await attachStream(state.threadId, snapshot, operation, retry.run_id);
        } catch (error) {
            if (isCurrentOperation(operation) && !isAbortError(error)) setError(toError(error, 'Failed to retry workflow run.'));
        } finally {
            if (isCurrentOperation(operation)) setIsLoading(false);
        }
    }, [attachStream, beginOperation, hydrateWorkflow, isCurrentOperation, setError, setRun, state.runId, state.threadId, state.workflow]);

    const loadHistory = useCallback(async (threadId: string, expectedRunId: string) => {
        const operation = beginOperation();
        reset();
        setIsLoading(true);
        try {
            const snapshot = await getActivitySnapshot(threadId, { runId: expectedRunId, signal: operation.signal });
            if (!isCurrentOperation(operation)) return;
            hydrateWorkflow(snapshot);
            setIsLoading(false);
            if (snapshot.run_status === 'running' || snapshot.run_status === 'waiting' || snapshot.run_status === 'queued') await attachStream(threadId, snapshot, operation, snapshot.run_id);
        } catch (error) {
            if (isCurrentOperation(operation) && !isAbortError(error)) setError(toError(error, 'Failed to load workflow snapshot.'));
        } finally { if (isCurrentOperation(operation)) setIsLoading(false); }
    }, [attachStream, beginOperation, hydrateWorkflow, isCurrentOperation, reset, setError]);

    const cancelRun = useCallback(async () => {
        if (!state.threadId || !state.runId) return;
        const operation = beginOperation();
        try {
            await cancelWorkflowRun(state.threadId, state.runId, { signal: operation.signal });
            if (!isCurrentOperation(operation)) return;
            const snapshot = await getActivitySnapshot(state.threadId, { runId: state.runId, signal: operation.signal });
            if (!isCurrentOperation(operation)) return;
            hydrateWorkflow(snapshot);
            setConnection('closed');
        } catch (error) {
            if (isCurrentOperation(operation) && !isAbortError(error)) setError(toError(error, 'Failed to cancel workflow run.'));
        } finally { if (isCurrentOperation(operation)) setIsLoading(false); }
    }, [beginOperation, hydrateWorkflow, isCurrentOperation, setConnection, setError, state.runId, state.threadId]);

    const activeActivities = state.workflow ? [...state.workflow.active.values()] : [];
    const isSubmittingInteraction = submittingInteractionId !== null
        && state.workflow?.interactions.get(submittingInteractionId)?.status === 'pending';
    const agentStatuses: Record<string, AgentStatus> = {};
    for (const activity of activeActivities) {
        const id = activity.scope_path[0] ?? activity.activity_id;
        agentStatuses[id] = activity.status === 'waiting' ? 'attention' : activity.status === 'running' ? 'running' : activity.status === 'completed' ? 'done' : activity.status === 'failed' || activity.status === 'cancelled' ? 'error' : 'idle';
    }
    const agentOutputs: Record<string, StandardAgentOutput | null> = {};
    for (const output of state.workflow?.completedOutputs.values() ?? []) {
        if (output.output_version !== 'v1') continue;
        if (!isStandardOutputKind(output.output_kind)) continue;
        agentOutputs[output.agent_id] = {
            kind: output.output_kind,
            version: 'v1',
            summary: output.summary,
            preview: output.preview,
            reference: output.artifact_id ? {
                artifact_id: output.artifact_id,
                download_url: buildArtifactUrl(output.artifact_id, output.identity.run_id),
                type: output.artifact_type ?? output.output_kind,
            } : null,
        };
        const agentOutput = agentOutputs[output.agent_id];
        if (agentOutput && hasDegradedPreview(agentOutput)) {
            agentStatuses[output.agent_id] = 'degraded';
        }
    }
    return {
        messages: state.messages,
        sendMessage,
        submitCommand,
        retryRun,
        loadHistory,
        isLoading,
        isSubmittingInteraction,
        error: state.error,
        threadId: state.threadId,
        runId: state.runId,
        connectionState: state.connection,
        cancelRun,
        hasMore,
        agentStatuses,
        agentOutputs,
        workflow: state.workflow,
        activeActivities,
    };
}
