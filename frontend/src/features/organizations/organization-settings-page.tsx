'use client';

import * as React from 'react';
import {
    AlertTriangle,
    Building2,
    Check,
    Crown,
    Pencil,
    Plus,
    RefreshCw,
    ShieldCheck,
    UserRound,
    UserRoundMinus,
    UserRoundX,
} from 'lucide-react';
import { useAuth } from '@/components/auth/AuthProvider';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Badge, type BadgeProps } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Combobox } from '@/components/ui/combobox';
import { EmptyState } from '@/components/ui/empty-state';
import { Feedback } from '@/components/ui/feedback';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useOrganizationContext } from './organization-context';
import * as organizationApi from './api';
import {
    type Organization,
    type OrganizationMember,
    type OrganizationRole,
    type OrganizationRoleChange,
    type OrganizationStatusChange,
} from './api';

type MemberState =
    | { kind: 'idle' }
    | { kind: 'loading'; members: OrganizationMember[] }
    | { kind: 'ready'; members: OrganizationMember[] }
    | { kind: 'error'; members: OrganizationMember[]; error: Error };

type PendingAction =
    | { kind: 'role' | 'status' | 'transfer'; userId: string }
    | { kind: 'rename' | 'create'; userId: null };

type FeedbackState = { tone: 'success' | 'error'; message: string } | null;

const roleLabels: Record<OrganizationRole, string> = {
    owner: 'Owner',
    admin: 'Admin',
    member: 'Member',
};

const statusLabels: Record<organizationApi.OrganizationStatus, string> = {
    pending: 'Pending',
    active: 'Active',
    suspended: 'Suspended',
    removed: 'Removed',
};

const statusVariants: Record<organizationApi.OrganizationStatus, BadgeProps['variant']> = {
    pending: 'warning',
    active: 'success',
    suspended: 'warning',
    removed: 'destructive',
};

function isOrganizationApiError(error: unknown): error is organizationApi.OrganizationApiError {
    return error instanceof organizationApi.OrganizationApiError;
}

function isStaleOrganizationContext(error: unknown): boolean {
    return isOrganizationApiError(error) && [401, 403, 404].includes(error.status);
}

function errorMessage(error: unknown, fallback: string): string {
    return error instanceof Error && error.message ? error.message : fallback;
}

function replaceMember(state: MemberState, updated: OrganizationMember): MemberState {
    if (state.kind === 'idle') return state;
    const members = state.members.map((member) => (member.userId === updated.userId ? updated : member));
    if (state.kind === 'error') return { kind: 'error', members, error: state.error };
    if (state.kind === 'loading') return { kind: 'loading', members };
    return { kind: 'ready', members };
}

function roleOptions(actorRole: OrganizationRole, member: OrganizationMember): OrganizationRoleChange[] {
    if (member.status !== 'active' || member.role === 'owner') return [];
    if (actorRole === 'owner') return ['member', 'admin'];
    return [];
}

