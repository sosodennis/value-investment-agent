import type { components } from '@/types/generated/api-contract';
import { csrfHeaders } from '@/lib/auth-api';
import { parseApiErrorMessage } from '@/types/protocol';

type OrganizationWire = components['schemas']['OrganizationResponse'];
type OrganizationMemberWire = components['schemas']['OrganizationMemberResponse'];

export type OrganizationRole = OrganizationWire['role'];
export type OrganizationStatus = OrganizationWire['status'];
export type OrganizationMemberStatus = OrganizationMemberWire['status'];

export type Organization = {
    id: string;
    name: string;
    createdAt: string;
    membershipId: string;
    role: OrganizationRole;
    status: OrganizationStatus;
};

export type OrganizationMember = {
    userId: string;
    email: string;
    membershipId: string;
    organizationId: string;
    role: OrganizationMemberWire['role'];
    status: OrganizationMemberStatus;
    createdAt: string;
    updatedAt: string;
};

export type OrganizationRoleChange = Extract<OrganizationRole, 'admin' | 'member'>;
export type OrganizationStatusChange = Extract<OrganizationMemberStatus, 'active' | 'suspended' | 'removed'>;

export class OrganizationApiError extends Error {
    readonly status: number;
    readonly code: string | null;

    constructor(message: string, status: number, code: string | null = null) {
        super(message);
        this.name = 'OrganizationApiError';
        this.status = status;
        this.code = code;
    }
}

type UnknownRecord = Record<string, unknown>;

function isRecord(value: unknown): value is UnknownRecord {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readRecord(value: unknown, context: string): UnknownRecord {
    if (!isRecord(value)) throw new TypeError(`${context} must be an object.`);
    return value;
}

function readString(value: unknown, context: string): string {
    if (typeof value !== 'string' || value.length === 0) {
        throw new TypeError(`${context} must be a non-empty string.`);
    }
    return value;
}

function readDateTime(value: unknown, context: string): string {
    const parsed = readString(value, context);
    const isRfc3339DateTime =
        /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(parsed);
    if (!isRfc3339DateTime || !Number.isFinite(Date.parse(parsed))) {
        throw new TypeError(`${context} must be a valid RFC3339 date-time.`);
    }
    return parsed;
}

function readRole(value: unknown, context: string): OrganizationRole {
    if (value === 'owner' || value === 'admin' || value === 'member') return value;
    throw new TypeError(`${context} has an unsupported role.`);
}

function readStatus(value: unknown, context: string): OrganizationStatus {
    if (value === 'pending' || value === 'active' || value === 'suspended' || value === 'removed') return value;
    throw new TypeError(`${context} has an unsupported status.`);
}

function readErrorCode(value: unknown): string | null {
    if (!isRecord(value) || !isRecord(value.detail)) return typeof value === 'string' ? value : null;
    return typeof value.detail.code === 'string' ? value.detail.code : null;
}

export function parseOrganization(value: unknown, context = 'organization'): Organization {
    const item = readRecord(value, context);
    return {
        id: readString(item.organization_id, `${context}.organization_id`),
        name: readString(item.name, `${context}.name`),
        createdAt: readDateTime(item.created_at, `${context}.created_at`),
        membershipId: readString(item.membership_id, `${context}.membership_id`),
        role: readRole(item.role, `${context}.role`),
        status: readStatus(item.status, `${context}.status`),
    };
}

export function parseOrganizations(value: unknown): Organization[] {
    if (!Array.isArray(value)) throw new TypeError('organizations must be an array.');
    return value.map((item, index) => parseOrganization(item, `organizations[${index}]`));
}

export function parseOrganizationMember(value: unknown, context = 'organization_member'): OrganizationMember {
    const item = readRecord(value, context);
    return {
        userId: readString(item.user_id, `${context}.user_id`),
        email: readString(item.email, `${context}.email`),
        membershipId: readString(item.membership_id, `${context}.membership_id`),
        organizationId: readString(item.organization_id, `${context}.organization_id`),
        role: readRole(item.role, `${context}.role`),
        status: readStatus(item.status, `${context}.status`),
        createdAt: readDateTime(item.created_at, `${context}.created_at`),
        updatedAt: readDateTime(item.updated_at, `${context}.updated_at`),
    };
}

export function parseOrganizationMembers(value: unknown): OrganizationMember[] {
    if (!Array.isArray(value)) throw new TypeError('organization_members must be an array.');
    return value.map((item, index) => parseOrganizationMember(item, `organization_members[${index}]`));
}

async function request<T>(path: string, decode: (payload: unknown) => T, init?: RequestInit): Promise<T> {
    const headers = new Headers(init?.headers);
    headers.set('Accept', 'application/json');
    if (init?.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
    for (const [name, value] of Object.entries(csrfHeaders())) headers.set(name, value);

    const response = await fetch(path, {
        ...init,
        credentials: 'include',
        headers,
    });

    if (!response.ok) {
        let message = `Organization request failed (HTTP ${response.status}).`;
        let code: string | null = null;
        try {
            const payload: unknown = await response.json();
            code = readErrorCode(payload);
            message = parseApiErrorMessage(payload) ?? code ?? message;
        } catch {
            // The HTTP status remains the only safe error detail for a non-JSON response.
        }
        throw new OrganizationApiError(message, response.status, code);
    }

    if (response.status === 204) return decode(undefined);
    return decode(await response.json());
}

function organizationPath(organizationId: string, suffix = ''): string {
    return `/api/v1/organizations/${encodeURIComponent(organizationId)}${suffix}`;
}

export function listOrganizations(): Promise<Organization[]> {
    return request('/api/v1/organizations', parseOrganizations);
}

export function createOrganization(name: string): Promise<Organization> {
    return request('/api/v1/organizations', (value) => parseOrganization(value, 'organization'), {
        method: 'POST',
        body: JSON.stringify({ name }),
    });
}

export function getOrganization(organizationId: string): Promise<Organization> {
    return request(organizationPath(organizationId), (value) => parseOrganization(value, 'organization'));
}

export function renameOrganization(organizationId: string, name: string): Promise<Organization> {
    return request(organizationPath(organizationId), (value) => parseOrganization(value, 'organization'), {
        method: 'PATCH',
        body: JSON.stringify({ name }),
    });
}

export function listOrganizationMembers(organizationId: string): Promise<OrganizationMember[]> {
    return request(organizationPath(organizationId, '/members'), parseOrganizationMembers);
}

export function changeMemberRole(
    organizationId: string,
    targetUserId: string,
    role: OrganizationRoleChange,
): Promise<OrganizationMember> {
    return request(
        organizationPath(organizationId, `/members/${encodeURIComponent(targetUserId)}/role`),
        (value) => parseOrganizationMember(value, 'organization_member'),
        { method: 'PATCH', body: JSON.stringify({ role }) },
    );
}

export function changeMemberStatus(
    organizationId: string,
    targetUserId: string,
    status: OrganizationStatusChange,
): Promise<OrganizationMember> {
    return request(
        organizationPath(organizationId, `/members/${encodeURIComponent(targetUserId)}/status`),
        (value) => parseOrganizationMember(value, 'organization_member'),
        { method: 'PATCH', body: JSON.stringify({ status }) },
    );
}

export function transferOwnership(organizationId: string, targetUserId: string): Promise<OrganizationMember> {
    return request(
        organizationPath(organizationId, '/ownership/transfer'),
        (value) => parseOrganizationMember(value, 'organization_member'),
        { method: 'POST', body: JSON.stringify({ target_user_id: targetUserId }) },
    );
}
