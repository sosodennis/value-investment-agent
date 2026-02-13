import {
    AgentErrorLog,
    AgentOutputKind,
    AgentStatus,
    StandardAgentOutput,
} from './agents';
import {
    HumanTickerSelection,
    InterruptRequestData,
    parseInterruptRequestData,
    InterruptResumePayload,
    IntentExtraction,
    TickerCandidate,
} from './interrupts';
import { isRecord } from './preview';
import { operations } from './generated/api-contract';

type ApiThreadStateResponse =
    operations['get_thread_history_thread__thread_id__get']['responses'][200]['content']['application/json'];
type ApiStreamStartResponse =
    operations['stream_agent_stream_post']['responses'][200]['content']['application/json'];
type ApiAgentStatusesResponse =
    operations['get_agent_statuses_thread__thread_id__agents_get']['responses'][200]['content']['application/json'];

export interface Message {
    id: string;
    role: 'user' | 'assistant' | 'system' | 'tool';
    content: string;
    type?: 'text' | 'financial_report' | 'interrupt.request';
    data?: unknown;
    isInteractive?: boolean;
    created_at?: string | null;
    agentId?: string;
}

const AGENT_STATUS_VALUES: AgentStatus[] = [
    'idle',
    'running',
    'done',
    'attention',
    'error',
    'degraded',
];

const isAgentStatus = (value: unknown): value is AgentStatus =>
    AGENT_STATUS_VALUES.some((status) => status === value);

const toRecord = (
    value: unknown,
    context: string
): Record<string, unknown> => {
    if (!isRecord(value) || Array.isArray(value)) {
        throw new TypeError(`${context} must be an object.`);
    }
    return value;
};

const isMessageRole = (value: unknown): value is Message['role'] =>
    value === 'user' ||
    value === 'assistant' ||
    value === 'system' ||
    value === 'tool';

const parseOptionalString = (value: unknown, context: string): string | undefined => {
    if (value === undefined) return undefined;
    if (typeof value === 'string') return value;
    throw new TypeError(`${context} must be a string | undefined.`);
};

const parseNullableOptionalString = (
    value: unknown,
    context: string
): string | null | undefined => {
    if (value === undefined || value === null) return value;
    if (typeof value === 'string') return value;
    throw new TypeError(`${context} must be a string | null | undefined.`);
};

const parseMessageType = (
    value: unknown,
    context: string
): NonNullable<Message['type']> => {
    if (value === 'text') return value;
    if (value === 'financial_report') return value;
    if (value === 'interrupt.request') return value;
    throw new TypeError(
        `${context} must be one of text | financial_report | interrupt.request.`
    );
};

const parseAgentStatus = (value: unknown, context: string): AgentStatus => {
    if (isAgentStatus(value)) {
        return value;
    }
    throw new TypeError(`${context} has unsupported status value.`);
};

const parseAgentOutputKind = (
    value: unknown,
    context: string
): AgentOutputKind => {
    if (value === 'intent_extraction.output') return value;
    if (value === 'fundamental_analysis.output') return value;
    if (value === 'financial_news_research.output') return value;
    if (value === 'debate.output') return value;
    if (value === 'technical_analysis.output') return value;
    if (value === 'generic.output') return value;
    throw new TypeError(`${context}.kind has unsupported value.`);
};

const parseAgentOutputVersion = (
    value: unknown,
    context: string
): 'v1' => {
    if (value !== 'v1') {
        throw new TypeError(`${context}.version must be v1.`);
    }
    return value;
};

const parseTickerCandidate = (value: unknown, context: string): TickerCandidate => {
    const record = toRecord(value, context);
    const symbol = record.symbol;
    const name = record.name;
    const confidence = record.confidence;

    if (typeof symbol !== 'string') {
        throw new TypeError(`${context}.symbol must be a string.`);
    }
    if (typeof name !== 'string') {
        throw new TypeError(`${context}.name must be a string.`);
    }
    if (typeof confidence !== 'number') {
        throw new TypeError(`${context}.confidence must be a number.`);
    }

    const exchange = parseNullableOptionalString(
        record.exchange,
        `${context}.exchange`
    );
    const type = parseNullableOptionalString(record.type, `${context}.type`);

    const candidate: TickerCandidate = {
        symbol,
        name,
        confidence,
    };
    if (exchange !== undefined) candidate.exchange = exchange;
    if (type !== undefined) candidate.type = type;
    return candidate;
};

