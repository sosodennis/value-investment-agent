import type { components } from '@/types/generated/api-contract';
import { csrfHeaders } from '../auth-api';

type ClientDebugBatchRequest = components['schemas']['ClientDebugBatchRequest'];
type ClientDebugEvent = components['schemas']['ClientDebugEvent'];
type ClientDebugContext = components['schemas']['ClientDebugContext'];

export type ClientDebugJsonValue =
    | string
    | number
    | boolean
    | null
    | ClientDebugJsonValue[]
    | { [key: string]: ClientDebugJsonValue };

export type ClientDebugDetails = Record<string, ClientDebugJsonValue>;

export type ClientDebugEmitOptions = {
    component?: string;
    requestId?: string;
    traceparent?: string;
    threadId?: string;
    runId?: string;
};

const EVENT_NAME = /^[a-z][a-z0-9_.-]{1,95}$/;
const TRACEPARENT = /^[0-9a-f]{2}-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$/;
const SENSITIVE_KEY = /(authorization|cookie|password|secret|token|credential|api[_-]?key|private[_-]?key)/i;
const FORBIDDEN_KEY = /(outerhtml|innerhtml|serialized[_-]?dom|dom[_-]?tree|input[_-]?value|request[_-]?url|response[_-]?url|url|href|query|fragment|request[_-]?body|response[_-]?body|body)/i;
const SENSITIVE_VALUE_PATTERNS = [
    /\bbearer\s+[A-Za-z0-9._~+/=-]{12,}\b/i,
    /\bsk-(?:or-v1-)?[A-Za-z0-9_-]{12,}\b/,
    /\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b/,
    /(?:https?:\/\/|www\.)[^\s"'<>]+/i,
    /(?:^|[?&#])[A-Za-z0-9_.~-]{1,64}=[^\s&#]*/,
    /\b(?:session|csrf|auth|access|refresh)[_-]?(?:token)?\s*[:=]\s*[^\s,;]+/i,
];
const REDACTED = '[REDACTED]';
const MAX_DEPTH = 6;
const MAX_STRING_LENGTH = 4096;
const MAX_ARRAY_ITEMS = 100;
const MAX_DETAILS_BYTES = 32 * 1024;
const MAX_QUEUE_SIZE = 200;
const MAX_BATCH_SIZE = 20;
const MAX_KEEPALIVE_BATCH_BYTES = 48 * 1024;
const MAX_BATCH_BYTES = 192 * 1024;
const MAX_RETRY_ATTEMPTS = 3;
const FLUSH_DELAY_MS = 250;

const enabled = process.env.NEXT_PUBLIC_ENABLE_CLIENT_DEBUG_CAPTURE === 'true';
type QueuedEvent = {
    event: ClientDebugEvent;
    attempts: number;
};

const queue: QueuedEvent[] = [];
const captureId = enabled && typeof window !== 'undefined' ? createId() : null;
const captureStartedAt = typeof performance === 'undefined' ? 0 : performance.now();
let sequence = 0;
let timer: number | null = null;
let inFlight: Promise<void> | null = null;
let inFlightBatch: QueuedEvent[] | null = null;
let unloading = false;

function createId(): string {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
        return crypto.randomUUID();
    }

    if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') {
        const bytes = new Uint8Array(16);
        crypto.getRandomValues(bytes);
        return Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('');
    }

    return Date.now().toString(16) + '-' + Math.random().toString(16).slice(2);
}

function sanitizeValue(value: unknown, key: string | null, depth: number): ClientDebugJsonValue | undefined {
    if (depth > MAX_DEPTH) return undefined;
    if (key && FORBIDDEN_KEY.test(key)) return undefined;
    if (key && SENSITIVE_KEY.test(key)) return REDACTED;

    if (value === null || typeof value === 'boolean' || typeof value === 'string') {
        if (typeof value === 'string') {
            if (value.length > MAX_STRING_LENGTH) return undefined;
            if (SENSITIVE_VALUE_PATTERNS.some((pattern) => pattern.test(value))) return REDACTED;
        }
        return value;
    }

    if (typeof value === 'number') {
        return Number.isFinite(value) ? value : undefined;
    }

    if (Array.isArray(value)) {
        if (value.length > MAX_ARRAY_ITEMS) return undefined;
        const result: ClientDebugJsonValue[] = [];
        for (const item of value) {
            const sanitized = sanitizeValue(item, null, depth + 1);
            if (sanitized !== undefined) result.push(sanitized);
        }
        return result;
    }

    if (typeof value === 'object') {
        const result: Record<string, ClientDebugJsonValue> = {};
        for (const [nestedKey, nestedValue] of Object.entries(value)) {
            const sanitized = sanitizeValue(nestedValue, nestedKey, depth + 1);
            if (sanitized !== undefined) result[nestedKey] = sanitized;
        }
        return result;
    }

    return undefined;
}

function sanitizeDetails(details: ClientDebugDetails): ClientDebugDetails {
    const sanitized = sanitizeValue(details, null, 0);
    if (!sanitized || Array.isArray(sanitized) || typeof sanitized !== 'object') return {};
    if (new TextEncoder().encode(JSON.stringify(sanitized)).byteLength > MAX_DETAILS_BYTES) {
        return {};
    }
    return sanitized;
}

function context(options: ClientDebugEmitOptions): ClientDebugContext {
    const viewport = {
        width: window.innerWidth,
        height: window.innerHeight,
        dpr: window.devicePixelRatio || 1,
    };

    return {
        route: window.location.pathname,
        viewport,
        scroll: { x: window.scrollX, y: window.scrollY },
        visibility_state: document.visibilityState,
        reduced_motion: window.matchMedia('(prefers-reduced-motion: reduce)').matches,
        ...(options.requestId ? { request_id: options.requestId } : {}),
        ...(options.traceparent && TRACEPARENT.test(options.traceparent)
            ? { traceparent: options.traceparent }
            : {}),
        ...(options.threadId ? { thread_id: options.threadId } : {}),
        ...(options.runId ? { run_id: options.runId } : {}),
    };
}

function schedule(): void {
    if (timer !== null || typeof window === 'undefined') return;
    timer = window.setTimeout(() => {
        timer = null;
        void flushNow(false);
    }, FLUSH_DELAY_MS);
}

class ClientDebugTransportError extends Error {
    readonly status: number | null;

    constructor(status: number | null) {
        super('Client debug capture transport failed.');
        this.name = 'ClientDebugTransportError';
        this.status = status;
    }
}

async function send(batch: QueuedEvent[], keepalive: boolean): Promise<void> {
    if (!captureId) return;

    const payload: ClientDebugBatchRequest = {
        schema_version: 'client_debug.v1',
        capture_id: captureId,
        events: batch.map(({ event }) => event),
    };
    const headers = new Headers({
        Accept: 'application/json',
        'Content-Type': 'application/json',
        ...csrfHeaders(),
    });
    const response = await fetch('/api/v1/client-debug/events', {
        method: 'POST',
        credentials: 'include',
        headers,
        body: JSON.stringify(payload),
        keepalive,
    });
    if (!response.ok) {
        throw new ClientDebugTransportError(response.status);
    }
}

function batchBytes(batch: QueuedEvent[]): number {
    return new TextEncoder().encode(
        JSON.stringify({
            schema_version: 'client_debug.v1',
            capture_id: captureId,
            events: batch.map(({ event }) => event),
        }),
    ).byteLength;
}

function flushOnPageHide(): void {
    unloading = true;
    if (timer !== null) {
        window.clearTimeout(timer);
        timer = null;
    }

    const pending = [...(inFlightBatch ?? []), ...queue];
    queue.length = 0;
    const terminalBatch: QueuedEvent[] = [];
    while (terminalBatch.length < 50 && pending.length > 0) {
        const candidate = [...terminalBatch, pending[0]];
        if (batchBytes(candidate) > MAX_KEEPALIVE_BATCH_BYTES) break;
        const next = pending.shift();
        if (!next) break;
        terminalBatch.push(next);
    }
    if (terminalBatch.length > 0) {
        void send(terminalBatch, true).catch(() => undefined);
    }
}

async function flushNow(keepalive: boolean): Promise<void> {
    if (!enabled || !captureId || unloading || queue.length === 0) return;
    if (inFlight) return inFlight;

    inFlight = (async () => {
        do {
            const batch: QueuedEvent[] = [];
            const maxBytes = keepalive ? MAX_KEEPALIVE_BATCH_BYTES : MAX_BATCH_BYTES;
            while (batch.length < MAX_BATCH_SIZE && queue.length > 0) {
                if (batchBytes([...batch, queue[0]]) > maxBytes && batch.length > 0) break;
                const next = queue.shift();
                if (!next) break;
                batch.push(next);
            }
            inFlightBatch = batch;
            try {
                await send(batch, keepalive);
            } catch (error) {
                const transportError = error instanceof ClientDebugTransportError ? error : null;
                const retryable =
                    transportError === null ||
                    transportError.status === 429 ||
                    (transportError.status !== null && transportError.status >= 500);
                const retryBatch = retryable && !unloading
                    ? batch
                          .filter(({ attempts }) => attempts < MAX_RETRY_ATTEMPTS)
                          .map(({ event, attempts }) => ({ event, attempts: attempts + 1 }))
                    : [];
                queue.unshift(...retryBatch);
                if (queue.length > MAX_QUEUE_SIZE) queue.splice(MAX_QUEUE_SIZE);
                break;
            } finally {
                inFlightBatch = null;
            }
        } while (queue.length > 0 && keepalive && !unloading);
    })().finally(() => {
        inFlight = null;
        if (queue.length > 0 && !unloading) {
            schedule();
        }
    });
    return inFlight;
}

if (enabled && typeof window !== 'undefined') {
    window.addEventListener('pagehide', flushOnPageHide);
}

export const debugCapture = {
    get isEnabled(): boolean {
        return enabled;
    },

    get captureId(): string | null {
        return captureId;
    },

    emit(name: string, details: ClientDebugDetails, options: ClientDebugEmitOptions = {}): void {
        if (!enabled || !captureId || !EVENT_NAME.test(name)) return;
        if (queue.length >= MAX_QUEUE_SIZE) return;

        sequence += 1;
        const event: ClientDebugEvent = {
            event_id: createId(),
            sequence,
            occurred_at: new Date().toISOString(),
            elapsed_ms: Math.max(0, performance.now() - captureStartedAt),
            name,
            severity: 'debug',
            context: context(options),
            details: sanitizeDetails(details),
            ...(options.component ? { component: options.component } : {}),
        };
        queue.push({ event, attempts: 0 });
        if (queue.length >= MAX_BATCH_SIZE) {
            void flushNow(false);
        } else {
            schedule();
        }
    },

    flush(): Promise<void> {
        return flushNow(false);
    },
};
