import type { UnknownRecord } from '@/types/preview';

export const ACTIVITY_EVENT_NAME = 'workflow.activity' as const;
export const ACTIVITY_VERSION = 'v1' as const;
export const ACTIVITY_STATUSES = [
    'queued', 'running', 'waiting', 'completed', 'failed', 'cancelled', 'skipped',
] as const;
export const ACTIVITY_KINDS = ['phase', 'node', 'tool', 'subgraph'] as const;
export const TERMINAL_ACTIVITY_STATUSES = new Set<ActivityStatus>([
    'completed', 'failed', 'cancelled', 'skipped',
]);

export type ActivityStatus = (typeof ACTIVITY_STATUSES)[number];
export type ActivityKind = (typeof ACTIVITY_KINDS)[number];

export interface WorkflowActivity {
    activity_id: string;
    parent_activity_id?: string;
    thread_id: string;
    run_id: string;
    scope_path: string[];
    kind: ActivityKind;
    status: ActivityStatus;
    label: string;
    progress?: number;
    attempt: number;
}

export interface WorkflowActivityEvent {
    event_id: string;
    seq_id: number;
    event_version: typeof ACTIVITY_VERSION;
    event_name: typeof ACTIVITY_EVENT_NAME;
    thread_id: string;
    run_id: string;
    occurred_at: string;
    payload: WorkflowActivity;
}

export type WorkflowRunStatus = Exclude<ActivityStatus, 'skipped'> | 'queued' | 'unknown';

export interface WorkflowActivitySnapshot {
    thread_id: string;
    run_id: string;
    run_status: WorkflowRunStatus;
    cursor: number;
    active_activities: WorkflowActivity[];
    recent_activities: WorkflowActivity[];
}

export type ConnectionState = 'disconnected' | 'connecting' | 'connected' | 'reconnecting' | 'closed';

export interface WorkflowActivityState {
    threadId: string;
    runId: string;
    cursor: number;
    runStatus: WorkflowActivitySnapshot['run_status'];
    active: Map<string, WorkflowActivity>;
    recent: WorkflowActivity[];
    eventIds: Set<string>;
    connection: ConnectionState;
    gapDetected: boolean;
}

const MAX_EVENT_IDS = 1000;

function rememberEvent(eventIds: Set<string>, eventId: string): Set<string> {
    const next = new Set(eventIds);
    next.add(eventId);
    while (next.size > MAX_EVENT_IDS) {
        const oldest = next.values().next().value;
        if (oldest === undefined) break;
        next.delete(oldest);
    }
    return next;
}

const record = (value: unknown, context: string): UnknownRecord => {
    if (typeof value !== 'object' || value === null || Array.isArray(value)) {
        throw new TypeError(`${context} must be an object.`);
    }
    return value as UnknownRecord;
};
const string = (value: unknown, context: string): string => {
    if (typeof value !== 'string' || value.length === 0) throw new TypeError(`${context} must be a non-empty string.`);
    return value;
};
const integer = (value: unknown, context: string): number => {
    if (typeof value !== 'number' || !Number.isInteger(value)) throw new TypeError(`${context} must be an integer.`);
    return value;
};
const oneOf = <T extends string>(value: unknown, values: readonly T[], context: string): T => {
    if (typeof value !== 'string' || !values.includes(value as T)) throw new TypeError(`${context} has an unsupported value.`);
    return value as T;
};

export function parseWorkflowActivity(value: unknown, context = 'activity'): WorkflowActivity {
    const input = record(value, context);
    const scope = input.scope_path;
    if (!Array.isArray(scope) || scope.length < 1 || scope.some((part) => typeof part !== 'string' || part.length === 0)) {
        throw new TypeError(`${context}.scope_path must be a non-empty string array.`);
    }
    const progress = input.progress;
    if (progress !== undefined && (typeof progress !== 'number' || !Number.isFinite(progress) || progress < 0 || progress > 100)) {
        throw new TypeError(`${context}.progress must be a number between 0 and 100.`);
    }
    const result: WorkflowActivity = {
        activity_id: string(input.activity_id, `${context}.activity_id`),
        thread_id: string(input.thread_id, `${context}.thread_id`),
        run_id: string(input.run_id, `${context}.run_id`),
        scope_path: [...scope] as string[],
        kind: oneOf(input.kind, ACTIVITY_KINDS, `${context}.kind`),
        status: oneOf(input.status, ACTIVITY_STATUSES, `${context}.status`),
        label: string(input.label, `${context}.label`),
        attempt: integer(input.attempt, `${context}.attempt`),
    };
    if (result.attempt < 1) throw new TypeError(`${context}.attempt must be positive.`);
    if (input.parent_activity_id !== undefined) result.parent_activity_id = string(input.parent_activity_id, `${context}.parent_activity_id`);
    if (progress !== undefined) result.progress = progress;
    return result;
}

