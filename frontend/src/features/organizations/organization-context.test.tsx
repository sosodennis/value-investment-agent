import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { OrganizationProvider, useOrganizationContext } from './organization-context';

const state = vi.hoisted(() => ({
    OrganizationApiError: class OrganizationApiError extends Error {
        readonly status: number;

        constructor(message: string, status: number) {
            super(message);
            this.status = status;
        }
    },
    activeOrganizationId: 'org-alpha',
    listOrganizations: vi.fn(),
    createOrganization: vi.fn(),
    selectActiveOrganization: vi.fn(),
    refresh: vi.fn(),
    user: {
        auth_type: 'session' as const,
        email: 'alice@example.test',
        role: 'user' as const,
        subject: 'user-alice',
        user_id: 'user-alice',
        organization_id: 'org-alpha',
        membership_id: 'membership-alpha',
    },
}));

vi.mock('@/components/auth/AuthProvider', () => ({
    useAuth: () => ({
        user: state.user,
        loading: false,
        refresh: state.refresh,
        signIn: vi.fn(),
        signUp: vi.fn(),
        signOut: vi.fn(),
    }),
}));

vi.mock('@/lib/auth-api', () => ({
    selectActiveOrganization: state.selectActiveOrganization,
}));

vi.mock('./api', () => ({
    listOrganizations: state.listOrganizations,
    createOrganization: state.createOrganization,
    OrganizationApiError: state.OrganizationApiError,
}));

const organizations = [
    {
        id: 'org-alpha',
        name: 'Alpha team',
        createdAt: '2026-10-31T00:00:00Z',
        membershipId: 'membership-alpha',
        role: 'owner' as const,
        status: 'active' as const,
    },
    {
        id: 'org-beta',
        name: 'Beta team',
        createdAt: '2026-10-31T00:00:00Z',
        membershipId: 'membership-beta',
        role: 'member' as const,
        status: 'active' as const,
    },
];

function deferred<T>() {
    let resolve!: (value: T) => void;
    let reject!: (reason?: unknown) => void;
    const promise = new Promise<T>((promiseResolve, promiseReject) => {
        resolve = promiseResolve;
        reject = promiseReject;
    });
    return { promise, resolve, reject };
}

function Probe() {
    const context = useOrganizationContext();
    return (
        <div>
            <p data-testid="active">{context.activeOrganization?.name ?? 'none'}</p>
            <p data-testid="error">{context.error?.message ?? 'none'}</p>
            <button onClick={() => void context.selectOrganization('org-beta')}>select beta</button>
        </div>
    );
}

describe('organization context', () => {
    beforeEach(() => {
        state.activeOrganizationId = 'org-alpha';
        state.user = {
            ...state.user,
            email: 'alice@example.test',
            subject: 'user-alice',
            user_id: 'user-alice',
            organization_id: 'org-alpha',
            membership_id: 'membership-alpha',
        };
        state.listOrganizations.mockReset().mockResolvedValue(organizations);
        state.createOrganization.mockReset();
        state.selectActiveOrganization.mockReset().mockImplementation(async (organizationId: string) => {
            state.activeOrganizationId = organizationId;
            return {
                ...state.user,
                organization_id: organizationId,
                membership_id: organizationId === 'org-beta' ? 'membership-beta' : 'membership-alpha',
            };
        });
        state.refresh.mockReset().mockImplementation(async () => {
            state.user = {
                ...state.user,
                organization_id: state.activeOrganizationId,
                membership_id: state.activeOrganizationId === 'org-beta' ? 'membership-beta' : 'membership-alpha',
            };
            return state.user;
        });
    });

    afterEach(cleanup);

    it('loads the organization list and exposes the server-confirmed active organization', async () => {
        render(
            <OrganizationProvider>
                <Probe />
            </OrganizationProvider>,
        );

        expect((await screen.findByTestId('active')).textContent).toBe('Alpha team');
        expect(state.listOrganizations).toHaveBeenCalled();
    });

    it('refreshes the authenticated session before exposing a newly selected organization', async () => {
        render(
            <OrganizationProvider>
                <Probe />
            </OrganizationProvider>,
        );

        await screen.findByText('Alpha team');
        fireEvent.click(screen.getByRole('button', { name: 'select beta' }));

        await waitFor(() => expect(screen.getByTestId('active').textContent).toBe('Beta team'));
        expect(state.selectActiveOrganization).toHaveBeenCalledWith('org-beta');
        expect(state.refresh).toHaveBeenCalled();
    });

    it('keeps a recoverable error when the organization list fails', async () => {
        state.listOrganizations.mockRejectedValueOnce(new Error('organization service unavailable'));
        render(
            <OrganizationProvider>
                <Probe />
            </OrganizationProvider>,
        );

        await waitFor(() => expect(screen.getByTestId('error').textContent).toBe('organization service unavailable'));
    });

    it('ignores a previous user organization response after the authenticated user changes', async () => {
        const firstResponse = deferred<typeof organizations>();
        const secondResponse = deferred<typeof organizations>();
        state.listOrganizations
            .mockReset()
            .mockImplementationOnce(() => firstResponse.promise)
            .mockImplementationOnce(() => secondResponse.promise);
        const view = render(
            <OrganizationProvider>
                <Probe />
            </OrganizationProvider>,
        );

        state.user = {
            ...state.user,
            user_id: 'user-bob',
            subject: 'user-bob',
            email: 'bob@example.test',
            organization_id: 'org-beta',
            membership_id: 'membership-beta',
        };
        view.rerender(
            <OrganizationProvider>
                <Probe />
            </OrganizationProvider>,
        );

        firstResponse.resolve(organizations);
        await Promise.resolve();
        expect(screen.getByTestId('active').textContent).toBe('none');

        secondResponse.resolve([organizations[1]]);
        await waitFor(() => expect(screen.getByTestId('active').textContent).toBe('Beta team'));
    });

    it('revalidates the auth session after an organization request returns 401', async () => {
        state.listOrganizations.mockReset().mockRejectedValueOnce(new state.OrganizationApiError('expired', 401));
        state.refresh.mockReset().mockResolvedValueOnce(null);
        render(
            <OrganizationProvider>
                <Probe />
            </OrganizationProvider>,
        );

        await waitFor(() => expect(state.refresh).toHaveBeenCalled());
        expect(screen.getByTestId('active').textContent).toBe('none');
        expect(screen.getByTestId('error').textContent).toBe('expired');
    });
});