const parseIntentExtraction = (
    value: unknown,
    context: string
): IntentExtraction | undefined => {
    if (value === undefined || value === null) return undefined;
    const record = toRecord(value, context);
    const isValuation = record.is_valuation_request;
    if (typeof isValuation !== 'boolean') {
        throw new TypeError(`${context}.is_valuation_request must be a boolean.`);
    }

    const companyName = parseNullableOptionalString(
        record.company_name,
        `${context}.company_name`
    );
    const ticker = parseNullableOptionalString(record.ticker, `${context}.ticker`);
    const modelPreference = parseNullableOptionalString(
        record.model_preference,
        `${context}.model_preference`
    );
    const reasoning = parseNullableOptionalString(
        record.reasoning,
        `${context}.reasoning`
    );

    const intent: IntentExtraction = {
        is_valuation_request: isValuation,
    };
    if (companyName !== undefined) intent.company_name = companyName;
    if (ticker !== undefined) intent.ticker = ticker;
    if (modelPreference !== undefined) {
        intent.model_preference = modelPreference;
    }
    if (reasoning !== undefined) intent.reasoning = reasoning;
    return intent;
};

const parseHumanTickerSelection = (
    value: unknown,
    context: string
): HumanTickerSelection => {
    const record = toRecord(value, context);
    if (record.type !== 'ticker_selection') {
        throw new TypeError(`${context}.type must be ticker_selection.`);
    }

    const candidatesRaw = record.candidates;
    if (!Array.isArray(candidatesRaw)) {
        throw new TypeError(`${context}.candidates must be an array.`);
    }
    const candidates = candidatesRaw.map((candidate, idx) =>
        parseTickerCandidate(candidate, `${context}.candidates[${idx}]`)
    );
    if (typeof record.reason !== 'string') {
        throw new TypeError(`${context}.reason must be a string.`);
    }

    return {
        type: 'ticker_selection',
        candidates,
        intent: parseIntentExtraction(record.intent, `${context}.intent`),
        reason: record.reason,
    };
};

const parseErrorLogs = (value: unknown, context: string): AgentErrorLog[] => {
    if (!Array.isArray(value)) {
        throw new TypeError(`${context} must be an array.`);
    }
    return value.map((entry, idx) => {
        const record = toRecord(entry, `${context}[${idx}]`);
        const node = record.node;
        const error = record.error;
        const severity = record.severity;
        if (typeof node !== 'string') {
            throw new TypeError(`${context}[${idx}].node must be a string.`);
        }
        if (typeof error !== 'string') {
            throw new TypeError(`${context}[${idx}].error must be a string.`);
        }
        if (severity !== 'warning' && severity !== 'error') {
            throw new TypeError(
                `${context}[${idx}].severity must be warning or error.`
            );
        }
        return {
            node,
            error,
            severity,
            timestamp: parseOptionalString(record.timestamp, `${context}[${idx}].timestamp`),
        };
    });
};

const parseStandardAgentOutput = (
    value: unknown,
    context: string
): StandardAgentOutput => {
    const record = toRecord(value, context);
    const kind = parseAgentOutputKind(record.kind, context);
    const version = parseAgentOutputVersion(record.version, context);
    const summary = record.summary;
    if (typeof summary !== 'string') {
        throw new TypeError(`${context}.summary must be a string.`);
    }

    const previewRaw = record.preview;
    const preview =
        previewRaw === undefined
            ? undefined
            : previewRaw === null
              ? null
              : toRecord(previewRaw, `${context}.preview`);

    const referenceRaw = record.reference;
    let reference: StandardAgentOutput['reference'] | undefined;
    if (referenceRaw === null) {
        reference = null;
    } else if (referenceRaw !== undefined) {
        const referenceRecord = toRecord(referenceRaw, `${context}.reference`);
        const artifactId = referenceRecord.artifact_id;
        const downloadUrl = referenceRecord.download_url;
        const type = referenceRecord.type;
        if (
            typeof artifactId !== 'string' ||
            typeof downloadUrl !== 'string' ||
            typeof type !== 'string'
        ) {
            throw new TypeError(
                `${context}.reference must include string artifact_id, download_url, type.`
            );
        }
        reference = {
            artifact_id: artifactId,
            download_url: downloadUrl,
            type,
        };
    }

    const output: StandardAgentOutput = { kind, version, summary };
    if (preview !== undefined) output.preview = preview;
    if (reference !== undefined) output.reference = reference;
    if ('error_logs' in record && record.error_logs !== undefined) {
        output.error_logs = parseErrorLogs(record.error_logs, `${context}.error_logs`);
    }
    return output;
};

