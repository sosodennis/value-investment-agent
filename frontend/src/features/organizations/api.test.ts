import { afterEach, describe, expect, it, vi } from 'vitest';
import {
    changeMemberRole,
    listOrganizationMembers,
    listOrganizations,
    parseOrganization,
    parseOrganizationMember,
    OrganizationApiError,
} from './api';

afterEach(() => vi.unstubAllGlobals());

const organization = {
    organization_id: 'org-alpha',
    name: 'Alpha team',
    created_at: '2026-10-31T00:00:00Z',
    membership_id: 'membership-alpha',
    role: 'owner',
    status: 'active',
};

const member = {
    user_id: 'user-bob',
    email: 'bob@example.test',
    membership_id: 'membership-bob',
    organization_id: 'org-alpha',
    role: 'member',
    status: 'active',
    created_at: '2026-10-31T00:00:00Z',
    updated_at: '2026-10-31T00:00:00Z',
};

describe('organization API boundary', () => {
    it('maps organization and member wire fields into feature models', () => {
        expect(parseOrganization(organization)).toEqual({
            id: 'org-alpha',
            name: 'Alpha team',
            createdAt: '2026-10-31T00:00:00Z',
            membershipId: 'membership-alpha',
            role: 'owner',
            status: 'active',
        });
        expect(parseOrganizationMember(member)).toEqual({
            userId: 'user-bob',
            email: 'bob@example.test',
            membershipId: 'membership-bob',
            organizationId: 'org-alpha',
            role: 'member',
            status: 'active',
            createdAt: '2026-10-31T00:00:00Z',
            updatedAt: '2026-10-31T00:00:00Z',
        });
    });

    it('rejects malformed roles, statuses, and timestamps at the boundary', () => {
        expect(() => parseOrganization({ ...organization, role: 'viewer' })).toThrow(/role/);
        expect(() => parseOrganizationMember({ ...member, status: 'unknown' })).toThrow(/status/);
        expect(() => parseOrganization({ ...organization, created_at: 'not-a-date' })).toThrow(/date-time/);
        expect(() => parseOrganization({ ...organization, created_at: '2026-10-31' })).toThrow(/RFC3339/);
    });

    it('uses authenticated organization paths and sends mutation methods with CSRF headers', async () => {
        const fetchMock = vi.fn().mockImplementation((path: string) => {
            if (path === '/api/v1/organizations') return Promise.resolve(new Response(JSON.stringify([organization]), { status: 200 }));
            return Promise.resolve(new Response(JSON.stringify(member), { status: 200 }));
        });
        vi.stubGlobal('fetch', fetchMock);
        document.cookie = 'app_csrf=csrf-token; path=/';

        await listOrganizations();
        expect(fetchMock).toHaveBeenCalledWith('/api/v1/organizations', expect.objectContaining({ credentials: 'include' }));

        await changeMemberRole('org/alpha', 'user/bob', 'member');
        expect(fetchMock).toHaveBeenLastCalledWith(
            '/api/v1/organizations/org%2Falpha/members/user%2Fbob/role',
            expect.objectContaining({
                method: 'PATCH',
                credentials: 'include',
                body: JSON.stringify({ role: 'member' }),
            }),
        );
        const lastCall = fetchMock.mock.calls.at(-1);
        const headers = lastCall?.[1]?.headers;
        if (!(headers instanceof Headers)) throw new Error('organization requests must use Headers.');
        expect(headers.get('X-CSRF-Token')).toBe('csrf-token');
    });

    it('keeps member reads bounded to the selected organization route', async () => {
        const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify([member]), { status: 200 }));
        vi.stubGlobal('fetch', fetchMock);

        await listOrganizationMembers('org-alpha');

        expect(fetchMock).toHaveBeenCalledWith(
            '/api/v1/organizations/org-alpha/members',
            expect.objectContaining({ credentials: 'include' }),
        );
    });

    it('returns a typed error for denied responses without exposing response internals', async () => {
        vi.stubGlobal('fetch', vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ detail: 'permission_denied' }), { status: 403 }))));

        await expect(listOrganizations()).rejects.toBeInstanceOf(OrganizationApiError);
        await expect(listOrganizations()).rejects.toMatchObject({ status: 403, message: 'permission_denied' });
    });
});
