'use client';

import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import type { AuthUser } from '@/lib/auth-api';
import * as authApi from '@/lib/auth-api';

type AuthContextValue = {
    user: AuthUser | null;
    loading: boolean;
    refresh: () => Promise<AuthUser | null>;
    signIn: (email: string, password: string) => Promise<AuthUser>;
    signUp: (email: string, displayName: string, password: string) => Promise<AuthUser>;
    signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
    const [user, setUser] = useState<AuthUser | null>(null);
    const [loading, setLoading] = useState(true);

    async function refresh(): Promise<AuthUser | null> {
        try {
            const nextUser = await authApi.getCurrentUser();
            setUser(nextUser);
            return nextUser;
        } catch {
            setUser(null);
            return null;
        } finally {
            setLoading(false);
        }
    }

    useEffect(() => {
        let active = true;
        void authApi.getCurrentUser()
            .then((nextUser) => {
                if (active) setUser(nextUser);
            })
            .catch(() => {
                if (active) setUser(null);
            })
            .finally(() => {
                if (active) setLoading(false);
            });

        return () => {
            active = false;
        };
    }, []);

    const value = useMemo<AuthContextValue>(
        () => ({
            user,
            loading,
            refresh,
            signIn: async (email, password) => {
                const nextUser = await authApi.login(email, password);
                setUser(nextUser);
                return nextUser;
            },
            signUp: async (email, displayName, password) => {
                const nextUser = await authApi.register(email, displayName, password);
                setUser(nextUser);
                return nextUser;
            },
            signOut: async () => {
                await authApi.logout();
                setUser(null);
            },
        }),
        [loading, user],
    );

    return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
    const value = useContext(AuthContext);
    if (!value) throw new Error('useAuth must be used inside AuthProvider');
    return value;
}
