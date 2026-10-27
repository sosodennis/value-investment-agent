import { csrfHeaders } from '@/lib/auth-api';

const API_URL = process.env.NEXT_PUBLIC_LANGGRAPH_URL || 'http://localhost:8000';

export type SearchProvider = {
    provider: string;
    operations: ('web' | 'news')[];
    key_required: boolean;
    optional_fields: string[];
};

export type SearchKey = {
    id: string;
    provider: string;
    label: string;
    suffix: string;
    fingerprint: string;
    enabled: boolean;
    priority: number;
    status: 'active' | 'disabled' | 'cooldown' | 'invalid';
    failure_count: number;
    last_tested_at: string | null;
    last_used_at: string | null;
    cooldown_until: string | null;
};

export type SearchProviderSetting = {
    provider: string;
    enabled: boolean;
    priority: number;
    keys: SearchKey[];
};

export type SearchSettings = {
    providers: SearchProvider[];
    settings: { providers: SearchProviderSetting[] };
};

export type SearchKeyMutation = { id: string; provider: string; tested: boolean; active: boolean; suffix: string; fingerprint: string };

export class SearchSettingsApiError extends Error {
    constructor(message: string, readonly status: number) {
        super(message);
        this.name = 'SearchSettingsApiError';
    }
}

type RecordValue = Record<string, unknown>;
function isRecord(value: unknown): value is RecordValue {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}
function record(value: unknown, context: string): RecordValue {
    if (!isRecord(value)) throw new TypeError(`${context} must be an object.`);
    return value;
}
function string(value: unknown, context: string): string {
    if (typeof value !== 'string') throw new TypeError(`${context} must be a string.`);
    return value;
}
function bool(value: unknown, context: string): boolean {
    if (typeof value !== 'boolean') throw new TypeError(`${context} must be a boolean.`);
    return value;
}
function number(value: unknown, context: string): number {
    if (typeof value !== 'number' || !Number.isInteger(value) || value < 0) throw new TypeError(`${context} must be a non-negative integer.`);
    return value;
}
function array(value: unknown, context: string): unknown[] {
    if (!Array.isArray(value)) throw new TypeError(`${context} must be an array.`);
    return value;
}
function parseKey(value: unknown): SearchKey | null {
    if (value === null || value === undefined) return null;
    const item = record(value, 'search_key');
    const status = item.status;
    if (status !== 'active' && status !== 'disabled' && status !== 'cooldown' && status !== 'invalid') throw new TypeError('search_key.status is unsupported.');
    return {
        id: string(item.id, 'search_key.id'), provider: string(item.provider, 'search_key.provider'),
        label: string(item.label, 'search_key.label'), suffix: string(item.suffix, 'search_key.suffix'),
        fingerprint: string(item.fingerprint, 'search_key.fingerprint'), enabled: bool(item.enabled, 'search_key.enabled'),
        priority: number(item.priority, 'search_key.priority'), status, failure_count: number(item.failure_count ?? 0, 'search_key.failure_count'),
        last_tested_at: item.last_tested_at === null || item.last_tested_at === undefined ? null : string(item.last_tested_at, 'search_key.last_tested_at'),
        cooldown_until: item.cooldown_until === null || item.cooldown_until === undefined ? null : string(item.cooldown_until, 'search_key.cooldown_until'),
        last_used_at: item.last_used_at === null || item.last_used_at === undefined ? null : string(item.last_used_at, 'search_key.last_used_at'),
    };
}
function parseKeys(value: unknown): SearchKey[] {
    return array(value, 'search_provider_setting.keys').map((entry, index) => {
        const parsed = parseKey(entry);
        if (parsed === null) throw new TypeError(`search_provider_setting.keys[${index}] must be an object.`);
        return parsed;
    });
}
function parseSnapshot(value: unknown): SearchSettings {
    const root = record(value, 'search_settings');
    const settings = record(root.settings, 'search_settings.settings');
    return {
        providers: array(root.providers, 'search_settings.providers').map((value) => {
            const item = record(value, 'search_provider');
            return {
                provider: string(item.provider, 'search_provider.provider'),
                operations: array(item.operations, 'search_provider.operations').map((op) => {
                    if (op !== 'web' && op !== 'news') throw new TypeError('search_provider.operations contains an unsupported operation.');
                    return op;
                }),
                key_required: item.key_required === undefined ? true : bool(item.key_required, 'search_provider.key_required'),
                optional_fields: item.optional_fields === undefined ? [] : array(item.optional_fields, 'search_provider.optional_fields').map((field) => string(field, 'search_provider.optional_fields[]')),
            };
        }),
        settings: { providers: array(settings.providers, 'search_settings.settings.providers').map((value) => {
            const item = record(value, 'search_provider_setting');
            return {
                provider: string(item.provider, 'search_provider_setting.provider'), enabled: bool(item.enabled, 'search_provider_setting.enabled'),
                priority: number(item.priority, 'search_provider_setting.priority'),
                keys: item.keys === undefined ? [] : parseKeys(item.keys),
            };
        }) },
    };
}
function parseMutation(value: unknown): SearchKeyMutation {
    const item = record(value, 'search_key_mutation');
    return { id: string(item.id, 'search_key_mutation.id'), provider: string(item.provider, 'search_key_mutation.provider'), tested: bool(item.tested, 'search_key_mutation.tested'), active: bool(item.active, 'search_key_mutation.active'), suffix: string(item.suffix, 'search_key_mutation.suffix'), fingerprint: string(item.fingerprint, 'search_key_mutation.fingerprint') };
}
async function request<T>(path: string, decode: (value: unknown) => T, init?: RequestInit): Promise<T> {
    const response = await fetch(`${API_URL}${path}`, {
        ...init, credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...csrfHeaders(), ...init?.headers },
    });
    if (!response.ok) {
        let message = `Search settings request failed (HTTP ${response.status}).`;
        try {
            const payload = record(await response.json(), 'error');
            if (typeof payload.detail === 'string') message = payload.detail;
        } catch {}
        throw new SearchSettingsApiError(message, response.status);
    }
    if (response.status === 204) return decode(undefined);
    return decode(await response.json());
}

export const getSearchSettings = (): Promise<SearchSettings> => request('/api/v1/search/settings', parseSnapshot);
export const updateSearchSettings = (providers: { provider: string; enabled: boolean; priority: number }[]): Promise<SearchSettings> => request('/api/v1/search/settings', parseSnapshot, { method: 'PUT', body: JSON.stringify({ providers }) });
export const addSearchKey = (input: { provider: string; api_key: string; label: string }): Promise<SearchKeyMutation> => request('/api/v1/search/settings/keys', parseMutation, { method: 'POST', body: JSON.stringify(input) });
export const replaceSearchKey = (input: { provider: string; key_id: string; api_key: string; label: string }): Promise<SearchKeyMutation> => request('/api/v1/search/settings/keys', parseMutation, { method: 'PUT', body: JSON.stringify(input) });
export const deleteSearchKey = (keyId: string): Promise<void> => request(`/api/v1/search/settings/keys/${encodeURIComponent(keyId)}`, () => undefined, { method: 'DELETE' });
export const setSearchKeyEnabled = (keyId: string, enabled: boolean): Promise<SearchKeyMutation> => request(`/api/v1/search/settings/keys/${encodeURIComponent(keyId)}`, parseMutation, { method: 'PATCH', body: JSON.stringify({ enabled }) });
