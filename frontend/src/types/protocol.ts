import { AgentErrorLog, AgentStatus, StandardAgentOutput } from './agents';
import {
    HumanTickerSelection,
    InterruptRequestData,
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

    const exchange = parseOptionalString(record.exchange, `${context}.exchange`);
    const type = parseOptionalString(record.type, `${context}.type`);

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
    const reasoning = record.reasoning;
    if (typeof isValuation !== 'boolean') {
        throw new TypeError(`${context}.is_valuation_request must be a boolean.`);
    }
    if (typeof reasoning !== 'string') {
        throw new TypeError(`${context}.reasoning must be a string.`);
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

    const intent: IntentExtraction = {
        is_valuation_request: isValuation,
        reasoning,
    };
    if (companyName !== undefined) intent.company_name = companyName;
    if (ticker !== undefined) intent.ticker = ticker;
    if (modelPreference !== undefined) {
        intent.model_preference = modelPreference;
    }
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

    const output: StandardAgentOutput = { summary };
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

    const message: Message = {
        id,
        role,
        content,
        type: parseMessageType(record.type, `${context}.type`),
    };

    if ('data' in record) {
        message.data = record.data;
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

export interface StreamRequest {
    thread_id: string;
    message?: string;
    resume_payload?: InterruptResumePayload;
}

export type StreamStartResponse = ApiStreamStartResponse;

export const isAgentEvent = (value: unknown): value is AgentEvent => {
    if (!isRecord(value)) return false;
    const type = value.type;
    if (typeof type !== 'string') return false;
    if (typeof value.id !== 'string') return false;
    if (typeof value.timestamp !== 'string') return false;
    if (typeof value.thread_id !== 'string') return false;
    if (typeof value.run_id !== 'string') return false;
    if (typeof value.seq_id !== 'number') return false;
    if (value.protocol_version !== 'v1') return false;
    if (typeof value.source !== 'string') return false;
    if (!isRecord(value.data)) return false;
    return (
        type === 'lifecycle.status' ||
        type === 'content.delta' ||
        type === 'state.update' ||
        type === 'interrupt.request' ||
        type === 'agent.status' ||
        type === 'error'
    );
};
