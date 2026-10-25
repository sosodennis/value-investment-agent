import type { components } from '@/types/generated/api-contract';
import { parseApiErrorMessage } from '@/types/protocol';
import { csrfHeaders } from '@/lib/auth-api';

const API_URL = process.env.NEXT_PUBLIC_LANGGRAPH_URL || 'http://localhost:8000';

export type LlmProviderKey =
    components['schemas']['src__llm_provider__interface__contracts__ProviderKeyResponse'];
export type LlmProviderKeyTestResult =
    components['schemas']['ProviderKeyTestResponse'];
export type LlmModelOption = components['schemas']['ModelOptionResponse'];
export type LlmSettings = components['schemas']['LlmSettingsResponse'];

export class LlmSettingsApiError extends Error {
    readonly status: number;

    constructor(message: string, status: number) {
        super(message);
        this.name = 'LlmSettingsApiError';
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

function parseLlmProviderKey(value: unknown, context: string): LlmProviderKey {
    const record = readRecord(value, context);
    return {
        id: readString(record.id, `${context}.id`),
        label: readString(record.label, `${context}.label`),
        suffix: readString(record.suffix, `${context}.suffix`),
        fingerprint: readString(record.fingerprint, `${context}.fingerprint`),
        created_at: readNullableString(record.created_at, `${context}.created_at`),
        cooldown_until: readNullableString(record.cooldown_until, `${context}.cooldown_until`),
        failure_count: typeof record.failure_count === 'number' ? record.failure_count : 0,
        last_error: readNullableString(record.last_error, `${context}.last_error`),
        last_tested_at: readNullableString(record.last_tested_at, `${context}.last_tested_at`),
        last_used_at: readNullableString(record.last_used_at, `${context}.last_used_at`),
        replacement_retire_at: readNullableString(
            record.replacement_retire_at,
            `${context}.replacement_retire_at`,
        ),
        status: typeof record.status === 'string' ? record.status : 'untested',
    };
}

function parseLlmProviderKeys(value: unknown): LlmProviderKey[] {
    if (!Array.isArray(value)) {
        throw new TypeError('llm_provider_keys must be an array.');
    }
    return value.map((entry, index) =>
        parseLlmProviderKey(entry, `llm_provider_keys[${index}]`)
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

function parseLlmProviderKeyTestResult(value: unknown): LlmProviderKeyTestResult {
    const record = readRecord(value, 'llm_provider_key_test');
    const status = record.status;
    if (
        status !== 'healthy' &&
        status !== 'invalid_key' &&
        status !== 'rate_limited' &&
        status !== 'unavailable'
    ) {
        throw new TypeError('llm_provider_key_test.status has an unsupported value.');
    }
    if (typeof record.passed !== 'boolean') {
        throw new TypeError('llm_provider_key_test.passed must be a boolean.');
    }
    return {
        id: readString(record.id, 'llm_provider_key_test.id'),
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
            ...csrfHeaders(),
            ...init?.headers,
        },
    });

    if (!response.ok) {
        let message = `LLM settings request failed (HTTP ${response.status}).`;
        try {
            const payload: unknown = await response.json();
            message = parseApiErrorMessage(payload) ?? message;
        } catch {}
        throw new LlmSettingsApiError(message, response.status);
    }

    if (response.status === 204) {
        return decode(undefined);
    }

    const payload: unknown = await response.json();
    return decode(payload);
}

export async function createLocalAdminSession(): Promise<void> {
    await request('/api/v1/auth/local-admin/session', () => undefined, {
        method: 'POST',
    });
}

export async function deleteLocalAdminSession(): Promise<void> {
    await request('/api/v1/auth/local-admin/session', () => undefined, {
        method: 'DELETE',
    });
}

export function listLlmProviderKeys(): Promise<LlmProviderKey[]> {
    return request('/api/v1/llm/provider-keys', parseLlmProviderKeys);
}

export function addLlmProviderKey(input: {
    label: string;
    api_key: string;
}): Promise<LlmProviderKey> {
    return request('/api/v1/llm/provider-keys', (value) =>
        parseLlmProviderKey(value, 'llm_provider_key'),
        {
            method: 'POST',
            body: JSON.stringify(input),
        }
    );
}

export function replaceLlmProviderKey(
    keyId: string,
    input: { label: string; api_key: string }
): Promise<LlmProviderKey> {
    return request(
        `/api/v1/llm/provider-keys/${encodeURIComponent(keyId)}/replace`,
        (value) => parseLlmProviderKey(value, 'llm_provider_key'),
        {
            method: 'POST',
            body: JSON.stringify(input),
        }
    );
}

export function testLlmProviderKey(
    keyId: string
): Promise<LlmProviderKeyTestResult> {
    return request(
        `/api/v1/llm/provider-keys/${encodeURIComponent(keyId)}/test`,
        parseLlmProviderKeyTestResult,
        { method: 'POST' }
    );
}

export function deleteLlmProviderKey(keyId: string): Promise<void> {
    return request(
        `/api/v1/llm/provider-keys/${encodeURIComponent(keyId)}`,
        () => undefined,
        { method: 'DELETE' }
    );
}

export function getLlmSettings(): Promise<LlmSettings> {
    return request('/api/v1/llm/settings', parseLlmSettings);
}

export function updateLlmSettings(selectedModel: string): Promise<LlmSettings> {
    return request('/api/v1/llm/settings', parseLlmSettings, {
        method: 'PUT',
        body: JSON.stringify({ selected_model: selectedModel }),
    });
}
