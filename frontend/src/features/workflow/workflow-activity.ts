import type { components } from '@/types/generated/api-contract';

export const ACTIVITY_EVENT_NAME = 'workflow.activity' as const;
export const INTERACTION_EVENT_NAME = 'workflow.interaction' as const;
export const AGENT_OUTPUT_EVENT_NAME = 'workflow.agent_output' as const;
export const ACTIVITY_VERSION = 'v2' as const;
export const INTERACTION_VERSION = 'v1' as const;
export const AGENT_OUTPUT_VERSION = 'v1' as const;
export const ACTIVITY_KINDS = ['phase', 'node', 'tool', 'subgraph'] as const;
export const ACTIVITY_STATUSES = [
    'queued', 'running', 'waiting', 'completed', 'failed', 'cancelled', 'skipped',
] as const;

type Brand<Value extends string, Name extends string> = Value & {
    readonly __brand: Name;
};

export type ThreadId = Brand<string, 'ThreadId'>;
export type RunId = Brand<string, 'RunId'>;
export type ActivityId = Brand<string, 'ActivityId'>;
export type InteractionId = Brand<string, 'InteractionId'>;
export type EventId = Brand<string, 'EventId'>;

type ContractActivity = components['schemas']['Activity'];
type ContractActivityEvent = components['schemas']['ActivityEvent'];
type ContractInteraction = components['schemas']['WorkflowInteraction'];
type ContractInteractionEvent = components['schemas']['WorkflowInteractionEvent'];
type ContractAgentOutput = components['schemas']['WorkflowAgentOutput'];
type ContractAgentOutputEvent = components['schemas']['WorkflowAgentOutputEvent'];
type ContractFailure = components['schemas']['WorkflowFailure'];
type ContractSnapshot = components['schemas']['WorkflowSnapshot'];

export type ActivityStatus = ContractActivity['status'];
export type ActivityKind = ContractActivity['kind'];
export type TickerCandidate = components['schemas']['TickerCandidate'];
export type TickerSelectionRequest = components['schemas']['TickerSelectionRequest'];
export type TickerSelectionResponse = components['schemas']['TickerSelectionResponse'];
export type WorkflowRunStatus = ContractSnapshot['run_status'];
export type WorkflowFailure = ContractFailure;
export type ConnectionState = 'disconnected' | 'connecting' | 'connected' | 'reconnecting' | 'closed';

export type WorkflowActivity = Omit<ContractActivity, 'activity_id' | 'thread_id' | 'run_id'> & {
    activity_id: ActivityId;
    thread_id: ThreadId;
    run_id: RunId;
};

export type InteractionIdentity = Omit<components['schemas']['InteractionIdentity'], 'activity_id' | 'thread_id' | 'run_id' | 'interaction_id'> & {
    activity_id: ActivityId;
    thread_id: ThreadId;
    run_id: RunId;
    interaction_id: InteractionId;
};

export type WorkflowInteraction = Omit<ContractInteraction, 'identity'> & {
    identity: InteractionIdentity;
};

export type WorkflowAgentOutput = Omit<ContractAgentOutput, 'identity'> & {
    identity: Omit<components['schemas']['WorkflowActivityIdentity'], 'activity_id' | 'thread_id' | 'run_id'> & {
        activity_id: ActivityId;
        thread_id: ThreadId;
        run_id: RunId;
    };
};

type EventName = typeof ACTIVITY_EVENT_NAME | typeof INTERACTION_EVENT_NAME | typeof AGENT_OUTPUT_EVENT_NAME;

type EventEnvelope = {
    event_id: EventId;
    seq_id: number;
    thread_id: ThreadId;
    run_id: RunId;
    occurred_at: string;
};

export type WorkflowActivityEvent = Omit<ContractActivityEvent, 'event_id' | 'thread_id' | 'run_id' | 'payload'> & EventEnvelope & {
    payload: WorkflowActivity;
};

