import type { components } from '@/types/generated/api-contract';
import { parseApiErrorMessage } from '@/types/protocol';
import { csrfHeaders } from '@/lib/auth-api';

export type LlmProviderKey =
    components['schemas']['src__llm_provider__interface__contracts__ProviderKeyResponse'];
export type LlmProviderKeyTestResult =
    components['schemas']['ProviderKeyTestResponse'];
export type LlmProviderKeyImport =
    components['schemas']['ProviderKeyImportBatchResponse'];
export type LlmProviderKeyImportPreview =
    components['schemas']['ProviderKeyImportPreviewResponse'];
export type LlmProviderKeyImportItemStatus =
    components['schemas']['ProviderKeyImportItemResponse']['status'];
type LlmProviderKeyImportItem = NonNullable<LlmProviderKeyImport['items']>[number];
type LlmProviderKeyImportErrorCode = NonNullable<LlmProviderKeyImportItem['error_code']>;
export type LlmModelOption = components['schemas']['ModelOptionResponse'];
export type LlmSettings = components['schemas']['LlmSettingsResponse'];

export class LlmSettingsApiError extends Error {
    readonly status: number;
    readonly code: string | null;

    constructor(message: string, status: number, code: string | null = null) {
        super(message);
        this.name = 'LlmSettingsApiError';
        this.status = status;
        this.code = code;
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

function readNumber(value: unknown, context: string): number {
    if (typeof value !== 'number' || !Number.isFinite(value)) {
        throw new TypeError(`${context} must be a finite number.`);
    }
    return value;
}

function readBoolean(value: unknown, context: string): boolean {
    if (typeof value !== 'boolean') {
        throw new TypeError(`${context} must be a boolean.`);
    }
    return value;
}

function readImportItemStatus(value: unknown): LlmProviderKeyImportItemStatus {
    switch (value) {
        case 'queued':
        case 'validating':
        case 'retry_wait':
        case 'imported':
        case 'duplicate':
        case 'invalid':
        case 'unavailable':
        case 'expired':
            return value;
        default:
            throw new TypeError('llm_provider_key_import.status is unsupported.');
    }
}

function readImportBatchStatus(value: unknown): LlmProviderKeyImport['status'] {
    switch (value) {
        case 'queued':
        case 'processing':
        case 'completed':
        case 'completed_with_errors':
            return value;
        default:
            throw new TypeError('llm_provider_key_import.status is unsupported.');
    }
}

function readImportErrorCode(value: unknown): LlmProviderKeyImportErrorCode | null | undefined {
    if (value === null) return null;
    if (value === undefined) return undefined;
    switch (value) {
        case 'invalid_key':
            return 'invalid_key';
        case 'request_rejected':
            return 'request_rejected';
        case 'rate_limited':
            return 'rate_limited';
        case 'upstream_unavailable':
            return 'upstream_unavailable';
        case 'worker_attempts_exhausted':
            return 'worker_attempts_exhausted';
        case 'staging_unavailable':
            return 'staging_unavailable';
        case 'already_owned':
            return 'already_owned';
        case 'duplicate_in_batch':
            return 'duplicate_in_batch';
        case 'already_importing':
            return 'already_importing';
        case 'retry_expired':
            return 'retry_expired';
        default:
            throw new TypeError('llm_provider_key_import.error_code is unsupported.');
    }
}

function readPreviewIssueCode(
    value: unknown,
): LlmProviderKeyImportPreview['issues'][number]['code'] {
    switch (value) {
        case 'invalid_key_format':
            return 'invalid_key_format';
        case 'invalid_csv_row':
            return 'invalid_csv_row';
        case 'invalid_label':
            return 'invalid_label';
        default:
            throw new TypeError('llm_provider_key_import_preview.issues.code is unsupported.');
    }
}

function parseProviderKeyImport(value: unknown): LlmProviderKeyImport {
    const record = readRecord(value, 'llm_provider_key_import');
    const status = readImportBatchStatus(record.status);
    const rawItems = record.items ?? [];
    if (!Array.isArray(rawItems)) {
        throw new TypeError('llm_provider_key_import.items must be an array.');
    }
    const items = rawItems.map((entry, index) => {
        const item = readRecord(entry, `llm_provider_key_import.items[${index}]`);
        return {
            source_line: readNumber(item.source_line, `items[${index}].source_line`),
            label: readString(item.label, `items[${index}].label`),
            suffix: readNullableString(item.suffix, `items[${index}].suffix`),
            status: readImportItemStatus(item.status),
            error_code: readImportErrorCode(item.error_code),
            attempts: readNumber(item.attempts, `items[${index}].attempts`),
            retryable: readBoolean(item.retryable, `items[${index}].retryable`),
        };
    });
    return {
        id: readString(record.id, 'llm_provider_key_import.id'),
        status,
        total_count: readNumber(record.total_count, 'llm_provider_key_import.total_count'),
        processed_count: readNumber(record.processed_count, 'llm_provider_key_import.processed_count'),
        imported_count: readNumber(record.imported_count, 'llm_provider_key_import.imported_count'),
        duplicate_count: readNumber(record.duplicate_count, 'llm_provider_key_import.duplicate_count'),
        invalid_count: readNumber(record.invalid_count, 'llm_provider_key_import.invalid_count'),
        retryable_count: readNumber(record.retryable_count, 'llm_provider_key_import.retryable_count'),
        created_at: readString(record.created_at, 'llm_provider_key_import.created_at'),
        updated_at: readString(record.updated_at, 'llm_provider_key_import.updated_at'),
        items,
    };
}

function parseProviderKeyImportPreview(value: unknown): LlmProviderKeyImportPreview {
    const record = readRecord(value, 'llm_provider_key_import_preview');
    if (record.file_type !== 'txt' && record.file_type !== 'csv') {
        throw new TypeError('llm_provider_key_import_preview.file_type is unsupported.');
    }
    if (!Array.isArray(record.issues)) {
        throw new TypeError('llm_provider_key_import_preview.issues must be an array.');
    }
    const issues = record.issues.map((entry, index) => {
        const issue = readRecord(entry, `llm_provider_key_import_preview.issues[${index}]`);
        return {
            source_line: readNumber(issue.source_line, `issues[${index}].source_line`),
            code: readPreviewIssueCode(issue.code),
        };
    });
    return {
        file_type: record.file_type,
        row_count: readNumber(record.row_count, 'llm_provider_key_import_preview.row_count'),
        unique_count: readNumber(record.unique_count, 'llm_provider_key_import_preview.unique_count'),
        duplicate_count: readNumber(record.duplicate_count, 'llm_provider_key_import_preview.duplicate_count'),
        issues,
    };
}

function parseErrorCode(value: unknown): string | null {
    if (!isRecord(value) || !isRecord(value.detail)) return null;
    return typeof value.detail.code === 'string' ? value.detail.code : null;
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
    const isFormData =
        typeof FormData !== 'undefined' && init?.body instanceof FormData;
    const response = await fetch(path, {
        ...init,
        credentials: 'include',
        headers: {
            ...(!isFormData ? { 'Content-Type': 'application/json' } : {}),
            ...csrfHeaders(),
            ...init?.headers,
        },
    });

    if (!response.ok) {
        let message = `LLM settings request failed (HTTP ${response.status}).`;
        let code: string | null = null;
        try {
            const payload: unknown = await response.json();
            code = parseErrorCode(payload);
            message = parseApiErrorMessage(payload) ?? code ?? message;
        } catch {}
        throw new LlmSettingsApiError(message, response.status, code);
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

export function previewLlmProviderKeyImport(
    file: File,
): Promise<LlmProviderKeyImportPreview> {
    const body = new FormData();
    body.append('file', file);
    return request(
        '/api/v1/llm/provider-keys/imports/preview',
        parseProviderKeyImportPreview,
        { method: 'POST', body },
    );
}

export function createLlmProviderKeyImport(
    file: File,
    idempotencyKey: string,
): Promise<LlmProviderKeyImport> {
    const body = new FormData();
    body.append('file', file);
    return request(
        '/api/v1/llm/provider-keys/imports',
        parseProviderKeyImport,
        {
            method: 'POST',
            headers: { 'Idempotency-Key': idempotencyKey },
            body,
        },
    );
}

export async function listLlmProviderKeyImports(): Promise<LlmProviderKeyImport[]> {
    const result = await request(
        '/api/v1/llm/provider-keys/imports',
        (value) => {
            if (!Array.isArray(value)) {
                throw new TypeError('llm_provider_key_imports must be an array.');
            }
            return value.map(parseProviderKeyImport);
        },
    );
    return result;
}

export function getLlmProviderKeyImport(
    batchId: string,
): Promise<LlmProviderKeyImport> {
    return request(
        `/api/v1/llm/provider-keys/imports/${encodeURIComponent(batchId)}`,
        parseProviderKeyImport,
    );
}

export function retryLlmProviderKeyImport(
    batchId: string,
): Promise<LlmProviderKeyImport> {
    return request(
        `/api/v1/llm/provider-keys/imports/${encodeURIComponent(batchId)}/retry`,
        parseProviderKeyImport,
        { method: 'POST' },
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