const parseMessage = (value: unknown, context: string): Message => {
    const record = toRecord(value, context);
    const id = record.id;
    const role = record.role;
    const content = record.content;
    if (typeof id !== 'string') {
        throw new TypeError(`${context}.id must be a string.`);
    }
    if (!isMessageRole(role)) {
        throw new TypeError(`${context}.role is invalid.`);
    }
    if (typeof content !== 'string') {
        throw new TypeError(`${context}.content must be a string.`);
    }

    const type = parseMessageType(record.type, `${context}.type`);
    const message: Message = {
        id,
        role,
        content,
        type,
    };

    if ('data' in record) {
        message.data =
            type === 'interrupt.request'
                ? parseInterruptRequestData(record.data, `${context}.data`)
                : record.data;
    } else if (type === 'interrupt.request') {
        throw new TypeError(`${context}.data is required for interrupt.request.`);
    }
    if ('created_at' in record) {
        const createdAt = parseNullableOptionalString(
            record.created_at,
            `${context}.created_at`
        );
        if (createdAt !== undefined) {
            message.created_at = createdAt;
        }
    }
    if (typeof record.agentId === 'string') {
        message.agentId = record.agentId;
    }
    return message;
};

export const parseHistoryResponse = (value: unknown): Message[] => {
    if (!Array.isArray(value)) {
        throw new TypeError('history response must be an array.');
    }
    return value.map((entry, idx) => parseMessage(entry, `history[${idx}]`));
};

export const parseThreadStateResponse = (
    value: unknown
): ThreadStateResponse => {
    const record = toRecord(value, 'thread response');
    const threadId = record.thread_id;
    const isRunning = record.is_running;
    const lastSeqId = record.last_seq_id;
    if (typeof threadId !== 'string') {
        throw new TypeError('thread response.thread_id must be a string.');
    }
    if (typeof isRunning !== 'boolean') {
        throw new TypeError('thread response.is_running must be a boolean.');
    }
    if (typeof lastSeqId !== 'number') {
        throw new TypeError('thread response.last_seq_id must be a number.');
    }

    const messages = parseHistoryResponse(record.messages);

    if (!Array.isArray(record.interrupts)) {
        throw new TypeError('thread response.interrupts must be an array.');
    }
    const interrupts = record.interrupts.map((interrupt, idx) =>
        parseHumanTickerSelection(interrupt, `thread.interrupts[${idx}]`)
    );

    const nodeStatusesRecord = toRecord(
        record.node_statuses,
        'thread response.node_statuses'
    );
    const node_statuses: Record<string, AgentStatus> = {};
    for (const [node, statusRaw] of Object.entries(nodeStatusesRecord)) {
        node_statuses[node] = parseAgentStatus(
            statusRaw,
            `thread.node_statuses.${node}`
        );
    }

    const agentOutputsRecord = toRecord(
        record.agent_outputs,
        'thread response.agent_outputs'
    );
    const agent_outputs: Record<string, StandardAgentOutput> = {};
    for (const [agentId, output] of Object.entries(agentOutputsRecord)) {
        agent_outputs[agentId] = parseStandardAgentOutput(
            output,
            `thread.agent_outputs.${agentId}`
        );
    }

    let next: string[] | null | undefined;
    if (record.next === undefined) {
        next = undefined;
    } else if (record.next === null) {
        next = null;
    } else if (Array.isArray(record.next) && record.next.every((v) => typeof v === 'string')) {
        next = record.next;
    } else {
        throw new TypeError('thread response.next must be string[] | null.');
    }

    const resolved_ticker = parseNullableOptionalString(
        record.resolved_ticker,
        'thread response.resolved_ticker'
    );
    const status = parseNullableOptionalString(
        record.status,
        'thread response.status'
    );

    const response: ThreadStateResponse = {
        thread_id: threadId,
        is_running: isRunning,
        last_seq_id: lastSeqId,
        messages,
        interrupts,
        node_statuses,
        agent_outputs,
        next,
    };
    if (resolved_ticker !== undefined) response.resolved_ticker = resolved_ticker;
    if (status !== undefined) response.status = status;
    return response;
};

export const parseStreamStartResponse = (
    value: unknown
): StreamStartResponse => {
    const record = toRecord(value, 'stream start response');
    if (record.status !== 'started' && record.status !== 'running') {
        throw new TypeError('stream start response.status must be started or running.');
    }
    if (typeof record.thread_id !== 'string') {
        throw new TypeError('stream start response.thread_id must be a string.');
    }
    return {
        status: record.status,
        thread_id: record.thread_id,
    };
};

