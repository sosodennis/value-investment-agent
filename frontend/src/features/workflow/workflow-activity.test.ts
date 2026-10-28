import { describe, expect, it } from 'vitest';
import {
    applyWorkflowEvent,
    boundedReconnectDelay,
    createWorkflowActivityState,
    parseSseWorkflowEventFrame,
    parseWorkflowActivitySnapshot,
    parseWorkflowEvent,
} from './workflow-activity';

const identity = {
    thread_id: 'thread-1',
    run_id: 'run-1',
    activity_id: 'intent.clarifying',
    interaction_id: 'interaction-1',
};

const activity = (status: string = 'running', activityId = 'intent.clarifying'): Record<string, unknown> => ({
    activity_id: activityId,
    thread_id: 'thread-1',
    run_id: 'run-1',
    scope_path: ['intent', 'clarifying'],
    kind: 'node',
    status,
    label: 'Ticker resolution',
    attempt: 1,
});

const interaction = (status: string = 'pending') => ({
    identity,
    kind: 'ticker_selection',
    status,
    request: {
        type: 'ticker_selection',
        title: 'Choose a company',
        description: 'Select the intended company.',
        candidates: [{ symbol: 'AAPL', name: 'Apple Inc.', confidence: 0.99 }],
    },
    ...(status === 'responded' ? { response: { type: 'ticker_selection', selected_symbol: 'AAPL' } } : {}),
});

const approvalInteraction = (status: string = 'pending') => ({
    identity: {
        thread_id: 'thread-1',
        run_id: 'run-1',
        activity_id: 'fundamental.calculation',
        interaction_id: 'approval-1',
    },
    kind: 'valuation_approval',
    status,
    request: {
        type: 'valuation_approval',
        contract_version: 'v1',
        ticker: 'AAPL',
        model_type: 'dcf_growth',
        title: 'Review valuation assumptions',
        description: 'Approve before deterministic calculation.',
        parameters: { wacc: 0.09, terminal_growth: 0.025 },
        audit_messages: ['PASS: assumptions are consistent'],
    },
    ...(status === 'responded' ? {
        response: { type: 'valuation_approval', contract_version: 'v1', decision: 'approve' },
    } : {}),
});

const activityEvent = (seqId: number, payload = activity(), eventId = `event-${seqId}`) => ({
    event_id: eventId,
    seq_id: seqId,
    event_version: 'v2',
    event_name: 'workflow.activity',
    thread_id: 'thread-1',
    run_id: 'run-1',
    occurred_at: '2026-10-26T00:00:01Z',
    payload,
});

const interactionEvent = (seqId: number, payload: unknown = interaction()) => ({
    event_id: `event-${seqId}`,
    seq_id: seqId,
    event_version: 'v1',
    event_name: 'workflow.interaction',
    thread_id: 'thread-1',
    run_id: 'run-1',
    occurred_at: '2026-10-26T00:00:02Z',
    payload,
});

const outputEvent = (seqId: number, preview: Record<string, unknown> | null = null) => ({
    event_id: `event-${seqId}`,
    seq_id: seqId,
    event_version: 'v1',
    event_name: 'workflow.agent_output',
    thread_id: 'thread-1',
    run_id: 'run-1',
    occurred_at: '2026-10-26T00:00:03Z',
    payload: {
        identity: { thread_id: 'thread-1', run_id: 'run-1', activity_id: 'fundamental_analysis' },
        agent_id: 'fundamental_analysis',
        output_kind: 'fundamental_analysis.output',
        output_version: 'v1',
        summary: 'Intrinsic value report is ready.',
        preview,
        artifact_id: 'artifact-1',
    },
});

const snapshot = (overrides: Record<string, unknown> = {}) => ({
    thread_id: 'thread-1',
    run_id: 'run-1',
    run_status: 'running',
    cursor: 0,
    active_activities: [],
    recent_activities: [],
    pending_interactions: [],
    completed_outputs: [],
    ...overrides,
});

