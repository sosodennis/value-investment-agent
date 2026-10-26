import { useCallback, useRef, useState } from 'react';
import { clientLogger } from '@/lib/logger';
import type { InterruptResumePayload } from '@/types/interrupts';
import type { AgentStatus, StandardAgentOutput } from '@/types/agents';
import { applyWorkflowActivityEvent, boundedReconnectDelay, cancelWorkflowRun, consumeWorkflowEvents, createWorkflowActivityState, getActivitySnapshot, startWorkflowRun, type WorkflowActivitySnapshot } from '@/features/workflow';
import { useAgentReducer } from './useAgentReducer';

const makeThreadId = () => `thread_${Date.now()}`;
const toError = (value: unknown, fallback: string) => value instanceof Error ? value.message : fallback;

export function useAgent(assistantId = 'agent') {
    void assistantId;
    const { state, initSession, setRun, hydrateWorkflow, processWorkflowEvent, setConnection, addUserMessage, setError } = useAgentReducer();
    const [isLoading, setIsLoading] = useState(false);
    const [hasMore] = useState(false);
    const abortRef = useRef<AbortController | null>(null);

    const attachStream = useCallback(async (threadId: string, initialSnapshot: WorkflowActivitySnapshot, expectedRunId = initialSnapshot.run_id) => {
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
                    const next = applyWorkflowActivityEvent(projection, event);
                    if (next.gapDetected) throw new Error('workflow sequence gap requires snapshot recovery.');
                    projection = next;
                    cursor = next.cursor;
                    processWorkflowEvent(event);
                    setConnection('connected');
                    return event.payload.activity_id === 'workflow' && ['completed', 'failed', 'cancelled'].includes(event.payload.status);
                }, expectedRunId);
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
            await attachStream(threadId, snapshot, run.run_id);
        } catch (error) { setError(toError(error, 'Failed to start workflow run.')); } finally { setIsLoading(false); }
    }, [addUserMessage, attachStream, hydrateWorkflow, initSession, setError, setRun, state.threadId]);

    const submitCommand = useCallback(async (payload: InterruptResumePayload) => {
        if (!state.threadId) { setError('Session ID missing.'); return; }
        const text = 'approved' in payload ? (payload.approved ? 'Approved' : 'Rejected') : 'selected_symbol' in payload ? `Selected ${payload.selected_symbol}` : 'Resumed execution';
        addUserMessage({ id: `user_${Date.now()}`, role: 'user', content: text, type: 'text' });
        setIsLoading(true);
        try {
            const run = await startWorkflowRun(state.threadId, { resume_payload: { ...payload } });
            setRun(run.run_id);
            const snapshot = await getActivitySnapshot(state.threadId, { runId: run.run_id });
            hydrateWorkflow(snapshot);
            await attachStream(state.threadId, snapshot, run.run_id);
        } catch (error) { setError(toError(error, 'Failed to resume workflow run.')); } finally { setIsLoading(false); }
    }, [addUserMessage, attachStream, hydrateWorkflow, setError, setRun, state.threadId]);

    const loadHistory = useCallback(async (threadId: string, expectedRunId?: string | null) => {
        setIsLoading(true);
        try {
            const snapshot = await getActivitySnapshot(
                threadId,
                expectedRunId ? { runId: expectedRunId } : undefined,
            );
            if (expectedRunId && snapshot.run_id !== expectedRunId) {
                throw new TypeError('activity snapshot run identity mismatch.');
            }
            hydrateWorkflow(snapshot);
            if (snapshot.run_status === 'running' || snapshot.run_status === 'waiting' || snapshot.run_status === 'queued') await attachStream(threadId, snapshot, snapshot.run_id);
        } catch (error) { setError(toError(error, 'Failed to load workflow snapshot.')); } finally { setIsLoading(false); }
    }, [attachStream, hydrateWorkflow, setError]);

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
    const agentStatuses: Record<string, AgentStatus> = {};
    for (const activity of activeActivities) {
        const id = activity.scope_path[0] ?? activity.activity_id;
        agentStatuses[id] = activity.status === 'waiting' ? 'attention' : activity.status === 'running' ? 'running' : activity.status === 'completed' ? 'done' : activity.status === 'failed' || activity.status === 'cancelled' ? 'error' : 'idle';
    }
    const agentOutputs: Record<string, StandardAgentOutput | null> = {};
    return {
        messages: state.messages,
        sendMessage,
        submitCommand,
        loadHistory,
        isLoading,
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