function MemberActions({
    actorRole,
    currentUserId,
    member,
    pendingAction,
    onRoleChange,
    onStatusChange,
    onTransfer,
}: {
    actorRole: OrganizationRole;
    currentUserId: string;
    member: OrganizationMember;
    pendingAction: PendingAction | null;
    onRoleChange: (member: OrganizationMember, role: OrganizationRoleChange) => void;
    onStatusChange: (member: OrganizationMember, status: OrganizationStatusChange) => void;
    onTransfer: (member: OrganizationMember) => void;
}) {
    const isPending = pendingAction?.userId === member.userId;
    const canManage = actorRole === 'owner' || actorRole === 'admin';
    const isSelf = member.userId === currentUserId;
    const options = roleOptions(actorRole, member);
    const canDemoteAdmin = actorRole === 'admin' && member.role === 'admin' && !isSelf;
    const canTransfer = actorRole === 'owner' && !isSelf && member.role !== 'owner' && member.status === 'active';
    const canChangeStatus =
        canManage &&
        !isSelf &&
        member.role !== 'owner' &&
        (member.status === 'active' || member.status === 'suspended');

    if (!canManage || (options.length === 0 && !canDemoteAdmin && !canChangeStatus && !canTransfer)) {
        return <span className="text-xs text-muted-foreground">View only</span>;
    }

    return (
        <div className="flex flex-wrap items-center justify-end gap-2">
            {options.length > 0 ? (
                <Combobox
                    value={member.role}
                    onValueChange={(value) => {
                        if (value === 'admin' || value === 'member') onRoleChange(member, value);
                    }}
                    options={options.map((option) => ({ value: option, label: roleLabels[option] }))}
                    ariaLabel={`Role for ${member.email}`}
                    searchPlaceholder="Search roles"
                    emptyMessage="No roles found."
                    className="h-9 w-28"
                    disabled={isPending}
                />
            ) : null}
            {canDemoteAdmin ? (
                <Button
                    variant="outline"
                    size="sm"
                    disabled={isPending}
                    onClick={() => onRoleChange(member, 'member')}
                >
                    <UserRoundMinus aria-hidden="true" />
                    Make member
                </Button>
            ) : null}
            {canChangeStatus ? (
                <>
                    {member.status === 'active' ? (
                        <Button
                            variant="outline"
                            size="sm"
                            disabled={isPending}
                            onClick={() => onStatusChange(member, 'suspended')}
                        >
                            <ShieldCheck aria-hidden="true" />
                            Suspend
                        </Button>
                    ) : (
                        <Button
                            variant="outline"
                            size="sm"
                            disabled={isPending}
                            onClick={() => onStatusChange(member, 'active')}
                        >
                            <Check aria-hidden="true" />
                            Reactivate
                        </Button>
                    )}
                    <Button
                        variant="destructive"
                        size="sm"
                        disabled={isPending}
                        onClick={() => onStatusChange(member, 'removed')}
                    >
                        <UserRoundX aria-hidden="true" />
                        Remove
                    </Button>
                </>
            ) : null}
            {canTransfer ? (
                <Button variant="outline" size="sm" disabled={isPending} onClick={() => onTransfer(member)}>
                    <Crown aria-hidden="true" />
                    Transfer ownership
                </Button>
            ) : null}
        </div>
    );
}

function MemberTable({
    actorRole,
    currentUserId,
    members,
    pendingAction,
    onRoleChange,
    onStatusChange,
    onTransfer,
}: {
    actorRole: OrganizationRole;
    currentUserId: string;
    members: OrganizationMember[];
    pendingAction: PendingAction | null;
    onRoleChange: (member: OrganizationMember, role: OrganizationRoleChange) => void;
    onStatusChange: (member: OrganizationMember, status: OrganizationStatusChange) => void;
    onTransfer: (member: OrganizationMember) => void;
}) {
    return (
        <Table>
            <caption className="sr-only">Organization members</caption>
            <TableHeader>
                <TableRow>
                    <TableHead>Member</TableHead>
                    <TableHead>Role</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                </TableRow>
            </TableHeader>
            <TableBody>
                {members.map((member) => (
                    <TableRow key={member.membershipId}>
                        <TableCell>
                            <div className="flex min-w-44 items-center gap-3">
                                <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
                                    <UserRound aria-hidden="true" className="size-4" />
                                </span>
                                <span className="min-w-0">
                                    <span className="block truncate font-medium text-foreground">{member.email}</span>
                                </span>
                            </div>
                        </TableCell>
                        <TableCell>
                            <Badge variant={member.role === 'owner' ? 'default' : 'outline'}>{roleLabels[member.role]}</Badge>
                        </TableCell>
                        <TableCell>
                            <Badge variant={statusVariants[member.status]}>{statusLabels[member.status]}</Badge>
                        </TableCell>
                        <TableCell className="min-w-72 text-right">
                            <MemberActions
                                actorRole={actorRole}
                                currentUserId={currentUserId}
                                member={member}
                                pendingAction={pendingAction}
                                onRoleChange={onRoleChange}
                                onStatusChange={onStatusChange}
                                onTransfer={onTransfer}
                            />
                        </TableCell>
                    </TableRow>
                ))}
            </TableBody>
        </Table>
    );
}