describe('workflow event boundary', () => {
    it('rejects unknown events, legacy activity interruptions, and cross-run identity', () => {
        expect(() => parseWorkflowEvent({ ...activityEvent(1), event_name: 'interrupt.request' })).toThrow(/unsupported/);
        expect(() => parseWorkflowEvent({ ...activityEvent(1), event_version: 'v1' })).toThrow(/v2/);
        expect(() => parseWorkflowEvent({
            ...activityEvent(1),
            payload: { ...activity(), interruption: { interaction_id: 'old' } },
        })).toThrow(/unsupported field/);
        expect(() => parseWorkflowEvent({ ...activityEvent(1), run_id: 'another-run' })).toThrow(/identity mismatch/);
        expect(() => parseWorkflowEvent(interactionEvent(1, {
            ...interaction(), identity: { ...identity, thread_id: 'another-thread' },
        }))).toThrow(/identity mismatch/);
    });

    it('folds activity, interaction, and output events on one ordered cursor', () => {
        const base = createWorkflowActivityState(parseWorkflowActivitySnapshot(snapshot()));
        const activityDelta = parseWorkflowEvent(activityEvent(1));
        const pendingDelta = parseWorkflowEvent(interactionEvent(2));
        const respondedDelta = parseWorkflowEvent(interactionEvent(3, interaction('responded')));
        const outputDelta = parseWorkflowEvent(outputEvent(4, { price: 120 }));
        const completeDelta = parseWorkflowEvent(activityEvent(5, activity('completed', 'workflow')));

        let state = applyWorkflowEvent(base, activityDelta);
        state = applyWorkflowEvent(state, pendingDelta);
        expect(state.runStatus).toBe('waiting');
        expect([...state.interactions.values()][0]?.status).toBe('pending');
        state = applyWorkflowEvent(state, respondedDelta);
        expect(state.runStatus).toBe('running');
        expect([...state.interactions.values()][0]?.status).toBe('responded');
        state = applyWorkflowEvent(state, outputDelta);
        expect(state.completedOutputs.size).toBe(1);
        state = applyWorkflowEvent(state, completeDelta);
        expect(state.cursor).toBe(5);
        expect(state.runStatus).toBe('completed');
        expect(state.active.size).toBe(1);
        expect(applyWorkflowEvent(state, completeDelta)).toBe(state);
    });

    it('parses and retains the versioned valuation approval through snapshot and response events', () => {
        const pending = approvalInteraction();
        const state = createWorkflowActivityState(parseWorkflowActivitySnapshot(snapshot({
            run_status: 'waiting',
            active_activities: [{ ...activity('waiting', 'fundamental.calculation'), scope_path: ['fundamental_analysis', 'calculation'] }],
            recent_activities: [{ ...activity('waiting', 'fundamental.calculation'), scope_path: ['fundamental_analysis', 'calculation'] }],
            pending_interactions: [pending],
        })));
        const parsed = [...state.interactions.values()][0];
        expect(parsed?.kind).toBe('valuation_approval');
        if (parsed?.kind !== 'valuation_approval') throw new Error('Approval interaction did not parse.');
        expect(parsed.request.contract_version).toBe('v1');
        expect(parsed.request.parameters.terminal_growth).toBe(0.025);

        const responded = parseWorkflowEvent(interactionEvent(1, approvalInteraction('responded')));
        if (responded.event_name !== 'workflow.interaction' || responded.payload.kind !== 'valuation_approval') {
            throw new Error('Approval response event did not parse.');
        }
        if (responded.payload.status !== 'responded' || !responded.payload.response) throw new Error('Approval response was not present.');
        expect(responded.payload.response.decision).toBe('approve');
        expect(() => parseWorkflowEvent(interactionEvent(1, {
            ...pending,
            request: { ...pending.request, contract_version: 'v2' },
        }))).toThrow(/contract_version/);
        expect(() => parseWorkflowEvent(interactionEvent(1, {
            ...pending,
            kind: 'ticker_selection',
        }))).toThrow(/request type/);
    });

    it('hydrates an exact run snapshot and rejects mismatched pending interactions', () => {
        const parsed = parseWorkflowActivitySnapshot(snapshot({
            run_status: 'waiting',
            cursor: 2,
            active_activities: [activity('waiting')],
            recent_activities: [activity('waiting')],
            pending_interactions: [interaction()],
            completed_outputs: [{
                identity: { thread_id: 'thread-1', run_id: 'run-1', activity_id: 'fundamental_analysis' },
                agent_id: 'fundamental_analysis',
                output_kind: 'fundamental_analysis.output',
                output_version: 'v1',
                summary: 'Intrinsic value report is ready.',
                artifact_id: 'artifact-1',
            }],
        }));
        const state = createWorkflowActivityState(parsed);
        expect([...state.interactions.values()][0]?.identity.run_id).toBe('run-1');
        expect(state.completedOutputs.size).toBe(1);
        expect(() => parseWorkflowActivitySnapshot(snapshot({
            pending_interactions: [{
                ...interaction(), identity: { ...identity, run_id: 'another-run' },
            }],
        }))).toThrow(/pending interaction identity/);
    });

    it('enforces candidate responses, output preview limits, SSE names, and replay gaps', () => {
        expect(() => parseWorkflowEvent(interactionEvent(1, {
            ...interaction('responded'),
            response: { type: 'ticker_selection', selected_symbol: 'MSFT' },
        }))).toThrow(/stored candidate/);
        expect(() => parseWorkflowEvent(outputEvent(1, { value: 'x'.repeat(16 * 1024) }))).toThrow(/16 KiB/);
        expect(() => parseSseWorkflowEventFrame(JSON.stringify(activityEvent(1)), 'workflow.interaction')).toThrow(/does not match/);
        expect(parseSseWorkflowEventFrame(JSON.stringify(interactionEvent(1)), 'workflow.interaction').event_id).toBe('event-1');

        const base = createWorkflowActivityState(parseWorkflowActivitySnapshot(snapshot({ cursor: 1 })));
        const gap = applyWorkflowEvent(base, parseWorkflowEvent(outputEvent(3)));
        expect(gap.gapDetected).toBe(true);
        expect(boundedReconnectDelay(20)).toBe(8000);
    });

    it('hydrates and replays safe failure provenance', () => {
        const failure = {
            code: 'schema_validation_failed',
            owner: 'llm_provider',
            activity_id: 'intent.extraction',
            retryable: false,
            message: 'The provider returned data that did not match the workflow contract.',
        };
        const parsed = parseWorkflowActivitySnapshot(snapshot({
            run_status: 'failed',
            failure,
            recent_activities: [{ ...activity('failed', 'workflow'), failure }],
        }));
        const state = createWorkflowActivityState(parsed);
        expect(state.failure).toEqual(failure);
        const next = applyWorkflowEvent(state, parseWorkflowEvent(activityEvent(1, {
            ...activity('failed', 'workflow'), failure,
        })));
        expect(next.failure).toEqual(failure);
        expect(() => parseWorkflowActivitySnapshot(snapshot({
            failure: { ...failure, retryable: 'no' },
        }))).toThrow(/retryable/);
    });
});
