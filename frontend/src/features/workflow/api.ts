import type { components, operations } from '@/types/generated/api-contract';
import { csrfHeaders } from '@/lib/auth-api';
import {
    parseSseWorkflowEventFrame,
    parseWorkflowActivitySnapshot,
    type WorkflowEvent,
    type WorkflowActivitySnapshot,
} from './workflow-activity';

const API_URL = (process.env.NEXT_PUBLIC_LANGGRAPH_URL || 'http://localhost:8000').replace(/\/+$/, '');

type StartRunRequest = components['schemas']['RunRequest'];
type StartRunResponse = operations['start_run_api_v1_threads__thread_id__runs_post']['responses'][202]['content']['application/json'];
type ResumeRunRequest = components['schemas']['ResumeRequest'];
type ResumeRunResponse = operations['resume_run_api_v1_threads__thread_id__runs__run_id__resume_post']['responses'][202]['content']['application/json'];

export interface WorkflowRun {
    thread_id: string;
    run_id: string;
    status: string;
}

async function readError(response: Response, operation: string): Promise<Error> {
    let detail = `HTTP ${response.status}`;
    try {
        const payload: unknown = await response.json();
        if (typeof payload === 'object' && payload !== null && 'detail' in payload) {
            const candidate = payload.detail;
            if (typeof candidate === 'string') detail = candidate;
            else if (typeof candidate === 'object' && candidate !== null && 'code' in candidate && typeof candidate.code === 'string') detail = candidate.code;
        }
    } catch { /* The status remains useful when the body is not JSON. */ }
    return new Error(`${operation} failed (${detail}).`);
}

function parseRunResponse(value: unknown): WorkflowRun {
    if (typeof value !== 'object' || value === null || Array.isArray(value)) throw new TypeError('run response must be an object.');
    const record = value as Record<string, unknown>;
    if (typeof record.thread_id !== 'string' || !record.thread_id || typeof record.run_id !== 'string' || !record.run_id || (record.status !== undefined && typeof record.status !== 'string')) throw new TypeError('run response has invalid identifiers or status.');
    return { thread_id: record.thread_id, run_id: record.run_id, status: typeof record.status === 'string' ? record.status : 'started' } satisfies StartRunResponse;
}

export async function getActivitySnapshot(
    threadId: string,
    options: { runId?: string; signal?: AbortSignal } = {},
): Promise<WorkflowActivitySnapshot> {
    const url = new URL(`${API_URL}/api/v1/threads/${encodeURIComponent(threadId)}/activities`);
    if (options.runId) url.searchParams.set('run_id', options.runId);
    const response = await fetch(url.toString(), { credentials: 'include', signal: options.signal });
    if (!response.ok) throw await readError(response, 'Activity snapshot');
    const payload: unknown = await response.json();
    const snapshot = parseWorkflowActivitySnapshot(payload);
    if (snapshot.thread_id !== threadId) throw new TypeError('activity snapshot thread identity mismatch.');
    if (options.runId && snapshot.run_id !== options.runId) throw new TypeError('activity snapshot run identity mismatch.');
    return snapshot;
}

export async function startWorkflowRun(threadId: string, request: StartRunRequest): Promise<WorkflowRun> {
    const response = await fetch(`${API_URL}/api/v1/threads/${encodeURIComponent(threadId)}/runs`, {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json', ...csrfHeaders() }, body: JSON.stringify(request),
    });
    if (!response.ok) throw await readError(response, 'Start run');
    const run = parseRunResponse(await response.json());
    if (run.thread_id !== threadId) throw new TypeError('run response thread identity mismatch.');
    return run;
}

export async function cancelWorkflowRun(threadId: string, runId: string): Promise<void> {
    const response = await fetch(`${API_URL}/api/v1/threads/${encodeURIComponent(threadId)}/runs/${encodeURIComponent(runId)}/cancel`, {
        method: 'POST', credentials: 'include', headers: csrfHeaders(),
    });
    if (!response.ok) throw await readError(response, 'Cancel run');
}

export async function resumeWorkflowRun(
    threadId: string,
    runId: string,
    request: ResumeRunRequest,
): Promise<WorkflowRun> {
    const response = await fetch(`${API_URL}/api/v1/threads/${encodeURIComponent(threadId)}/runs/${encodeURIComponent(runId)}/resume`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...csrfHeaders() },
        body: JSON.stringify(request),
    });
    if (!response.ok) throw await readError(response, 'Resume run');
    const run = parseRunResponse(await response.json()) as ResumeRunResponse;
    if (run.thread_id !== threadId || run.run_id !== runId) throw new TypeError('resume response run identity mismatch.');
    return run;
}

export async function consumeWorkflowEvents(
    threadId: string,
    afterSeq: number,
    signal: AbortSignal,
    onEvent: (event: WorkflowEvent) => boolean | void,
    runId?: string,
): Promise<void> {
    const url = new URL(`${API_URL}/api/v1/threads/${encodeURIComponent(threadId)}/events`);
    url.searchParams.set('after_seq', String(afterSeq));
    if (runId) url.searchParams.set('run_id', runId);
    const response = await fetch(url.toString(), { credentials: 'include', signal, headers: { Accept: 'text/event-stream' } });
    if (!response.ok) throw await readError(response, 'Workflow event stream');
    const reader = response.body?.getReader();
    if (!reader) throw new Error('Workflow event stream has no response body.');
    const decoder = new TextDecoder();
    let buffer = '';
    try {
        while (!signal.aborted) {
            const { done, value } = await reader.read();
            if (done) return;
            buffer += decoder.decode(value, { stream: true });
            const frames = buffer.split(/\r?\n\r?\n/);
            buffer = frames.pop() ?? '';
            for (const frame of frames) {
                const lines = frame.split(/\r?\n/);
                const eventName = lines.find((line) => line.startsWith('event:'))?.slice(6).trim();
                if (!eventName || eventName === 'heartbeat' || lines.every((line) => line.startsWith(':'))) continue;
                if (eventName !== 'workflow.activity' && eventName !== 'workflow.interaction' && eventName !== 'workflow.agent_output') {
                    throw new TypeError(`Unsupported SSE event ${eventName}.`);
                }
                const data = lines.filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trimStart()).join('\n');
                const event = parseSseWorkflowEventFrame(data, eventName);
                if (event.thread_id !== threadId) throw new TypeError('workflow event thread identity mismatch.');
                if (onEvent(event) === true) return;
            }
        }
    } finally {
        await reader.cancel().catch(() => undefined);
        reader.releaseLock();
    }
}