function TransferDialog({
    member,
    pending,
    onCancel,
    onConfirm,
}: {
    member: OrganizationMember | null;
    pending: boolean;
    onCancel: () => void;
    onConfirm: () => Promise<void>;
}) {
    return (
        <AlertDialog open={member !== null} onOpenChange={(open) => !open && onCancel()}>
            <AlertDialogContent>
                <AlertDialogHeader>
                    <AlertDialogTitle>Transfer organization ownership?</AlertDialogTitle>
                    <AlertDialogDescription>
                        {member ? `${member.email} will become the owner. Your membership will remain active as a member.` : ''}
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <AlertDialogCancel disabled={pending}>Cancel</AlertDialogCancel>
                    <AlertDialogAction
                        disabled={pending}
                        onClick={(event) => {
                            event.preventDefault();
                            void onConfirm();
                        }}
                    >
                        {pending ? 'Transferring...' : 'Transfer ownership'}
                    </AlertDialogAction>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    );
}

function OrganizationList({
    organizations,
    activeOrganization,
    isSelecting,
    onSelect,
}: {
    organizations: Organization[];
    activeOrganization: Organization | null;
    isSelecting: boolean;
    onSelect: (organizationId: string) => void;
}) {
    return (
        <ul className="grid gap-2" aria-label="Organizations">
            {organizations.map((organization) => {
                const active = organization.id === activeOrganization?.id;
                return (
                    <li key={organization.id}>
                        <div className="flex items-center justify-between gap-3 rounded-md border border-border/70 px-3 py-2">
                            <div className="flex min-w-0 items-center gap-3">
                                <Building2 aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
                                <span className="min-w-0">
                                    <span className="block truncate font-medium">{organization.name}</span>
                                    <span className="block text-xs text-muted-foreground">
                                        {roleLabels[organization.role]} · {statusLabels[organization.status]}
                                    </span>
                                </span>
                            </div>
                            <Button
                                variant={active ? 'secondary' : 'outline'}
                                size="sm"
                                aria-label={active ? `${organization.name} is active` : `Use ${organization.name}`}
                                disabled={active || isSelecting || organization.status !== 'active'}
                                onClick={() => onSelect(organization.id)}
                            >
                                {active ? 'Active' : 'Use'}
                            </Button>
                        </div>
                    </li>
                );
            })}
        </ul>
    );
}

