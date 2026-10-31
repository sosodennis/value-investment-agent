import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Organization } from './api';
import OrganizationSettingsPage from './organization-settings-page';

type TestOrganizationContext = {
    organizations: Organization[];
    activeOrganization: Organization | null;
    error: Error | null;
    isLoading: boolean;
    isSelecting: boolean;
    selectingOrganizationId: string | null;
    refresh: ReturnType<typeof vi.fn>;
    selectOrganization: ReturnType<typeof vi.fn>;
    createOrganization: ReturnType<typeof vi.fn>;
};

const state = vi.hoisted(() => {
    const context: TestOrganizationContext = {
        organizations: [],
        activeOrganization: null,
        error: null,
        isLoading: false,
        isSelecting: false,
        selectingOrganizationId: null,
        refresh: vi.fn(),
        selectOrganization: vi.fn(),
        createOrganization: vi.fn(),
    };
    return {
        api: {
            listOrganizationMembers: vi.fn(),
            changeMemberRole: vi.fn(),
            changeMemberStatus: vi.fn(),
            transferOwnership: vi.fn(),
            renameOrganization: vi.fn(),
        },
        context,
        auth: {
            user: {
                auth_type: 'session' as const,
                email: 'alice@example.test',
                role: 'user' as const,
                subject: 'user-alice',
                user_id: 'user-alice',
                organization_id: 'org-alpha',
                membership_id: 'membership-alice',
            },
            refresh: vi.fn(),
        },
    };
});

vi.mock('@/components/auth/AuthProvider', () => ({
    useAuth: () => ({
        ...state.auth,
        loading: false,
        signIn: vi.fn(),
        signUp: vi.fn(),
        signOut: vi.fn(),
    }),
}));

vi.mock('./organization-context', () => ({
    useOrganizationContext: () => state.context,
}));

vi.mock('./api', () => ({
    ...state.api,
    OrganizationApiError: class OrganizationApiError extends Error {
        readonly status: number;
        readonly code: string | null;

        constructor(message: string, status: number, code: string | null = null) {
            super(message);
            this.status = status;
            this.code = code;
        }
    },
}));

const activeOrganization = {
    id: 'org-alpha',
    name: 'Alpha team',
    createdAt: '2026-10-31T00:00:00Z',
    membershipId: 'membership-alice',
    role: 'owner' as const,
    status: 'active' as const,
};

const organizations = [activeOrganization];

const members = [
    {
        userId: 'user-alice',
        email: 'alice@example.test',
        membershipId: 'membership-alice',
        organizationId: 'org-alpha',
        role: 'owner' as const,
        status: 'active' as const,
        createdAt: '2026-10-31T00:00:00Z',
        updatedAt: '2026-10-31T00:00:00Z',
    },
    {
        userId: 'user-bob',
        email: 'bob@example.test',
        membershipId: 'membership-bob',
        organizationId: 'org-alpha',
        role: 'member' as const,
        status: 'active' as const,
        createdAt: '2026-10-31T00:00:00Z',
        updatedAt: '2026-10-31T00:00:00Z',
    },
];

const betaOrganization = {
    ...activeOrganization,
    id: 'org-beta',
    name: 'Beta team',
    membershipId: 'membership-bob',
};