export type WorkflowInteractionEvent = Omit<ContractInteractionEvent, 'event_id' | 'thread_id' | 'run_id' | 'payload'> & EventEnvelope & {
    payload: WorkflowInteraction;
};

export type WorkflowAgentOutputEvent = Omit<ContractAgentOutputEvent, 'event_id' | 'thread_id' | 'run_id' | 'payload'> & EventEnvelope & {
    payload: WorkflowAgentOutput;
};

export type WorkflowEvent = WorkflowActivityEvent | WorkflowInteractionEvent | WorkflowAgentOutputEvent;

export type WorkflowActivitySnapshot = Omit<ContractSnapshot, 'thread_id' | 'run_id' | 'active_activities' | 'recent_activities' | 'pending_interactions' | 'completed_outputs'> & {
    thread_id: ThreadId;
    run_id: RunId;
    active_activities: WorkflowActivity[];
    recent_activities: WorkflowActivity[];
    pending_interactions: WorkflowInteraction[];
    completed_outputs: WorkflowAgentOutput[];
};

export interface WorkflowActivityState {
    threadId: ThreadId;
    runId: RunId;
    cursor: number;
    runStatus: WorkflowRunStatus;
    failure: WorkflowFailure | null;
    active: Map<ActivityId, WorkflowActivity>;
    recent: WorkflowActivity[];
    interactions: Map<InteractionId, WorkflowInteraction>;
    completedOutputs: Map<string, WorkflowAgentOutput>;
    eventIds: Set<EventId>;
    connection: ConnectionState;
    gapDetected: boolean;
}

export const TERMINAL_ACTIVITY_STATUSES = new Set<ActivityStatus>([
    'completed', 'failed', 'cancelled', 'skipped',
]);

const MAX_EVENT_IDS = 1000;
type UnknownRecord = Record<string, unknown>;