export default function OrganizationSettingsPage() {
    const { user, refresh: refreshAuth } = useAuth();
    const {
        organizations,
        activeOrganization,
        error: organizationError,
        isLoading: organizationsLoading,
        isSelecting,
        refresh: refreshOrganizations,
        selectOrganization,
        createOrganization,
    } = useOrganizationContext();
    const [memberState, setMemberState] = React.useState<MemberState>({ kind: 'idle' });
    const [createName, setCreateName] = React.useState('');
    const [renameName, setRenameName] = React.useState('');
    const [pendingAction, setPendingAction] = React.useState<PendingAction | null>(null);
    const [feedback, setFeedback] = React.useState<FeedbackState>(null);
    const [transferTarget, setTransferTarget] = React.useState<OrganizationMember | null>(null);
    const memberRequestGenerationRef = React.useRef(0);
    const activeOrganizationIdRef = React.useRef<string | null>(activeOrganization?.id ?? null);

    React.useEffect(() => {
        activeOrganizationIdRef.current = activeOrganization?.id ?? null;
    }, [activeOrganization?.id]);

    const loadMembers = React.useCallback(async (organizationId: string) => {
        const requestId = ++memberRequestGenerationRef.current;
        const isCurrentRequest = () =>
            memberRequestGenerationRef.current === requestId && activeOrganizationIdRef.current === organizationId;
        setMemberState((previous) => ({ kind: 'loading', members: previous.kind === 'idle' ? [] : previous.members }));
        try {
            const members = await organizationApi.listOrganizationMembers(organizationId);
            if (!isCurrentRequest()) return;
            setMemberState({ kind: 'ready', members });
        } catch (nextError) {
            if (!isCurrentRequest()) return;
            setMemberState((previous) => ({
                kind: 'error',
                members: previous.kind === 'idle' ? [] : previous.members,
                error: nextError instanceof Error ? nextError : new Error('Members could not be loaded.'),
            }));
        }
    }, []);

    React.useEffect(() => {
        if (!activeOrganization) {
            memberRequestGenerationRef.current += 1;
            setMemberState({ kind: 'idle' });
            return;
        }
        activeOrganizationIdRef.current = activeOrganization.id;
        void loadMembers(activeOrganization.id);
        return () => {
            memberRequestGenerationRef.current += 1;
        };
    }, [activeOrganization, loadMembers]);

    React.useEffect(() => {
        setRenameName(activeOrganization?.name ?? '');
    }, [activeOrganization?.id, activeOrganization?.name]);

    async function handleCreate(event: React.FormEvent<HTMLFormElement>) {
        event.preventDefault();
        const name = createName.trim();
        if (!name) {
            setFeedback({ tone: 'error', message: 'Enter an organization name.' });
            return;
        }
        setPendingAction({ kind: 'create', userId: null });
        setFeedback(null);
        try {
            const created = await createOrganization(name);
            const selected = await selectOrganization(created.id);
            if (!selected) throw new Error('The organization was created but could not be selected.');
            setCreateName('');
            setFeedback({ tone: 'success', message: `${created.name} is now active.` });
        } catch (nextError) {
            setFeedback({ tone: 'error', message: errorMessage(nextError, 'The organization could not be created.') });
        } finally {
            setPendingAction(null);
        }
    }

    async function handleRename(event: React.FormEvent<HTMLFormElement>) {
        event.preventDefault();
        if (!activeOrganization) return;
        const name = renameName.trim();
        if (!name) {
            setFeedback({ tone: 'error', message: 'Enter an organization name.' });
            return;
        }
        setPendingAction({ kind: 'rename', userId: null });
        setFeedback(null);
        try {
            await organizationApi.renameOrganization(activeOrganization.id, name);
            await refreshOrganizations();
            setFeedback({ tone: 'success', message: 'Organization name updated.' });
        } catch (nextError) {
            setFeedback({ tone: 'error', message: errorMessage(nextError, 'The organization name could not be updated.') });
        } finally {
            setPendingAction(null);
        }
    }

    async function runMemberMutation(
        action: PendingAction,
        operation: () => Promise<OrganizationMember>,
    ): Promise<boolean> {
        if (!activeOrganization) return false;
        const organizationId = activeOrganization.id;
        setPendingAction(action);
        setFeedback(null);
        try {
            const updated = await operation();
            if (activeOrganizationIdRef.current !== organizationId) return false;
            setMemberState((previous) => replaceMember(previous, updated));
            await refreshOrganizations();
            await refreshAuth();
            if (activeOrganizationIdRef.current !== organizationId) return false;
            await loadMembers(organizationId);
            setFeedback({ tone: 'success', message: 'Membership updated.' });
            return true;
        } catch (nextError) {
            setFeedback({
                tone: 'error',
                message: isStaleOrganizationContext(nextError)
                    ? 'This organization context is no longer available. Refresh and choose an active organization.'
                    : errorMessage(nextError, 'The membership could not be updated.'),
            });
            return false;
        } finally {
            setPendingAction(null);
        }
    }

    function handleRoleChange(member: OrganizationMember, role: OrganizationRoleChange) {
        void runMemberMutation(
            { kind: 'role', userId: member.userId },
            () => organizationApi.changeMemberRole(activeOrganization?.id ?? '', member.userId, role),
        );
    }

    function handleStatusChange(member: OrganizationMember, status: OrganizationStatusChange) {
        void runMemberMutation(
            { kind: 'status', userId: member.userId },
            () => organizationApi.changeMemberStatus(activeOrganization?.id ?? '', member.userId, status),
        );
    }

    async function handleTransfer() {
        if (!activeOrganization || !transferTarget) return;
        const completed = await runMemberMutation(
            { kind: 'transfer', userId: transferTarget.userId },
            () => organizationApi.transferOwnership(activeOrganization.id, transferTarget.userId),
        );
        if (completed) setTransferTarget(null);
    }

    const canRename = activeOrganization?.role === 'owner' || activeOrganization?.role === 'admin';
    const memberError = memberState.kind === 'error' ? memberState.error : null;

    return (
        <main className="mx-auto grid w-full max-w-6xl gap-6 px-4 py-8 sm:px-6 lg:px-8">
            <header className="grid gap-2">
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">Organization</p>
                <h1 className="font-headline text-3xl font-semibold tracking-tight text-foreground">Organization workspace</h1>
                <p className="max-w-2xl text-sm text-muted-foreground">
                    Manage the active organization and its members. Access is enforced by the server for every action.
                </p>
            </header>

            {feedback ? <Feedback tone={feedback.tone}>{feedback.message}</Feedback> : null}

            {organizationError ? (
                <Alert variant="destructive">
                    <AlertTriangle aria-hidden="true" className="size-4" />
                    <AlertTitle>Organization context unavailable</AlertTitle>
                    <AlertDescription className="flex flex-wrap items-center justify-between gap-3">
                        <span>
                            {organizationError.message || 'Refresh the session or choose an active organization before continuing.'}
                        </span>
                        <Button variant="outline" size="sm" onClick={() => void refreshOrganizations()}>
                            <RefreshCw aria-hidden="true" />
                            Retry
                        </Button>
                    </AlertDescription>
                </Alert>
            ) : null}

            <section className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.45fr)]">
                <Card>
                    <CardHeader>
                        <CardTitle>Organizations</CardTitle>
                        <CardDescription>Choose the organization used by organization-scoped surfaces.</CardDescription>
                    </CardHeader>
                    <CardContent className="grid gap-5">
                        {organizationsLoading && organizations.length === 0 ? (
                            <div className="grid gap-3" aria-label="Loading organizations">
                                <Skeleton className="h-12 w-full" />
                                <Skeleton className="h-12 w-full" />
                            </div>
                        ) : organizations.length > 0 ? (
                            <OrganizationList
                                organizations={organizations}
                                activeOrganization={activeOrganization}
                                isSelecting={isSelecting}
                                onSelect={(organizationId) => void selectOrganization(organizationId)}
                            />
                        ) : (
                            <EmptyState
                                icon={<Building2 />}
                                title="No organizations yet"
                                description="Create an organization to start sharing organization-scoped capabilities."
                            />
                        )}
                        <form className="grid gap-3 border-t border-border/60 pt-4" onSubmit={(event) => void handleCreate(event)}>
                            <div className="grid gap-1.5">
                                <Label htmlFor="new-organization-name">Create organization</Label>
                                <Input
                                    id="new-organization-name"
                                    value={createName}
                                    onChange={(event) => setCreateName(event.target.value)}
                                    placeholder="e.g. Research team"
                                    maxLength={120}
                                    disabled={pendingAction?.kind === 'create'}
                                />
                            </div>
                            <Button type="submit" className="w-fit" disabled={pendingAction?.kind === 'create'}>
                                <Plus aria-hidden="true" />
                                Create organization
                            </Button>
                        </form>
                    </CardContent>
                </Card>

                <Card>
                    <CardHeader>
                        <CardTitle>Active organization</CardTitle>
                        <CardDescription>The selected context is revalidated by the backend on every request.</CardDescription>
                    </CardHeader>
                    <CardContent>
                        {!activeOrganization ? (
                            <EmptyState
                                icon={<AlertTriangle />}
                                title="Select an active organization"
                                description="Choose an active membership from the organization list to view its members."
                            />
                        ) : (
                            <div className="grid gap-5">
                                <div className="flex flex-wrap items-start justify-between gap-4 rounded-md border border-border/70 p-4">
                                    <div className="flex items-start gap-3">
                                        <span className="flex size-10 items-center justify-center rounded-md bg-primary/10 text-primary">
                                            <Building2 aria-hidden="true" className="size-5" />
                                        </span>
                                        <div className="grid gap-1">
                                            <h2 className="text-lg font-semibold">{activeOrganization.name}</h2>
                                            <p className="text-sm text-muted-foreground">
                                                {roleLabels[activeOrganization.role]} · {statusLabels[activeOrganization.status]}
                                            </p>
                                        </div>
                                    </div>
                                    <Badge variant={statusVariants[activeOrganization.status]}>
                                        {statusLabels[activeOrganization.status]}
                                    </Badge>
                                </div>
                                {canRename ? (
                                    <form className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end" onSubmit={(event) => void handleRename(event)}>
                                        <div className="grid gap-1.5">
                                            <Label htmlFor="organization-name">Organization name</Label>
                                            <Input
                                                id="organization-name"
                                                value={renameName}
                                                onChange={(event) => setRenameName(event.target.value)}
                                                maxLength={120}
                                                disabled={pendingAction?.kind === 'rename'}
                                            />
                                        </div>
                                        <Button type="submit" variant="outline" disabled={pendingAction?.kind === 'rename'}>
                                            <Pencil aria-hidden="true" />
                                            Rename
                                        </Button>
                                    </form>
                                ) : null}
                            </div>
                        )}
                    </CardContent>
                </Card>
            </section>

            <Card>
                <CardHeader className="flex-row items-start justify-between gap-4">
                    <div className="grid gap-1.5">
                        <CardTitle>Members</CardTitle>
                        <CardDescription>Manage membership within the selected organization.</CardDescription>
                    </div>
                    {activeOrganization ? (
                        <Badge variant="outline">
                            {memberState.kind === 'ready' || memberState.kind === 'loading' || memberState.kind === 'error'
                                ? `${memberState.members.length} members`
                                : 'Loading'}
                        </Badge>
                    ) : null}
                </CardHeader>
                <CardContent>
                    {!activeOrganization ? (
                        <EmptyState icon={<UserRound />} title="No organization selected" description="Select an organization above to view members." />
                    ) : memberState.kind === 'idle' || memberState.kind === 'loading' ? (
                        <div className="grid gap-3" aria-label="Loading members">
                            <Skeleton className="h-12 w-full" />
                            <Skeleton className="h-12 w-full" />
                            <Skeleton className="h-12 w-full" />
                        </div>
                    ) : memberState.kind === 'error' ? (
                        <Alert variant={isStaleOrganizationContext(memberError) ? 'warning' : 'destructive'}>
                            <AlertTriangle aria-hidden="true" className="size-4" />
                            <AlertTitle>{isStaleOrganizationContext(memberError) ? 'Organization context changed' : 'Members unavailable'}</AlertTitle>
                            <AlertDescription className="flex flex-wrap items-center justify-between gap-3">
                                <span>
                                    {isStaleOrganizationContext(memberError)
                                        ? 'Choose another active organization or refresh this membership context.'
                                        : errorMessage(memberError, 'The member list could not be loaded.')}
                                </span>
                                <Button variant="outline" size="sm" onClick={() => void loadMembers(activeOrganization.id)}>
                                    <RefreshCw aria-hidden="true" />
                                    Retry
                                </Button>
                            </AlertDescription>
                        </Alert>
                    ) : memberState.members.length === 0 ? (
                        <EmptyState icon={<UserRoundMinus />} title="No members found" description="This organization has no active member records." />
                    ) : (
                        <MemberTable
                            actorRole={activeOrganization.role}
                            currentUserId={user?.user_id ?? ''}
                            members={memberState.members}
                            pendingAction={pendingAction}
                            onRoleChange={handleRoleChange}
                            onStatusChange={handleStatusChange}
                            onTransfer={setTransferTarget}
                        />
                    )}
                </CardContent>
            </Card>

            <TransferDialog
                member={transferTarget}
                pending={pendingAction?.kind === 'transfer'}
                onCancel={() => setTransferTarget(null)}
                onConfirm={handleTransfer}
            />
        </main>
    );
}