export function parseWorkflowActivityEvent(value: unknown, context = 'workflow.activity event'): WorkflowActivityEvent {
    const input = record(value, context);
    const eventVersion = input.event_version;
    if (eventVersion !== ACTIVITY_VERSION) throw new TypeError(`${context}.event_version must be v1.`);
    if (input.event_name !== ACTIVITY_EVENT_NAME) throw new TypeError(`${context}.event_name must be workflow.activity.`);
    const event: WorkflowActivityEvent = {
        event_id: string(input.event_id, `${context}.event_id`),
        seq_id: integer(input.seq_id, `${context}.seq_id`),
        event_version: ACTIVITY_VERSION,
        event_name: ACTIVITY_EVENT_NAME,
        thread_id: string(input.thread_id, `${context}.thread_id`),
        run_id: string(input.run_id, `${context}.run_id`),
        occurred_at: string(input.occurred_at, `${context}.occurred_at`),
        payload: parseWorkflowActivity(input.payload, `${context}.payload`),
    };
    if (event.seq_id < 1 || Number.isNaN(Date.parse(event.occurred_at))) throw new TypeError(`${context} has an invalid cursor or timestamp.`);
    if (event.payload.thread_id !== event.thread_id || event.payload.run_id !== event.run_id) throw new TypeError(`${context} thread/run identity mismatch.`);
    return event;
}

export function parseWorkflowActivitySnapshot(value: unknown, context = 'workflow.activity snapshot'): WorkflowActivitySnapshot {
    const input = record(value, context);
    const active = input.active_activities;
    const recent = input.recent_activities;
    if (!Array.isArray(active) || !Array.isArray(recent)) throw new TypeError(`${context} activity sets must be arrays.`);
    const snapshot: WorkflowActivitySnapshot = {
        thread_id: string(input.thread_id, `${context}.thread_id`),
        run_id: string(input.run_id, `${context}.run_id`),
        run_status: oneOf(input.run_status, ['queued', 'running', 'waiting', 'completed', 'failed', 'cancelled', 'unknown'], `${context}.run_status`),
        cursor: integer(input.cursor, `${context}.cursor`),
        active_activities: active.map((item, index) => parseWorkflowActivity(item, `${context}.active_activities[${index}]`)),
        recent_activities: recent.map((item, index) => parseWorkflowActivity(item, `${context}.recent_activities[${index}]`)),
    };
    if (snapshot.cursor < 0) throw new TypeError(`${context}.cursor must be non-negative.`);
    for (const activity of [...snapshot.active_activities, ...snapshot.recent_activities]) {
        if (activity.thread_id !== snapshot.thread_id || activity.run_id !== snapshot.run_id) throw new TypeError(`${context} activity identity mismatch.`);
    }
    return snapshot;
}

export function createWorkflowActivityState(snapshot: WorkflowActivitySnapshot): WorkflowActivityState {
    return {
        threadId: snapshot.thread_id, runId: snapshot.run_id, cursor: snapshot.cursor,
        runStatus: snapshot.run_status, active: new Map(snapshot.active_activities.map((item) => [item.activity_id, item])),
        recent: [...snapshot.recent_activities], eventIds: new Set(), connection: 'disconnected', gapDetected: false,
    };
}

export function applyWorkflowActivityEvent(state: WorkflowActivityState, event: WorkflowActivityEvent): WorkflowActivityState {
    if (event.thread_id !== state.threadId || event.run_id !== state.runId || event.payload.thread_id !== state.threadId || event.payload.run_id !== state.runId) throw new TypeError('workflow.activity event identity mismatch.');
    if (state.eventIds.has(event.event_id)) return state;
    if (event.seq_id <= state.cursor) return { ...state, eventIds: rememberEvent(state.eventIds, event.event_id) };
    if (event.seq_id !== state.cursor + 1) return { ...state, gapDetected: true };
    const active = new Map(state.active);
    if (TERMINAL_ACTIVITY_STATUSES.has(event.payload.status)) active.delete(event.payload.activity_id); else active.set(event.payload.activity_id, event.payload);
    const recent = [event.payload, ...state.recent.filter((item) => item.activity_id !== event.payload.activity_id)].slice(0, 100);
    return { ...state, cursor: event.seq_id, active, recent, eventIds: rememberEvent(state.eventIds, event.event_id), gapDetected: false };
}

export function parseSseActivityFrame(data: string): WorkflowActivityEvent {
    let value: unknown;
    try { value = JSON.parse(data); } catch { throw new TypeError('SSE data is not valid JSON.'); }
    return parseWorkflowActivityEvent(value, 'SSE workflow.activity event');
}

export function boundedReconnectDelay(attempt: number, baseMs = 250, maxMs = 8000): number {
    if (!Number.isFinite(attempt) || attempt < 0) return baseMs;
    return Math.min(maxMs, baseMs * (2 ** Math.floor(attempt)));
}