export type AgentEventType =
    | 'lifecycle.status'
    | 'content.delta'
    | 'state.update'
    | 'interrupt.request'
    | 'agent.status'
    | 'error';

const isAgentEventType = (value: unknown): value is AgentEventType =>
    value === 'lifecycle.status' ||
    value === 'content.delta' ||
    value === 'state.update' ||
    value === 'interrupt.request' ||
    value === 'agent.status' ||
    value === 'error';

type LifecycleStatus = LifecycleStatusEvent['data']['status'];
const LIFECYCLE_STATUS_VALUES: LifecycleStatus[] = [
    'idle',
    'running',
    'paused',
    'error',
    'done',
];

const isLifecycleStatus = (value: unknown): value is LifecycleStatus =>
    LIFECYCLE_STATUS_VALUES.some((status) => status === value);

interface AgentEventBase {
    id: string;
    timestamp: string;
    thread_id: string;
    run_id: string;
    seq_id: number;
    protocol_version: 'v1';
    source: string;
    metadata?: Record<string, unknown>;
}

export interface ContentDeltaEvent extends AgentEventBase {
    type: 'content.delta';
    data: {
        content: string;
    };
}

export interface StateUpdateEvent extends AgentEventBase {
    type: 'state.update';
    data: StandardAgentOutput;
}

export interface InterruptRequestEvent extends AgentEventBase {
    type: 'interrupt.request';
    data: InterruptRequestData;
}

export interface AgentStatusEvent extends AgentEventBase {
    type: 'agent.status';
    data: {
        status: AgentStatus;
        node?: string;
    };
}

export interface LifecycleStatusEvent extends AgentEventBase {
    type: 'lifecycle.status';
    data: {
        status: 'idle' | 'running' | 'paused' | 'error' | 'done';
    };
}

export interface ErrorEvent extends AgentEventBase {
    type: 'error';
    data: {
        message: string;
    };
}

export type AgentEvent =
    | ContentDeltaEvent
    | StateUpdateEvent
    | InterruptRequestEvent
    | AgentStatusEvent
    | LifecycleStatusEvent
    | ErrorEvent;

export type ThreadStateResponse = Omit<
    ApiThreadStateResponse,
    'node_statuses' | 'agent_outputs' | 'interrupts' | 'messages'
> & {
    messages: Message[];
    interrupts: HumanTickerSelection[];
    node_statuses: Record<string, AgentStatus>;
    agent_outputs: Record<string, StandardAgentOutput>;
};

export type AgentStatusesResponse = Omit<
    ApiAgentStatusesResponse,
    'node_statuses' | 'agent_outputs'
> & {
    node_statuses: Record<string, AgentStatus>;
    agent_outputs: Record<string, StandardAgentOutput>;
};

export interface StreamRequest {
    thread_id: string;
    message?: string;
    resume_payload?: InterruptResumePayload;
}

export type StreamStartResponse = ApiStreamStartResponse;

const parseValidationErrorMessage = (value: unknown): string | null => {
    if (!Array.isArray(value)) return null;
    const messages: string[] = [];
    for (const entry of value) {
        if (!isRecord(entry) || Array.isArray(entry)) {
            continue;
        }
        const record = entry;
        const msg = record.msg;
        if (typeof msg !== 'string') continue;
        const locRaw = record.loc;
        const loc =
            Array.isArray(locRaw) &&
            locRaw.every((part) => typeof part === 'string' || typeof part === 'number')
                ? locRaw.map(String).join('.')
                : null;
        messages.push(loc ? `${loc}: ${msg}` : msg);
    }
    return messages.length > 0 ? messages.join('; ') : null;
};

export const parseApiErrorMessage = (
    value: unknown
): string | null => {
    if (!isRecord(value)) return null;
    if (!('detail' in value)) return null;
    const detail = value.detail;
    if (typeof detail === 'string') return detail;
    const validationMessage = parseValidationErrorMessage(detail);
    return validationMessage;
};

