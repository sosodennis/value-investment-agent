import { useCallback, useEffect, useRef, useState } from 'react';
import { clientLogger } from '@/lib/logger';
import type { AgentStatus, StandardAgentOutput } from '@/types/agents';
import { buildArtifactUrl } from '@/features/artifacts/api';
import { applyWorkflowEvent, boundedReconnectDelay, cancelWorkflowRun, consumeWorkflowEvents, createWorkflowActivityState, getActivitySnapshot, resumeWorkflowRun, startWorkflowRun, type InteractionId, type InteractionResponse, type WorkflowActivitySnapshot, type WorkflowInteraction } from '@/features/workflow';
import { useAgentReducer } from './useAgentReducer';

const makeThreadId = () => `thread_${Date.now()}`;
const toError = (value: unknown, fallback: string) => value instanceof Error ? value.message : fallback;
const STANDARD_OUTPUT_KINDS: readonly StandardAgentOutput['kind'][] = [
    'intent_extraction.output',
    'fundamental_analysis.output',
    'financial_news_research.output',
    'technical_analysis.output',
    'debate.output',
];

const isStandardOutputKind = (value: string): value is StandardAgentOutput['kind'] =>
    STANDARD_OUTPUT_KINDS.some((kind) => kind === value);

export function useAgent(assistantId = 'agent') {
    void assistantId;
    const { state, initSession, setRun, hydrateWorkflow, processWorkflowEvent, setConnection, addUserMessage, setError, reset } = useAgentReducer();
    const [isLoading, setIsLoading] = useState(false);
    const [submittingInteractionId, setSubmittingInteractionId] = useState<InteractionId | null>(null);
    const [hasMore] = useState(false);
    const abortRef = useRef<AbortController | null>(null);
    const submittingInteractionRef = useRef<InteractionId | null>(null);

    useEffect(() => () => abortRef.current?.abort(), []);

    const attachStream = useCallback(async (threadId: string, initialSnapshot: WorkflowActivitySnapshot, expectedRunId: string = initialSnapshot.run_id) => {
        if (initialSnapshot.run_id !== expectedRunId) throw new TypeError('activity snapshot run identity mismatch.');
        abortRef.current?.abort();
        const controller = new AbortController();
        abortRef.current = controller;
        let attempt = 0;
        let snapshot = initialSnapshot;
        let cursor = snapshot.cursor;
        let projection = createWorkflowActivityState(snapshot);
        while (!controller.signal.aborted && attempt < 5) {
            try {
                setConnection(attempt === 0 ? 'connecting' : 'reconnecting');
                await consumeWorkflowEvents(threadId, cursor, controller.signal, (event) => {
                    if (event.run_id !== expectedRunId || event.thread_id !== threadId) throw new TypeError('workflow event identity mismatch.');
                    const next = applyWorkflowEvent(projection, event);
                    if (next.gapDetected) throw new Error('workflow sequence gap requires snapshot recovery.');
                    projection = next;
                    cursor = next.cursor;
                    processWorkflowEvent(event);
                    return event.event_name === 'workflow.activity'
                        && event.payload.activity_id === 'workflow'
                        && ['completed', 'failed', 'cancelled'].includes(event.payload.status);
                }, expectedRunId, () => setConnection('connected'));
                if (controller.signal.aborted) return;
                snapshot = await getActivitySnapshot(threadId, { runId: expectedRunId, signal: controller.signal });
                if (snapshot.run_id !== expectedRunId) throw new TypeError('activity snapshot run identity mismatch.');
                hydrateWorkflow(snapshot);
                if (['completed', 'failed', 'cancelled'].includes(snapshot.run_status)) { setConnection('closed'); return; }
                cursor = snapshot.cursor;
                projection = createWorkflowActivityState(snapshot);
            } catch (error) {
                if (controller.signal.aborted) { setConnection('disconnected'); return; }
                clientLogger.error('workflow.stream.error', { threadId, attempt, error: toError(error, 'stream failed') });
                snapshot = await getActivitySnapshot(threadId, { runId: expectedRunId, signal: controller.signal });
                if (snapshot.run_id !== expectedRunId) throw new TypeError('activity snapshot run identity mismatch.');
                hydrateWorkflow(snapshot);
                if (['completed', 'failed', 'cancelled'].includes(snapshot.run_status)) { setConnection('closed'); return; }
                cursor = snapshot.cursor;
                projection = createWorkflowActivityState(snapshot);
            }
            attempt += 1;
            if (attempt < 5) await new Promise((resolve) => setTimeout(resolve, boundedReconnectDelay(attempt)));
        }
        setConnection('closed');
    }, [hydrateWorkflow, processWorkflowEvent, setConnection]);

    const sendMessage = useCallback(async (content: string, newSession = false) => {
        submittingInteractionRef.current = null;
        setSubmittingInteractionId(null);
        setIsLoading(true);
        const threadId = newSession || !state.threadId ? makeThreadId() : state.threadId;
        if (threadId !== state.threadId) initSession(threadId);
        addUserMessage({ id: `user_${Date.now()}`, role: 'user', content, type: 'text' });
        try {
            const run = await startWorkflowRun(threadId, { message: content });
            setRun(run.run_id);
            const snapshot = await getActivitySnapshot(threadId, { runId: run.run_id });
            if (snapshot.run_id !== run.run_id) throw new TypeError('activity snapshot run identity mismatch.');
            hydrateWorkflow(snapshot);
            setIsLoading(false);
            await attachStream(threadId, snapshot, run.run_id);
        } catch (error) { setError(toError(error, 'Failed to start workflow run.')); } finally { setIsLoading(false); }
    }, [addUserMessage, attachStream, hydrateWorkflow, initSession, setError, setRun, state.threadId]);

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
        submittingInteractionRef.current = interactionId;
        setSubmittingInteractionId(interactionId);
        const text = response.type === 'ticker_selection'
            ? `Selected ${response.selected_symbol}`
            : response.decision === 'approve' ? 'Approved valuation' : 'Rejected valuation';
        addUserMessage({ id: `user_${Date.now()}`, role: 'user', content: text, type: 'text' });
        try {
            const run = await resumeWorkflowRun(state.threadId, state.runId, {
                identity: currentInteraction.identity,
                response,
            });
            setRun(run.run_id);
            const snapshot = await getActivitySnapshot(state.threadId, { runId: run.run_id });
            hydrateWorkflow(snapshot);
            setIsLoading(false);
            await attachStream(state.threadId, snapshot, run.run_id);
        } catch (error) { setError(toError(error, 'Failed to resume workflow run.')); } finally {
            if (submittingInteractionRef.current === interactionId) {
                submittingInteractionRef.current = null;
                setSubmittingInteractionId(null);
            }
            setIsLoading(false);
        }
    }, [addUserMessage, attachStream, hydrateWorkflow, setError, setRun, state.runId, state.threadId, state.workflow]);

    const loadHistory = useCallback(async (threadId: string, expectedRunId: string) => {
        abortRef.current?.abort();
        abortRef.current = null;
        submittingInteractionRef.current = null;
        setSubmittingInteractionId(null);
        reset();
        setConnection('disconnected');
        setIsLoading(true);
        try {
            const snapshot = await getActivitySnapshot(threadId, { runId: expectedRunId });
            hydrateWorkflow(snapshot);
            setIsLoading(false);
            if (snapshot.run_status === 'running' || snapshot.run_status === 'waiting' || snapshot.run_status === 'queued') await attachStream(threadId, snapshot, snapshot.run_id);
        } catch (error) { setError(toError(error, 'Failed to load workflow snapshot.')); } finally { setIsLoading(false); }
    }, [attachStream, hydrateWorkflow, reset, setConnection, setError]);

    const cancelRun = useCallback(async () => {
        if (!state.threadId || !state.runId) return;
        try {
            await cancelWorkflowRun(state.threadId, state.runId);
            abortRef.current?.abort();
            const snapshot = await getActivitySnapshot(state.threadId, { runId: state.runId });
            hydrateWorkflow(snapshot);
            setConnection('closed');
        } catch (error) { setError(toError(error, 'Failed to cancel workflow run.')); }
    }, [hydrateWorkflow, setConnection, setError, state.runId, state.threadId]);

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
    }
    return {
        messages: state.messages,
        sendMessage,
        submitCommand,
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
