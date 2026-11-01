import { afterEach, describe, expect, it, vi } from 'vitest';
import { parseInvitation } from '@/features/organizations/api';
import { acceptInvitation, listNotifications, NotificationApiError } from './api';

afterEach(() => vi.unstubAllGlobals());

const invitation = {
    invitation_id: 'invitation-1',
    organization_id: 'org-alpha',
    organization_name: 'Alpha team',
    inviter_user_id: 'user-owner',
    inviter_display_name: 'Owner',
    recipient_user_id: 'user-recipient',
    recipient_display_name: 'Recipient',
    requested_role: 'member',
    status: 'pending',
    created_at: '2026-10-31T00:00:00Z',
    updated_at: '2026-10-31T00:00:00Z',
    expires_at: '2026-11-07T00:00:00Z',
    revision: 1,
};

describe('notification API boundary', () => {
    it('parses invitation state and rejects unsafe enum values', async () => {
        expect(parseInvitation(invitation)).toMatchObject({
            invitationId: 'invitation-1',
            requestedRole: 'member',
            status: 'pending',
        });
        expect(() => parseInvitation({ ...invitation, status: 'owner' })).toThrow(/status/);
    });

    it('scopes inbox reads and invitation actions to authenticated requests', async () => {
        const fetchMock = vi.fn()
            .mockResolvedValueOnce(
                new Response(
                    JSON.stringify({
                        items: [
                            {
                                notification_id: 'inbox-1',
                                event_id: 'event-1',
                                type: 'organization.invitation',
                                organization_id: 'org-alpha',
                                payload: { status: 'pending' },
                                action: { action_type: 'organization.invitation', action_ref: 'invitation-1' },
                                read_at: null,
                                created_at: '2026-10-31T00:00:00Z',
                                expires_at: '2026-11-07T00:00:00Z',
                            },
                        ],
                        unread_count: 1,
                    }),
                    { status: 200 },
                ),
            )
            .mockResolvedValueOnce(new Response(JSON.stringify(invitation), { status: 200 }));
        vi.stubGlobal('fetch', fetchMock);
        document.cookie = 'app_csrf=csrf-token; path=/';

        await expect(listNotifications()).resolves.toMatchObject({ unreadCount: 1 });
        await acceptInvitation('org/alpha', 'invitation/1');

        expect(fetchMock).toHaveBeenNthCalledWith(
            2,
            '/api/v1/organizations/org%2Falpha/invitations/invitation%2F1/accept',
            expect.objectContaining({ method: 'POST', credentials: 'include' }),
        );
        const headers = fetchMock.mock.calls[1]?.[1]?.headers;
        if (!(headers instanceof Headers)) throw new Error('notification actions must use Headers.');
        expect(headers.get('X-CSRF-Token')).toBe('csrf-token');
        expect(headers.get('Idempotency-Key')).toMatch(/^accept-invitation\/1-/);
    });

    it('returns a typed error for stale or already-processed invitation actions', async () => {
        vi.stubGlobal('fetch', vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ detail: 'invitation_expired' }), { status: 409 }))));
        await expect(acceptInvitation('org-alpha', 'invitation-1')).rejects.toBeInstanceOf(NotificationApiError);
        await expect(acceptInvitation('org-alpha', 'invitation-1')).rejects.toMatchObject({ status: 409, code: 'invitation_expired' });
    });
});
