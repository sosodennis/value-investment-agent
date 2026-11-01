import { csrfHeaders } from '@/lib/auth-api';
import { parseApiErrorMessage } from '@/types/protocol';

export type NotificationStatus = 'pending' | 'accepted' | 'declined' | 'expired' | 'revoked';

export type NotificationItem = {
    notificationId: string;
    eventId: string;
    type: string;
    organizationId: string | null;
    payload: Record<string, unknown>;
    action: { actionType: string; actionRef: string } | null;
    readAt: string | null;
    createdAt: string;
    expiresAt: string | null;
};

export class NotificationApiError extends Error {
    readonly status: number;
    readonly code: string | null;

    constructor(message: string, status: number, code: string | null = null) {
        super(message);
        this.name = 'NotificationApiError';
        this.status = status;
        this.code = code;
    }
}

type UnknownRecord = Record<string, unknown>;

function isRecord(value: unknown): value is UnknownRecord {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readString(value: unknown, context: string): string {
    if (typeof value !== 'string' || value.length === 0) throw new TypeError(`${context} must be a non-empty string.`);
    return value;
}

function readNullableString(value: unknown, context: string): string | null {
    if (value === null) return null;
    return readString(value, context);
}

function readPayload(value: unknown): Record<string, unknown> {
    if (!isRecord(value)) throw new TypeError('notification payload must be an object.');
    return value;
}

function parseItem(value: unknown, context = 'notification'): NotificationItem {
    if (!isRecord(value)) throw new TypeError(`${context} must be an object.`);
    const action = value.action;
    return {
        notificationId: readString(value.notification_id, `${context}.notification_id`),
        eventId: readString(value.event_id, `${context}.event_id`),
        type: readString(value.type, `${context}.type`),
        organizationId: readNullableString(value.organization_id, `${context}.organization_id`),
        payload: readPayload(value.payload),
        action:
            action === null
                ? null
                : isRecord(action)
                  ? {
                        actionType: readString(action.action_type, `${context}.action.action_type`),
                        actionRef: readString(action.action_ref, `${context}.action.action_ref`),
                    }
                  : (() => {
                        throw new TypeError(`${context}.action must be an object or null.`);
                    })(),
        readAt: readNullableString(value.read_at, `${context}.read_at`),
        createdAt: readString(value.created_at, `${context}.created_at`),
        expiresAt: readNullableString(value.expires_at, `${context}.expires_at`),
    };
}

function errorCode(value: unknown): string | null {
    if (!isRecord(value)) return null;
    return typeof value.detail === 'string' ? value.detail : null;
}

async function request<T>(path: string, decode: (value: unknown) => T, init?: RequestInit): Promise<T> {
    const headers = new Headers(init?.headers);
    headers.set('Accept', 'application/json');
    if (init?.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
    for (const [name, value] of Object.entries(csrfHeaders())) headers.set(name, value);
    const response = await fetch(path, { ...init, credentials: 'include', headers });
    if (!response.ok) {
        let message = `Notification request failed (HTTP ${response.status}).`;
        let code: string | null = null;
        try {
            const payload: unknown = await response.json();
            code = errorCode(payload);
            message = parseApiErrorMessage(payload) ?? code ?? message;
        } catch {
            // Keep the status as the only detail for non-JSON failures.
        }
        throw new NotificationApiError(message, response.status, code);
    }
    return decode(await response.json());
}

export async function listNotifications(): Promise<{ items: NotificationItem[]; unreadCount: number }> {
    return request('/api/v1/notifications', (value) => {
        if (!isRecord(value) || !Array.isArray(value.items) || typeof value.unread_count !== 'number') {
            throw new TypeError('notification list has an invalid shape.');
        }
        return {
            items: value.items.map((item, index) => parseItem(item, `notifications[${index}]`)),
            unreadCount: value.unread_count,
        };
    });
}

export function markNotificationRead(notificationId: string): Promise<NotificationItem> {
    return request(`/api/v1/notifications/${encodeURIComponent(notificationId)}/read`, (value) => parseItem(value), {
        method: 'PATCH',
    });
}

function invitationAction(organizationId: string, invitationId: string, operation: 'accept' | 'decline', idempotencyKey = `${operation}-${invitationId}-${crypto.randomUUID()}`): Promise<unknown> {
    return request(
        `/api/v1/organizations/${encodeURIComponent(organizationId)}/invitations/${encodeURIComponent(invitationId)}/${operation}`,
        (value) => value,
        { method: 'POST', headers: { 'Idempotency-Key': idempotencyKey } },
    );
}

export function acceptInvitation(organizationId: string, invitationId: string, idempotencyKey?: string): Promise<unknown> {
    return invitationAction(organizationId, invitationId, 'accept', idempotencyKey);
}

export function declineInvitation(organizationId: string, invitationId: string, idempotencyKey?: string): Promise<unknown> {
    return invitationAction(organizationId, invitationId, 'decline', idempotencyKey);
}
