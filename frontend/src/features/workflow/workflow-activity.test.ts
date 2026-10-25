import { describe, expect, it } from 'vitest';
import {
    applyWorkflowActivityEvent,
    boundedReconnectDelay,
    createWorkflowActivityState,
    parseSseActivityFrame,
    parseWorkflowActivity,
    parseWorkflowActivityEvent,
    parseWorkflowActivitySnapshot,
} from './workflow-activity';

const tickerInterruption = {
    interaction_id: 'interaction-1',
    request: {
        type: 'ticker_selection',
        title: 'Ticker Resolution',
        description: 'Choose the intended company.',
        candidates: [{ symbol: 'GOOG', name: 'Alphabet Inc.', confidence: 0.91 }],
    },
};

const activity = (status: string = 'running') => ({
    activity_id: 'root', thread_id: 'thread-1', run_id: 'run-1', scope_path: ['root'],
    kind: 'node', status, label: 'Root', attempt: 1,
});
const event = (seq_id: number, event_id = `event-${seq_id}`, status = 'running') => ({
    event_id, seq_id, event_version: 'v1', event_name: 'workflow.activity', thread_id: 'thread-1', run_id: 'run-1', occurred_at: '2026-10-24T00:00:01Z', payload: activity(status),
});

describe('workflow.activity consumer boundary', () => {
    it('rejects malformed, unknown-first payloads and cross identity', () => {
        expect(() => parseWorkflowActivityEvent({ ...event(1), payload: { ...activity(), progress: 101 } })).toThrow();
        expect(() => parseWorkflowActivityEvent({ ...event(1), payload: { ...activity(), run_id: 'other' } })).toThrow(/identity/);
        expect(() => parseWorkflowActivityEvent({ ...event(1), event_name: 'interrupt.request' })).toThrow(/event_name/);
    });

    it('hydrates snapshot then applies ordered deltas with event id dedupe', () => {
        const snapshot = parseWorkflowActivitySnapshot({
            thread_id: 'thread-1', run_id: 'run-1', run_status: 'running', cursor: 0,
            active_activities: [], recent_activities: [],
        });
        let state = applyWorkflowActivityEvent(createWorkflowActivityState(snapshot), parseWorkflowActivityEvent(event(1)));
        state = applyWorkflowActivityEvent(state, parseWorkflowActivityEvent(event(1)));
        expect(state.cursor).toBe(1);
        expect(state.active.has('root')).toBe(true);
        expect(state.eventIds.size).toBe(1);
    });

    it('flags gaps for replay/snapshot recovery and models terminal activities as sets', () => {
        const snapshot = parseWorkflowActivitySnapshot({ thread_id: 'thread-1', run_id: 'run-1', run_status: 'running', cursor: 1, active_activities: [activity()], recent_activities: [] });
        const state = applyWorkflowActivityEvent(createWorkflowActivityState(snapshot), parseWorkflowActivityEvent(event(3)));
        expect(state.gapDetected).toBe(true);
        const completed = applyWorkflowActivityEvent({ ...state, cursor: 2, gapDetected: false }, parseWorkflowActivityEvent(event(3, 'event-3', 'completed')));
        expect(completed.active.size).toBe(0);
    });

    it('parses SSE frames and bounds reconnect backoff', () => {
        expect(parseSseActivityFrame(JSON.stringify(event(1))).event_id).toBe('event-1');
        expect(boundedReconnectDelay(20)).toBe(8000);
    });

    it('hydrates and replays the typed waiting interaction', () => {
        const waiting = parseWorkflowActivity({ ...activity('waiting'), interruption: tickerInterruption });
        const snapshot = parseWorkflowActivitySnapshot({
            thread_id: 'thread-1', run_id: 'run-1', run_status: 'waiting', cursor: 1,
            active_activities: [waiting], recent_activities: [waiting],
        });
        const state = createWorkflowActivityState(snapshot);
        expect(state.active.get('root')?.interruption?.interaction_id).toBe('interaction-1');
        expect(() => parseWorkflowActivity({ ...activity('waiting'), type: 'ticker_selection', data: {} })).toThrow(/unsupported field/);
        expect(() => parseWorkflowActivity({ ...activity('waiting'), interruption: { ...tickerInterruption, request: { ...tickerInterruption.request, candidates: [] } } })).toThrow(/candidates/);
    });
});
