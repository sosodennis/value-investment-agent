'use client';

import * as React from 'react';
import { useAuth } from '@/components/auth/AuthProvider';
import * as authApi from '@/lib/auth-api';
import {
    createOrganization,
    listOrganizations,
    OrganizationApiError,
    type Organization,
} from './api';

type OrganizationContextValue = {
    organizations: Organization[];
    activeOrganization: Organization | null;
    isLoading: boolean;
    isSelecting: boolean;
    selectingOrganizationId: string | null;
    error: OrganizationApiError | Error | null;
    refresh: () => Promise<void>;
    selectOrganization: (organizationId: string) => Promise<boolean>;
    createOrganization: (name: string) => Promise<Organization>;
};

const OrganizationContext = React.createContext<OrganizationContextValue | null>(null);

function errorStatus(error: unknown): number | null {
    if (error instanceof OrganizationApiError) return error.status;
    if (error instanceof Error && 'status' in error && typeof error.status === 'number') return error.status;
    return null;
}

export function OrganizationProvider({ children }: { children: React.ReactNode }) {
    const { user, loading: authLoading, refresh: refreshAuth } = useAuth();
    const userId = user?.user_id ?? null;
    const [organizations, setOrganizations] = React.useState<Organization[]>([]);
    const [isLoading, setIsLoading] = React.useState(true);
    const [isSelecting, setIsSelecting] = React.useState(false);
    const [selectingOrganizationId, setSelectingOrganizationId] = React.useState<string | null>(null);
    const [error, setError] = React.useState<OrganizationApiError | Error | null>(null);
    const requestGenerationRef = React.useRef(0);
    const selectionGenerationRef = React.useRef(0);
    const currentUserIdRef = React.useRef<string | null>(userId);

    React.useEffect(() => {
        const previousUserId = currentUserIdRef.current;
        currentUserIdRef.current = userId;
        if (previousUserId === userId) return;

        requestGenerationRef.current += 1;
        setOrganizations([]);
        setError(null);
        setIsLoading(userId !== null && !authLoading);
    }, [authLoading, userId]);

    React.useEffect(() => () => {
        requestGenerationRef.current += 1;
        selectionGenerationRef.current += 1;
    }, []);

    const refresh = React.useCallback(async () => {
        const requestId = ++requestGenerationRef.current;
        const requestedUserId = userId;
        const isCurrentRequest = () =>
            requestGenerationRef.current === requestId && currentUserIdRef.current === requestedUserId;

        if (!requestedUserId) {
            setOrganizations([]);
            setError(null);
            setIsLoading(false);
            return;
        }

        setIsLoading(true);
        setError(null);
        try {
            const nextOrganizations = await listOrganizations();
            if (!isCurrentRequest()) return;
            setOrganizations(nextOrganizations);
        } catch (nextError) {
            if (!isCurrentRequest()) return;
            if (nextError instanceof OrganizationApiError && [401, 403, 404].includes(nextError.status)) {
                setOrganizations([]);
            }
            setError(nextError instanceof Error ? nextError : new Error('Organization list could not be loaded.'));
            if (nextError instanceof OrganizationApiError && nextError.status === 401) {
                await refreshAuth();
            }
        } finally {
            if (isCurrentRequest()) setIsLoading(false);
        }
    }, [refreshAuth, userId]);

    React.useEffect(() => {
        if (authLoading) return;
        let cancelled = false;
        void Promise.resolve().then(() => {
            if (!cancelled) return refresh();
            return undefined;
        });
        return () => {
            cancelled = true;
        };
    }, [authLoading, refresh]);

    const selectOrganization = React.useCallback(
        async (organizationId: string): Promise<boolean> => {
            const selectionId = ++selectionGenerationRef.current;
            const selectedUserId = userId;
            setIsSelecting(true);
            setSelectingOrganizationId(organizationId);
            setError(null);
            try {
                const selectedUser = await authApi.selectActiveOrganization(organizationId);
                if (selectionGenerationRef.current !== selectionId || currentUserIdRef.current !== selectedUserId) {
                    return false;
                }
                const refreshedUser = await refreshAuth();
                if (!refreshedUser || refreshedUser.organization_id !== selectedUser.organization_id) {
                    throw new Error('The active organization could not be confirmed.');
                }
                await refresh();
                return true;
            } catch (nextError) {
                if (selectionGenerationRef.current !== selectionId || currentUserIdRef.current !== selectedUserId) {
                    return false;
                }
                const status = errorStatus(nextError);
                if (status === 401) {
                    await refreshAuth();
                }
                if (status !== null && [403, 404].includes(status)) {
                    setOrganizations((current) => current.filter((organization) => organization.id !== organizationId));
                }
                setError(nextError instanceof Error ? nextError : new Error('The organization could not be selected.'));
                return false;
            } finally {
                if (selectionGenerationRef.current === selectionId) {
                    setIsSelecting(false);
                    setSelectingOrganizationId(null);
                }
            }
        },
        [refresh, refreshAuth, userId],
    );

    const createOrganizationForUser = React.useCallback(
        async (name: string) => {
            const created = await createOrganization(name);
            await refresh();
            return created;
        },
        [refresh],
    );

    const activeOrganization = React.useMemo(
        () => organizations.find((organization) => organization.id === user?.organization_id) ?? null,
        [organizations, user?.organization_id],
    );

    const value = React.useMemo<OrganizationContextValue>(
        () => ({
            organizations,
            activeOrganization,
            isLoading,
            isSelecting,
            selectingOrganizationId,
            error,
            refresh,
            selectOrganization,
            createOrganization: createOrganizationForUser,
        }),
        [
            activeOrganization,
            createOrganizationForUser,
            error,
            isLoading,
            isSelecting,
            organizations,
            refresh,
            selectOrganization,
            selectingOrganizationId,
        ],
    );

    return <OrganizationContext.Provider value={value}>{children}</OrganizationContext.Provider>;
}

export function useOrganizationContext(): OrganizationContextValue {
    const value = React.useContext(OrganizationContext);
    if (!value) throw new Error('useOrganizationContext must be used inside OrganizationProvider');
    return value;
}
