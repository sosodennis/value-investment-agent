import type { components } from '@/types/generated/api-contract';
import { parseApiErrorMessage } from '@/types/protocol';

const API_URL = (
    process.env.NEXT_PUBLIC_LANGGRAPH_URL || 'http://localhost:8000'
).replace(/\/+$/, '');
const CSRF_COOKIE_NAME = 'app_csrf';
const CSRF_HEADER_NAME = 'X-CSRF-Token';

export type AuthUser =
    components['schemas']['Principal'];

export class AuthApiError extends Error {
    readonly status: number;

    constructor(message: string, status: number) {
        super(message);
        this.name = 'AuthApiError';
        this.status = status;
    }
}

type UnknownRecord = Record<string, unknown>;

const isRecord = (value: unknown): value is UnknownRecord =>
    typeof value === 'object' && value !== null && !Array.isArray(value);

function readCsrfCookie(): string | null {
    if (typeof document === 'undefined') return null;

    const cookiePrefix = `${CSRF_COOKIE_NAME}=`;
    const cookie = document.cookie
        .split(';')
        .map((entry) => entry.trim())
        .find((entry) => entry.startsWith(cookiePrefix));
    if (!cookie) return null;

    return decodeURIComponent(cookie.slice(cookiePrefix.length));
}

export function csrfHeaders(): Record<string, string> {
    const csrfToken = readCsrfCookie();
    return csrfToken ? { [CSRF_HEADER_NAME]: csrfToken } : {};
}

function parseAuthUser(value: unknown): AuthUser {
    if (!isRecord(value)) {
        throw new TypeError('auth response must be an object.');
    }
    if (
        value.auth_type !== 'session' ||
        value.role !== 'user' ||
        typeof value.email !== 'string' ||
        typeof value.subject !== 'string' ||
        typeof value.user_id !== 'string'
    ) {
        throw new TypeError('auth response has an invalid principal.');
    }

    return {
        auth_type: 'session',
        email: value.email,
        role: 'user',
        subject: value.subject,
        user_id: value.user_id,
    };
}

async function readErrorMessage(response: Response): Promise<string> {
    try {
        const payload: unknown = await response.json();
        return (
            parseApiErrorMessage(payload) ||
            `Authentication request failed (HTTP ${response.status}).`
        );
    } catch {
        return `Authentication request failed (HTTP ${response.status}).`;
    }
}

async function request<T>(
    path: string,
    decode: (payload: unknown) => T,
    init?: RequestInit,
): Promise<T> {
    const headers = new Headers(init?.headers);
    headers.set('Accept', 'application/json');
    if (init?.body && !headers.has('Content-Type')) {
        headers.set('Content-Type', 'application/json');
    }
    for (const [name, value] of Object.entries(csrfHeaders())) {
        headers.set(name, value);
    }

    const response = await fetch(`${API_URL}${path}`, {
        ...init,
        credentials: 'include',
        headers,
    });

    if (!response.ok) {
        throw new AuthApiError(await readErrorMessage(response), response.status);
    }

    if (response.status === 204) {
        return decode(undefined);
    }

    return decode(await response.json());
}

export function getCurrentUser(): Promise<AuthUser> {
    return request('/api/auth/me', parseAuthUser);
}

export function login(email: string, password: string): Promise<AuthUser> {
    return request('/api/auth/login', parseAuthUser, {
        method: 'POST',
        body: JSON.stringify({ email, password }),
    });
}

export function register(email: string, password: string): Promise<AuthUser> {
    return request('/api/auth/register', parseAuthUser, {
        method: 'POST',
        body: JSON.stringify({ email, password }),
    });
}

export function logout(): Promise<void> {
    return request('/api/auth/logout', () => undefined, { method: 'POST' });
}
