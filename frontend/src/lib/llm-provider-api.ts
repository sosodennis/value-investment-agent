import type { components } from '@/types/generated/api-contract';
import { parseApiErrorMessage } from '@/types/protocol';

const API_URL = process.env.NEXT_PUBLIC_LANGGRAPH_URL || 'http://localhost:8000';

export type OpenRouterKey = components['schemas']['OpenRouterKeyResponse'];
export type OpenRouterKeyTestResult =
    components['schemas']['OpenRouterKeyTestResponse'];
export type LlmModelOption = components['schemas']['LlmModelOptionResponse'];
export type LlmSettings = components['schemas']['LlmSettingsResponse'];

export class LlmProviderApiError extends Error {
    readonly status: number;

    constructor(message: string, status: number) {
        super(message);
        this.name = 'LlmProviderApiError';
        this.status = status;
    }
}

type UnknownRecord = Record<string, unknown>;

const isRecord = (value: unknown): value is UnknownRecord =>
    typeof value === 'object' && value !== null && !Array.isArray(value);

function readString(value: unknown, context: string): string {
    if (typeof value !== 'string') {
        throw new TypeError(`${context} must be a string.`);
    }
    return value;
}

function readNullableString(value: unknown, context: string): string | null | undefined {
    if (value === undefined || value === null) return value;
    return readString(value, context);
}

function readRecord(value: unknown, context: string): UnknownRecord {
    if (!isRecord(value)) {
        throw new TypeError(`${context} must be an object.`);
    }
    return value;
}

function parseOpenRouterKey(value: unknown, context: string): OpenRouterKey {
    const record = readRecord(value, context);
    return {
        id: readString(record.id, `${context}.id`),
        label: readString(record.label, `${context}.label`),
        suffix: readString(record.suffix, `${context}.suffix`),
        fingerprint: readString(record.fingerprint, `${context}.fingerprint`),
        created_at: readNullableString(record.created_at, `${context}.created_at`),
    };
}

function parseOpenRouterKeys(value: unknown): OpenRouterKey[] {
    if (!Array.isArray(value)) {
        throw new TypeError('openrouter_keys must be an array.');
    }
    return value.map((entry, index) =>
        parseOpenRouterKey(entry, `openrouter_keys[${index}]`)
    );
}

function parseModelOption(value: unknown, context: string): LlmModelOption {
    const record = readRecord(value, context);
    const contextLength = record.context_length;
    if (
        contextLength !== undefined &&
        contextLength !== null &&
        typeof contextLength !== 'number'
    ) {
        throw new TypeError(`${context}.context_length must be a number | null | undefined.`);
    }
    return {
        id: readString(record.id, `${context}.id`),
        name: readString(record.name, `${context}.name`),
        description: readNullableString(record.description, `${context}.description`),
        context_length: contextLength,
    };
}

function parseLlmSettings(value: unknown): LlmSettings {
    const record = readRecord(value, 'llm_settings');
    if (!Array.isArray(record.models)) {
        throw new TypeError('llm_settings.models must be an array.');
    }
    return {
        selected_model: readString(record.selected_model, 'llm_settings.selected_model'),
        default_model: readString(record.default_model, 'llm_settings.default_model'),
        models: record.models.map((entry, index) =>
            parseModelOption(entry, `llm_settings.models[${index}]`)
        ),
    };
}

function parseOpenRouterKeyTestResult(value: unknown): OpenRouterKeyTestResult {
    const record = readRecord(value, 'openrouter_key_test');
    const status = record.status;
    if (
        status !== 'healthy' &&
        status !== 'invalid_key' &&
        status !== 'rate_limited' &&
        status !== 'unavailable'
    ) {
        throw new TypeError('openrouter_key_test.status has an unsupported value.');
    }
    if (typeof record.passed !== 'boolean') {
        throw new TypeError('openrouter_key_test.passed must be a boolean.');
    }
    return {
        id: readString(record.id, 'openrouter_key_test.id'),
        passed: record.passed,
        status,
    };
}

async function request<T>(
    path: string,
    decode: (payload: unknown) => T,
    init?: RequestInit
): Promise<T> {
    const response = await fetch(`${API_URL}${path}`, {
        ...init,
        credentials: 'include',
        headers: {
            'Content-Type': 'application/json',
            ...init?.headers,
        },
    });

    if (!response.ok) {
        let message = `LLM provider request failed (HTTP ${response.status}).`;
        try {
            const payload: unknown = await response.json();
            message = parseApiErrorMessage(payload) ?? message;
        } catch {}
        throw new LlmProviderApiError(message, response.status);
    }

    if (response.status === 204) {
        return decode(undefined);
    }

    const payload: unknown = await response.json();
    return decode(payload);
}

export async function createLocalAdminSession(): Promise<void> {
    await request('/api/auth/local-admin/session', () => undefined, {
        method: 'POST',
    });
}

export async function deleteLocalAdminSession(): Promise<void> {
    await request('/api/auth/local-admin/session', () => undefined, {
        method: 'DELETE',
    });
}

export function listOpenRouterKeys(): Promise<OpenRouterKey[]> {
    return request('/api/settings/openrouter-keys', parseOpenRouterKeys);
}

export function addOpenRouterKey(input: {
    label: string;
    api_key: string;
}): Promise<OpenRouterKey> {
    return request('/api/settings/openrouter-keys', (value) =>
        parseOpenRouterKey(value, 'openrouter_key'),
        {
            method: 'POST',
            body: JSON.stringify(input),
        }
    );
}

export function testOpenRouterKey(
    keyId: string
): Promise<OpenRouterKeyTestResult> {
    return request(
        `/api/settings/openrouter-keys/${encodeURIComponent(keyId)}/test`,
        parseOpenRouterKeyTestResult,
        { method: 'POST' }
    );
}

export function deleteOpenRouterKey(keyId: string): Promise<void> {
    return request(
        `/api/settings/openrouter-keys/${encodeURIComponent(keyId)}`,
        () => undefined,
        { method: 'DELETE' }
    );
}

export function getLlmSettings(): Promise<LlmSettings> {
    return request('/api/settings/llm', parseLlmSettings);
}

export function updateLlmSettings(selectedModel: string): Promise<LlmSettings> {
    return request('/api/settings/llm', parseLlmSettings, {
        method: 'PUT',
        body: JSON.stringify({ selected_model: selectedModel }),
    });
}