function isUnknownRecord(value: unknown): value is UnknownRecord {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function record(value: unknown, context: string): UnknownRecord {
    if (!isUnknownRecord(value)) throw new TypeError(`${context} must be an object.`);
    return value;
}

function onlyKeys(value: UnknownRecord, keys: readonly string[], context: string): void {
    const allowed = new Set(keys);
    if (Object.keys(value).some((key) => !allowed.has(key))) {
        throw new TypeError(`${context} has an unsupported field.`);
    }
}

function isNonEmptyString(value: unknown): value is string {
    return typeof value === 'string' && value.length > 0;
}

function string(value: unknown, context: string): string {
    if (!isNonEmptyString(value)) throw new TypeError(`${context} must be a non-empty string.`);
    return value;
}

function isThreadId(value: unknown): value is ThreadId {
    return isNonEmptyString(value);
}

function isRunId(value: unknown): value is RunId {
    return isNonEmptyString(value);
}

function isActivityId(value: unknown): value is ActivityId {
    return isNonEmptyString(value);
}

function isInteractionId(value: unknown): value is InteractionId {
    return isNonEmptyString(value);
}

function isEventId(value: unknown): value is EventId {
    return isNonEmptyString(value);
}

function identifier<Name extends string>(
    value: unknown,
    context: string,
    isIdentifier: (candidate: unknown) => candidate is Brand<string, Name>,
): Brand<string, Name> {
    if (!isIdentifier(value)) throw new TypeError(`${context} must be a non-empty identifier.`);
    return value;
}

function integer(value: unknown, context: string, minimum: number): number {
    if (typeof value !== 'number' || !Number.isInteger(value) || value < minimum) {
        throw new TypeError(`${context} must be an integer greater than or equal to ${minimum}.`);
    }
    return value;
}

function finiteNumber(value: unknown, context: string, minimum: number, maximum: number): number {
    if (typeof value !== 'number' || !Number.isFinite(value) || value < minimum || value > maximum) {
        throw new TypeError(`${context} must be a finite number between ${minimum} and ${maximum}.`);
    }
    return value;
}

function isOneOf<const Values extends readonly string[]>(
    value: unknown,
    values: Values,
): value is Values[number] {
    return typeof value === 'string' && values.includes(value);
}

function oneOf<const Values extends readonly string[]>(
    value: unknown,
    values: Values,
    context: string,
): Values[number] {
    if (!isOneOf(value, values)) throw new TypeError(`${context} has an unsupported value.`);
    return value;
}

function nullableString(value: unknown, context: string): string | null {
    if (value === null) return null;
    return string(value, context);
}

function parseCandidate(value: unknown, context: string): TickerCandidate {
    const input = record(value, context);
    onlyKeys(input, ['symbol', 'name', 'exchange', 'type', 'confidence'], context);
    const candidate: TickerCandidate = {
        symbol: string(input.symbol, `${context}.symbol`),
        name: string(input.name, `${context}.name`),
        confidence: finiteNumber(input.confidence, `${context}.confidence`, 0, 1),
    };
    if (input.exchange !== undefined) candidate.exchange = nullableString(input.exchange, `${context}.exchange`);
    if (input.type !== undefined) candidate.type = nullableString(input.type, `${context}.type`);
    return candidate;
}

function parseTickerRequest(value: unknown, context: string): TickerSelectionRequest {
    const input = record(value, context);
    onlyKeys(input, ['type', 'title', 'description', 'candidates'], context);
    if (!Array.isArray(input.candidates) || input.candidates.length < 1 || input.candidates.length > 20) {
        throw new TypeError(`${context}.candidates must contain 1 to 20 candidates.`);
    }
    return {
        type: oneOf(input.type, ['ticker_selection'], `${context}.type`),
        title: string(input.title, `${context}.title`),
        description: string(input.description, `${context}.description`),
        candidates: input.candidates.map((item, index) => parseCandidate(item, `${context}.candidates[${index}]`)),
    };
}

function parseTickerResponse(value: unknown, context: string): TickerSelectionResponse {
    const input = record(value, context);
    onlyKeys(input, ['type', 'selected_symbol'], context);
    return {
        type: oneOf(input.type, ['ticker_selection'], `${context}.type`),
        selected_symbol: string(input.selected_symbol, `${context}.selected_symbol`),
    };
}

function parseWorkflowFailure(value: unknown, context: string): WorkflowFailure {
    const input = record(value, context);
    onlyKeys(input, ['code', 'owner', 'activity_id', 'retryable', 'message'], context);
    return {
        code: string(input.code, `${context}.code`),
        owner: string(input.owner, `${context}.owner`),
        activity_id: input.activity_id === undefined || input.activity_id === null
            ? null
            : string(input.activity_id, `${context}.activity_id`),
        retryable: input.retryable === true || input.retryable === false
            ? input.retryable
            : (() => { throw new TypeError(`${context}.retryable must be a boolean.`); })(),
        message: string(input.message, `${context}.message`),
    };
}

export function parseWorkflowActivity(value: unknown, context = 'activity'): WorkflowActivity {
    const input = record(value, context);
    onlyKeys(input, [
        'activity_id', 'parent_activity_id', 'thread_id', 'run_id', 'scope_path',
        'kind', 'status', 'label', 'progress', 'attempt',
        'failure',
    ], context);
    if (!Array.isArray(input.scope_path) || input.scope_path.length < 1) {
        throw new TypeError(`${context}.scope_path must be a non-empty string array.`);
    }
    const scopePath = input.scope_path.map((part, index) => string(part, `${context}.scope_path[${index}]`));
    const activity: WorkflowActivity = {
        activity_id: identifier(input.activity_id, `${context}.activity_id`, isActivityId),
        thread_id: identifier(input.thread_id, `${context}.thread_id`, isThreadId),
        run_id: identifier(input.run_id, `${context}.run_id`, isRunId),
        scope_path: scopePath,
        kind: oneOf(input.kind, ['phase', 'node', 'tool', 'subgraph'], `${context}.kind`),
        status: oneOf(input.status, ['queued', 'running', 'waiting', 'completed', 'failed', 'cancelled', 'skipped'], `${context}.status`),
        label: string(input.label, `${context}.label`),
        attempt: integer(input.attempt, `${context}.attempt`, 1),
    };
    if (input.parent_activity_id !== undefined) {
        activity.parent_activity_id = nullableString(input.parent_activity_id, `${context}.parent_activity_id`);
    }
    if (input.progress !== undefined) {
        activity.progress = input.progress === null ? null : finiteNumber(input.progress, `${context}.progress`, 0, 100);
    }
    if (input.failure !== undefined && input.failure !== null) {
        activity.failure = parseWorkflowFailure(input.failure, `${context}.failure`);
    }
    return activity;
}

function parseInteractionIdentity(value: unknown, context: string): InteractionIdentity {
    const input = record(value, context);
    onlyKeys(input, ['thread_id', 'run_id', 'activity_id', 'interaction_id'], context);
    return {
        thread_id: identifier(input.thread_id, `${context}.thread_id`, isThreadId),
        run_id: identifier(input.run_id, `${context}.run_id`, isRunId),
        activity_id: identifier(input.activity_id, `${context}.activity_id`, isActivityId),
        interaction_id: identifier(input.interaction_id, `${context}.interaction_id`, isInteractionId),
    };
}

function parseWorkflowInteraction(value: unknown, context: string): WorkflowInteraction {
    const input = record(value, context);
    onlyKeys(input, ['identity', 'kind', 'status', 'request', 'response'], context);
    const request = parseTickerRequest(input.request, `${context}.request`);
    const status = oneOf(input.status, ['pending', 'responded', 'cancelled'], `${context}.status`);
    const response = input.response === undefined || input.response === null
        ? input.response
        : parseTickerResponse(input.response, `${context}.response`);
    if ((status === 'responded') !== (response !== undefined && response !== null)) {
        throw new TypeError(`${context} response is only valid for a responded interaction.`);
    }
    if (response && !request.candidates.some((candidate) => candidate.symbol === response.selected_symbol)) {
        throw new TypeError(`${context}.response must select a stored candidate.`);
    }
    const interaction: WorkflowInteraction = {
        identity: parseInteractionIdentity(input.identity, `${context}.identity`),
        kind: oneOf(input.kind, ['ticker_selection'], `${context}.kind`),
        status,
        request,
    };
    if (response !== undefined) interaction.response = response;
    return interaction;
}

function parseOutputIdentity(value: unknown, context: string): WorkflowAgentOutput['identity'] {
    const input = record(value, context);
    onlyKeys(input, ['thread_id', 'run_id', 'activity_id'], context);
    return {
        thread_id: identifier(input.thread_id, `${context}.thread_id`, isThreadId),
        run_id: identifier(input.run_id, `${context}.run_id`, isRunId),
        activity_id: identifier(input.activity_id, `${context}.activity_id`, isActivityId),
    };
}

function parseWorkflowAgentOutput(value: unknown, context: string): WorkflowAgentOutput {
    const input = record(value, context);
    onlyKeys(input, [
        'identity', 'agent_id', 'output_kind', 'output_version', 'summary', 'preview', 'artifact_id',
    ], context);
    const output: WorkflowAgentOutput = {
        identity: parseOutputIdentity(input.identity, `${context}.identity`),
        agent_id: string(input.agent_id, `${context}.agent_id`),
        output_kind: string(input.output_kind, `${context}.output_kind`),
        output_version: string(input.output_version, `${context}.output_version`),
        summary: string(input.summary, `${context}.summary`),
    };
    if (input.preview !== undefined) {
        if (input.preview === null) {
            output.preview = null;
        } else {
            const preview = record(input.preview, `${context}.preview`);
            const serialized = JSON.stringify(preview);
            if (serialized === undefined || new TextEncoder().encode(serialized).byteLength > 16 * 1024) {
                throw new TypeError(`${context}.preview exceeds 16 KiB.`);
            }
            output.preview = preview;
        }
    }
    if (input.artifact_id !== undefined) {
        output.artifact_id = input.artifact_id === null
            ? null
            : string(input.artifact_id, `${context}.artifact_id`);
    }
    return output;
}

function parseEventEnvelope(value: unknown, context: string): EventEnvelope & {
    event_name: EventName;
    event_version: unknown;
    payload: unknown;
} {
    const input = record(value, context);
    onlyKeys(input, [
        'event_id', 'seq_id', 'event_version', 'event_name', 'thread_id', 'run_id', 'occurred_at', 'payload',
    ], context);
    const occurredAt = string(input.occurred_at, `${context}.occurred_at`);
    if (Number.isNaN(Date.parse(occurredAt))) throw new TypeError(`${context}.occurred_at must be a date-time.`);
    return {
        event_id: identifier(input.event_id, `${context}.event_id`, isEventId),
        seq_id: integer(input.seq_id, `${context}.seq_id`, 1),
        thread_id: identifier(input.thread_id, `${context}.thread_id`, isThreadId),
        run_id: identifier(input.run_id, `${context}.run_id`, isRunId),
        occurred_at: occurredAt,
        event_name: oneOf(input.event_name, [ACTIVITY_EVENT_NAME, INTERACTION_EVENT_NAME, AGENT_OUTPUT_EVENT_NAME], `${context}.event_name`),
        event_version: input.event_version,
        payload: input.payload,
    };
}

export function parseWorkflowEvent(value: unknown, context = 'workflow event'): WorkflowEvent {
    const envelope = parseEventEnvelope(value, context);
    switch (envelope.event_name) {
        case ACTIVITY_EVENT_NAME: {
            if (envelope.event_version !== ACTIVITY_VERSION) throw new TypeError(`${context}.event_version must be v2.`);
            const payload = parseWorkflowActivity(envelope.payload, `${context}.payload`);
            if (payload.thread_id !== envelope.thread_id || payload.run_id !== envelope.run_id) {
                throw new TypeError(`${context} thread/run identity mismatch.`);
            }
            return {
                event_id: envelope.event_id,
                seq_id: envelope.seq_id,
                event_version: ACTIVITY_VERSION,
                event_name: ACTIVITY_EVENT_NAME,
                thread_id: envelope.thread_id,
                run_id: envelope.run_id,
                occurred_at: envelope.occurred_at,
                payload,
            };
        }
        case INTERACTION_EVENT_NAME: {
            if (envelope.event_version !== INTERACTION_VERSION) throw new TypeError(`${context}.event_version must be v1.`);
            const payload = parseWorkflowInteraction(envelope.payload, `${context}.payload`);
            if (payload.identity.thread_id !== envelope.thread_id || payload.identity.run_id !== envelope.run_id) {
                throw new TypeError(`${context} thread/run identity mismatch.`);
            }
            return {
                event_id: envelope.event_id,
                seq_id: envelope.seq_id,
                event_version: INTERACTION_VERSION,
                event_name: INTERACTION_EVENT_NAME,
                thread_id: envelope.thread_id,
                run_id: envelope.run_id,
                occurred_at: envelope.occurred_at,
                payload,
            };
        }
        case AGENT_OUTPUT_EVENT_NAME: {
            if (envelope.event_version !== AGENT_OUTPUT_VERSION) throw new TypeError(`${context}.event_version must be v1.`);
            const payload = parseWorkflowAgentOutput(envelope.payload, `${context}.payload`);
            if (payload.identity.thread_id !== envelope.thread_id || payload.identity.run_id !== envelope.run_id) {
                throw new TypeError(`${context} thread/run identity mismatch.`);
            }
            return {
                event_id: envelope.event_id,
                seq_id: envelope.seq_id,
                event_version: AGENT_OUTPUT_VERSION,
                event_name: AGENT_OUTPUT_EVENT_NAME,
                thread_id: envelope.thread_id,
                run_id: envelope.run_id,
                occurred_at: envelope.occurred_at,
                payload,
            };
        }
        default: {
            const exhaustive: never = envelope.event_name;
            throw new TypeError(`${context}.event_name is unsupported: ${exhaustive}`);
        }
    }
}

export function parseWorkflowActivitySnapshot(value: unknown, context = 'workflow snapshot'): WorkflowActivitySnapshot {
    const input = record(value, context);
    onlyKeys(input, [
        'thread_id', 'run_id', 'run_status', 'cursor', 'active_activities', 'recent_activities',
        'pending_interactions', 'completed_outputs', 'failure',
    ], context);
    const threadId = identifier(input.thread_id, `${context}.thread_id`, isThreadId);
    const runId = identifier(input.run_id, `${context}.run_id`, isRunId);
    function array(value: unknown, key: string): unknown[] {
        if (!Array.isArray(value)) throw new TypeError(`${context}.${key} must be an array.`);
        return value;
    }
    const activeValues = array(input.active_activities, 'active_activities');
    const recentValues = array(input.recent_activities, 'recent_activities');
    const interactionValues = array(input.pending_interactions, 'pending_interactions');
    const outputValues = array(input.completed_outputs, 'completed_outputs');
    const activeActivities = activeValues.map((item, index) => parseWorkflowActivity(item, `${context}.active_activities[${index}]`));
    const recentActivities = recentValues.map((item, index) => parseWorkflowActivity(item, `${context}.recent_activities[${index}]`));
    const pendingInteractions = interactionValues.map((item, index) => parseWorkflowInteraction(item, `${context}.pending_interactions[${index}]`));
    const completedOutputs = outputValues.map((item, index) => parseWorkflowAgentOutput(item, `${context}.completed_outputs[${index}]`));
    const failure = input.failure === undefined || input.failure === null
        ? null
        : parseWorkflowFailure(input.failure, `${context}.failure`);
    for (const item of activeActivities) {
        if (item.thread_id !== threadId || item.run_id !== runId) throw new TypeError(`${context} activity identity mismatch.`);
    }
    for (const item of recentActivities) {
        if (item.thread_id !== threadId || item.run_id !== runId) throw new TypeError(`${context} activity identity mismatch.`);
    }
    for (const item of pendingInteractions) {
        if (item.identity.thread_id !== threadId || item.identity.run_id !== runId || item.status !== 'pending') {
            throw new TypeError(`${context} pending interaction identity or status mismatch.`);
        }
    }
    for (const item of completedOutputs) {
        if (item.identity.thread_id !== threadId || item.identity.run_id !== runId) throw new TypeError(`${context} output identity mismatch.`);
    }
    return {
        thread_id: threadId,
        run_id: runId,
        run_status: oneOf(input.run_status, ['queued', 'running', 'waiting', 'completed', 'failed', 'cancelled', 'unknown'], `${context}.run_status`),
        cursor: integer(input.cursor, `${context}.cursor`, 0),
        active_activities: activeActivities,
        recent_activities: recentActivities,
        pending_interactions: pendingInteractions,
        completed_outputs: completedOutputs,
        failure,
    };
}

function rememberEvent(eventIds: Set<EventId>, eventId: EventId): Set<EventId> {
    const next = new Set(eventIds);
    next.add(eventId);
    while (next.size > MAX_EVENT_IDS) {
        const oldest = next.values().next().value;
        if (oldest === undefined) break;
        next.delete(oldest);
    }
    return next;
}

export function createWorkflowActivityState(snapshot: WorkflowActivitySnapshot): WorkflowActivityState {
    return {
        threadId: snapshot.thread_id,
        runId: snapshot.run_id,
        cursor: snapshot.cursor,
        runStatus: snapshot.run_status,
        failure: snapshot.failure ?? null,
        active: new Map(snapshot.active_activities.map((item) => [item.activity_id, item])),
        recent: [...snapshot.recent_activities],
        interactions: new Map(snapshot.pending_interactions.map((item) => [item.identity.interaction_id, item])),
        completedOutputs: new Map(snapshot.completed_outputs.map((item) => [JSON.stringify([item.identity.activity_id, item.agent_id]), item])),
        eventIds: new Set(),
        connection: 'disconnected',
        gapDetected: false,
    };
}

function statusForActivity(status: ActivityStatus): WorkflowRunStatus | null {
    switch (status) {
        case 'queued': return 'queued';
        case 'running': return 'running';
        case 'waiting': return 'waiting';
        case 'completed': return 'completed';
        case 'failed': return 'failed';
        case 'cancelled': return 'cancelled';
        case 'skipped': return null;
        default: {
            const exhaustive: never = status;
            return exhaustive;
        }
    }
}

export function applyWorkflowEvent(state: WorkflowActivityState, event: WorkflowEvent): WorkflowActivityState {
    if (event.thread_id !== state.threadId || event.run_id !== state.runId) {
        throw new TypeError('workflow event thread/run identity mismatch.');
    }
    if (state.eventIds.has(event.event_id)) return state;
    if (event.seq_id <= state.cursor) {
        return { ...state, eventIds: rememberEvent(state.eventIds, event.event_id) };
    }
    if (event.seq_id !== state.cursor + 1) return { ...state, gapDetected: true };

    const next: WorkflowActivityState = {
        ...state,
        cursor: event.seq_id,
        eventIds: rememberEvent(state.eventIds, event.event_id),
        gapDetected: false,
    };
    switch (event.event_name) {
        case ACTIVITY_EVENT_NAME: {
            const active = new Map(state.active);
            if (TERMINAL_ACTIVITY_STATUSES.has(event.payload.status)) {
                active.delete(event.payload.activity_id);
            } else {
                active.set(event.payload.activity_id, event.payload);
            }
            next.active = active;
            next.recent = [event.payload, ...state.recent.filter((item) => item.activity_id !== event.payload.activity_id)].slice(0, 100);
            if (event.payload.activity_id === 'workflow') {
                next.runStatus = statusForActivity(event.payload.status) ?? state.runStatus;
                next.failure = event.payload.failure ?? null;
            }
            return next;
        }
        case INTERACTION_EVENT_NAME: {
            const interactions = new Map(state.interactions);
            interactions.set(event.payload.identity.interaction_id, event.payload);
            next.interactions = interactions;
            if (event.payload.status === 'pending') next.runStatus = 'waiting';
            if (event.payload.status === 'responded') next.runStatus = 'running';
            if (event.payload.status === 'cancelled') next.runStatus = 'cancelled';
            return next;
        }
        case AGENT_OUTPUT_EVENT_NAME: {
            const completedOutputs = new Map(state.completedOutputs);
            completedOutputs.set(JSON.stringify([event.payload.identity.activity_id, event.payload.agent_id]), event.payload);
            next.completedOutputs = completedOutputs;
            return next;
        }
        default: {
            const exhaustive: never = event;
            return exhaustive;
        }
    }
}

export function parseSseWorkflowEventFrame(data: string, eventName: string): WorkflowEvent {
    let value: unknown;
    try {
        value = JSON.parse(data) as unknown;
    } catch {
        throw new TypeError('SSE data is not valid JSON.');
    }
    const event = parseWorkflowEvent(value, `SSE ${eventName} event`);
    if (event.event_name !== eventName) throw new TypeError('SSE event name does not match its data envelope.');
    return event;
}

export function boundedReconnectDelay(attempt: number, baseMs = 250, maxMs = 8000): number {
    if (!Number.isFinite(attempt) || attempt < 0) return baseMs;
    return Math.min(maxMs, baseMs * (2 ** Math.floor(attempt)));
}