export const parseAgentStatusesResponse = (
    value: unknown
): AgentStatusesResponse => {
    const record = toRecord(value, 'agent statuses response');
    const nodeStatusesRecord = toRecord(
        record.node_statuses,
        'agent statuses response.node_statuses'
    );
    const node_statuses: Record<string, AgentStatus> = {};
    for (const [node, statusRaw] of Object.entries(nodeStatusesRecord)) {
        node_statuses[node] = parseAgentStatus(
            statusRaw,
            `agent statuses response.node_statuses.${node}`
        );
    }

    const outputsRecord = toRecord(
        record.agent_outputs,
        'agent statuses response.agent_outputs'
    );
    const agent_outputs: Record<string, StandardAgentOutput> = {};
    for (const [agentId, output] of Object.entries(outputsRecord)) {
        agent_outputs[agentId] = parseStandardAgentOutput(
            output,
            `agent statuses response.agent_outputs.${agentId}`
        );
    }

    const current_node = parseNullableOptionalString(
        record.current_node,
        'agent statuses response.current_node'
    );
    const response: AgentStatusesResponse = {
        node_statuses,
        agent_outputs,
    };
    if (current_node !== undefined) {
        response.current_node = current_node;
    }
    return response;
};

export const parseAgentEvent = (
    value: unknown,
    context = 'agent event'
): AgentEvent => {
    const record = toRecord(value, context);
    if (!isAgentEventType(record.type)) {
        throw new TypeError(`${context}.type is invalid.`);
    }

    const id = record.id;
    const timestamp = record.timestamp;
    const threadId = record.thread_id;
    const runId = record.run_id;
    const seqId = record.seq_id;
    const protocolVersion = record.protocol_version;
    const source = record.source;
    if (typeof id !== 'string') {
        throw new TypeError(`${context}.id must be a string.`);
    }
    if (typeof timestamp !== 'string') {
        throw new TypeError(`${context}.timestamp must be a string.`);
    }
    if (typeof threadId !== 'string') {
        throw new TypeError(`${context}.thread_id must be a string.`);
    }
    if (typeof runId !== 'string') {
        throw new TypeError(`${context}.run_id must be a string.`);
    }
    if (typeof seqId !== 'number') {
        throw new TypeError(`${context}.seq_id must be a number.`);
    }
    if (protocolVersion !== 'v1') {
        throw new TypeError(`${context}.protocol_version must be v1.`);
    }
    if (typeof source !== 'string') {
        throw new TypeError(`${context}.source must be a string.`);
    }

    let metadata: Record<string, unknown> | undefined;
    if ('metadata' in record && record.metadata !== undefined) {
        metadata = toRecord(record.metadata, `${context}.metadata`);
    }

    const base: AgentEventBase = {
        id,
        timestamp,
        thread_id: threadId,
        run_id: runId,
        seq_id: seqId,
        protocol_version: 'v1',
        source,
    };
    const baseWithMetadata: AgentEventBase =
        metadata === undefined ? base : { ...base, metadata };

    if (record.type === 'content.delta') {
        const data = toRecord(record.data, `${context}.data`);
        const content = data.content;
        if (typeof content !== 'string') {
            throw new TypeError(`${context}.data.content must be a string.`);
        }
        return {
            ...baseWithMetadata,
            type: 'content.delta',
            data: {
                content,
            },
        };
    }

    if (record.type === 'state.update') {
        return {
            ...baseWithMetadata,
            type: 'state.update',
            data: parseStandardAgentOutput(record.data, `${context}.data`),
        };
    }

    if (record.type === 'interrupt.request') {
        return {
            ...baseWithMetadata,
            type: 'interrupt.request',
            data: parseInterruptRequestData(record.data, `${context}.data`),
        };
    }

    if (record.type === 'agent.status') {
        const data = toRecord(record.data, `${context}.data`);
        const status = parseAgentStatus(data.status, `${context}.data.status`);
        const node = parseOptionalString(data.node, `${context}.data.node`);
        const event: AgentStatusEvent = {
            ...baseWithMetadata,
            type: 'agent.status',
            data: {
                status,
            },
        };
        if (node !== undefined) {
            event.data.node = node;
        }
        return event;
    }

    if (record.type === 'lifecycle.status') {
        const data = toRecord(record.data, `${context}.data`);
        if (!isLifecycleStatus(data.status)) {
            throw new TypeError(`${context}.data.status is invalid.`);
        }
        return {
            ...baseWithMetadata,
            type: 'lifecycle.status',
            data: {
                status: data.status,
            },
        };
    }

    const data = toRecord(record.data, `${context}.data`);
    const message = data.message;
    if (typeof message !== 'string') {
        throw new TypeError(`${context}.data.message must be a string.`);
    }
    return {
        ...baseWithMetadata,
        type: 'error',
        data: {
            message,
        },
    };
};

export const isAgentEvent = (value: unknown): value is AgentEvent => {
    try {
        parseAgentEvent(value);
        return true;
    } catch {
        return false;
    }
};
