'use client';

import * as React from 'react';
import { Bell, Check, Clock3, X } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';
import { Skeleton } from '@/components/ui/skeleton';
import * as notificationApi from './api';
import type { NotificationItem } from './api';

type State =
    | { kind: 'loading' }
    | { kind: 'ready'; items: NotificationItem[] }
    | { kind: 'error'; message: string };

function payloadString(item: NotificationItem, key: string, fallback: string): string {
    const value = item.payload[key];
    return typeof value === 'string' && value.length > 0 ? value : fallback;
}

function statusLabel(item: NotificationItem): string {
    const fallback = item.expiresAt && Date.parse(item.expiresAt) <= Date.now() ? 'expired' : 'pending';
    return payloadString(item, 'status', fallback);
}

function InvitationActions({ item, onDone }: { item: NotificationItem; onDone: () => Promise<void> }) {
    const [pending, setPending] = React.useState<'accept' | 'decline' | null>(null);
    const [error, setError] = React.useState<string | null>(null);
    const idempotencyKeys = React.useRef(new Map<string, string>());
    const state = statusLabel(item);
    if (item.type !== 'organization.invitation' || !item.organizationId || !item.action?.actionRef || state !== 'pending') return null;
    const organizationId = item.organizationId;
    const invitationId = item.action.actionRef;

    async function act(operation: 'accept' | 'decline') {
        const operationKey = `${operation}:${invitationId}`;
        const idempotencyKey = idempotencyKeys.current.get(operationKey) ?? `${operation}-${invitationId}-${crypto.randomUUID()}`;
        idempotencyKeys.current.set(operationKey, idempotencyKey);
        setPending(operation);
        setError(null);
        try {
            if (operation === 'accept') await notificationApi.acceptInvitation(organizationId, invitationId, idempotencyKey);
            else await notificationApi.declineInvitation(organizationId, invitationId, idempotencyKey);
            idempotencyKeys.current.delete(operationKey);
            await onDone();
        } catch (caught) {
            const apiError = caught instanceof notificationApi.NotificationApiError ? caught : null;
            setError(apiError?.code === 'invitation_expired' ? 'This invitation has expired.' : 'This invitation is already processed or unavailable. Refresh to see the latest state.');
            await onDone();
        } finally {
            setPending(null);
        }
    }

    return (
        <div className="mt-4 space-y-2">
            <div className="flex flex-wrap gap-2">
                <Button size="sm" disabled={pending !== null} onClick={() => void act('accept')}>
                    <Check aria-hidden="true" />
                    {pending === 'accept' ? 'Accepting...' : 'Accept'}
                </Button>
                <Button size="sm" variant="outline" disabled={pending !== null} onClick={() => void act('decline')}>
                    <X aria-hidden="true" />
                    {pending === 'decline' ? 'Declining...' : 'Decline'}
                </Button>
            </div>
            {error ? <p className="text-sm text-destructive" role="alert">{error}</p> : null}
        </div>
    );
}

function NotificationCard({ item, onDone }: { item: NotificationItem; onDone: () => Promise<void> }) {
    const markedRead = React.useRef(false);
    const state = statusLabel(item);
    const organization = payloadString(item, 'organization_name', 'Your organization');
    const inviter = payloadString(item, 'inviter_display_name', 'An organization administrator');
    const role = payloadString(item, 'requested_role', 'member');
    const message = item.type === 'organization.invitation' ? `${inviter} invited you to join ${organization} as ${role}.` : payloadString(item, 'message', 'You have a new notification.');

    React.useEffect(() => {
        if (item.readAt || markedRead.current) return;
        markedRead.current = true;
        void notificationApi.markNotificationRead(item.notificationId).then(() => onDone()).catch(() => {
            markedRead.current = false;
        });
    }, [item.notificationId, item.readAt, onDone]);

    return (
        <Card className={item.readAt ? '' : 'border-primary/40'}>
            <CardHeader className="pb-3">
                <div className="flex items-start justify-between gap-3">
                    <div>
                        <CardTitle className="text-base">{item.type === 'organization.invitation' ? 'Organization invitation' : 'Notification'}</CardTitle>
                        <CardDescription>{new Date(item.createdAt).toLocaleString()}</CardDescription>
                    </div>
                    <Badge variant={state === 'pending' ? 'warning' : state === 'accepted' ? 'success' : state === 'revoked' || state === 'declined' ? 'destructive' : 'outline'}>{state}</Badge>
                </div>
            </CardHeader>
            <CardContent>
                <p className="text-sm text-foreground">{message}</p>
                <InvitationActions item={item} onDone={onDone} />
            </CardContent>
        </Card>
    );
}

export function NotificationInbox() {
    const [state, setState] = React.useState<State>({ kind: 'loading' });

    const refresh = React.useCallback(async () => {
        try {
            const result = await notificationApi.listNotifications();
            setState({ kind: 'ready', items: result.items });
        } catch (caught) {
            setState({ kind: 'error', message: caught instanceof Error ? caught.message : 'Could not load notifications.' });
        }
    }, []);

    React.useEffect(() => {
        const timer = window.setTimeout(() => void refresh(), 0);
        return () => window.clearTimeout(timer);
    }, [refresh]);

    if (state.kind === 'loading') {
        return <div className="mx-auto max-w-3xl space-y-3 p-4 sm:p-8"><Skeleton className="h-8 w-48" /><Skeleton className="h-28 w-full" /><Skeleton className="h-28 w-full" /></div>;
    }
    if (state.kind === 'error') {
        return <div className="mx-auto max-w-3xl p-4 sm:p-8"><Alert variant="destructive"><AlertTitle>Notifications unavailable</AlertTitle><AlertDescription>{state.message}<Button className="mt-3" variant="outline" onClick={() => void refresh()}>Try again</Button></AlertDescription></Alert></div>;
    }
    return (
        <main className="mx-auto max-w-3xl space-y-6 p-4 sm:p-8">
            <div className="flex items-center gap-3"><Bell aria-hidden="true" className="size-6 text-primary" /><div><h1 className="text-2xl font-semibold">Notifications</h1><p className="text-sm text-muted-foreground">Your private organization and system inbox.</p></div></div>
            {state.items.length === 0 ? <EmptyState icon={<Clock3 />} title="No notifications" description="New organization invitations will appear here." /> : <div className="space-y-3">{state.items.map((item) => <NotificationCard key={item.notificationId} item={item} onDone={refresh} />)}</div>}
        </main>
    );
}