const betaMembers = [
    {
        ...members[1],
        userId: 'user-carol',
        email: 'carol@example.test',
        membershipId: 'membership-carol',
        organizationId: 'org-beta',
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

describe('organization settings page', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        state.context.organizations = organizations;
        state.context.activeOrganization = activeOrganization;
        state.context.error = null;
        state.context.isLoading = false;
        state.context.isSelecting = false;
        state.context.selectingOrganizationId = null;
        state.api.listOrganizationMembers.mockResolvedValue(members);
        state.api.changeMemberRole.mockResolvedValue(members[1]);
        state.api.changeMemberStatus.mockResolvedValue({ ...members[1], status: 'suspended' });
        state.api.transferOwnership.mockResolvedValue({ ...members[1], role: 'owner' });
        state.api.renameOrganization.mockResolvedValue(activeOrganization);
        state.context.refresh.mockResolvedValue(undefined);
        state.context.selectOrganization.mockResolvedValue(undefined);
        state.context.createOrganization.mockResolvedValue({ ...activeOrganization, id: 'org-beta', name: 'Beta team' });
        state.auth.refresh.mockResolvedValue(state.auth.user);
    });

    afterEach(cleanup);

    it('renders the active organization and server-backed member actions', async () => {
        render(<OrganizationSettingsPage />);

        expect(await screen.findByRole('heading', { name: 'Alpha team' })).toBeTruthy();
        expect(await screen.findByText('bob@example.test')).toBeTruthy();
        expect(screen.getByRole('button', { name: 'Transfer ownership' })).toBeTruthy();
        expect(screen.getByRole('button', { name: 'Remove' })).toBeTruthy();
    });

    it('submits member status changes and reloads the authoritative list', async () => {
        render(<OrganizationSettingsPage />);
        await screen.findByText('bob@example.test');

        fireEvent.click(screen.getByRole('button', { name: 'Suspend' }));

        await screen.findByText('Membership updated.');
        expect(state.api.changeMemberStatus).toHaveBeenCalledWith('org-alpha', 'user-bob', 'suspended');
        expect(state.api.listOrganizationMembers).toHaveBeenCalledTimes(2);
    });

    it('requires confirmation before transferring ownership', async () => {
        render(<OrganizationSettingsPage />);
        await screen.findByText('bob@example.test');

        fireEvent.click(screen.getByRole('button', { name: 'Transfer ownership' }));
        const dialog = await screen.findByRole('alertdialog');
        expect(within(dialog).getByText(/bob@example.test will become the owner/)).toBeTruthy();
        fireEvent.click(within(dialog).getByRole('button', { name: 'Transfer ownership' }));

        await screen.findByText('Membership updated.');
        expect(state.api.transferOwnership).toHaveBeenCalledWith('org-alpha', 'user-bob');
    });

    it('renders a read-only member view when the server reports member role', async () => {
        state.context.activeOrganization = { ...activeOrganization, role: 'member' };
        render(<OrganizationSettingsPage />);
        await screen.findByText('bob@example.test');

        expect(screen.queryByRole('button', { name: 'Remove' })).toBeNull();
        expect(screen.queryByRole('button', { name: 'Transfer ownership' })).toBeNull();
        expect(screen.queryByLabelText('Organization name')).toBeNull();
        expect(screen.getAllByText('View only').length).toBeGreaterThan(0);
    });

    it('shows a recoverable member-loading error and retries the route', async () => {
        state.api.listOrganizationMembers
            .mockRejectedValueOnce(new Error('member service unavailable'))
            .mockResolvedValueOnce(members);
        render(<OrganizationSettingsPage />);

        expect(await screen.findByText('Members unavailable')).toBeTruthy();
        fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
        expect(await screen.findByText('bob@example.test')).toBeTruthy();
        expect(state.api.listOrganizationMembers).toHaveBeenCalledTimes(2);
    });

    it('does not render a stale member response after switching organizations', async () => {
        const alphaResponse = deferred<typeof members>();
        const betaResponse = deferred<typeof betaMembers>();
        state.api.listOrganizationMembers.mockImplementation((organizationId: string) =>
            organizationId === 'org-alpha' ? alphaResponse.promise : betaResponse.promise,
        );
        const view = render(<OrganizationSettingsPage />);

        state.context.organizations = [betaOrganization];
        state.context.activeOrganization = betaOrganization;
        view.rerender(<OrganizationSettingsPage />);

        alphaResponse.resolve(members);
        await Promise.resolve();
        expect(screen.queryByText('bob@example.test')).toBeNull();

        betaResponse.resolve(betaMembers);
        expect(await screen.findByText('carol@example.test')).toBeTruthy();
        expect(screen.queryByText('bob@example.test')).toBeNull();
    });

    it('keeps pending memberships read-only until the backend accepts them', async () => {
        const pendingMember = { ...members[1], status: 'pending' as const };
        state.api.listOrganizationMembers.mockResolvedValue([members[0], pendingMember]);
        render(<OrganizationSettingsPage />);

        await screen.findByText('bob@example.test');
        expect(screen.queryByRole('button', { name: 'Remove' })).toBeNull();
        expect(screen.getAllByText('View only').length).toBeGreaterThan(0);
    });
});
