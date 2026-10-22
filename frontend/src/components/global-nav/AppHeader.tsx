'use client';

import React from 'react';
import { GlobalNav } from './index';
// Next.js automatically optimizes these via optmizePackageImports in next.config.ts
import { Bell, Settings, User } from 'lucide-react';
import Link from 'next/link';
import { useAuth } from '@/components/auth/AuthProvider';
import { usePathname, useRouter } from 'next/navigation';

export function AppHeader() {
    const { user, loading, signOut } = useAuth();
    const pathname = usePathname();
    const router = useRouter();

    async function handleSignOut() {
        await signOut();
        router.replace('/login');
    }

    return (
        <GlobalNav.Root>
            <div className="flex items-center">
                <GlobalNav.Logo />
                <GlobalNav.Links>
                    <GlobalNav.Link href="/">Markets</GlobalNav.Link>
                    <GlobalNav.Link href="/portfolio">Portfolio</GlobalNav.Link>
                    <GlobalNav.Link href="/workspace">Workspace</GlobalNav.Link>
                    <GlobalNav.Link href="/technical-observability">Observability</GlobalNav.Link>
                </GlobalNav.Links>
            </div>
            <GlobalNav.Actions>
                <button
                    className="p-2 text-on-surface-variant hover:text-on-surface transition-colors duration-200 focus:ring-2 focus:ring-primary-container focus:outline-none rounded"
                    aria-label="Notifications"
                >
                    <Bell size={18} />
                </button>
                {user ? <Link
                    href="/settings/llm"
                    className="p-2 text-on-surface-variant hover:text-on-surface transition-colors duration-200 focus:ring-2 focus:ring-primary-container focus:outline-none rounded"
                    aria-label="LLM settings"
                    title="LLM settings"
                >
                    <Settings size={18} />
                </Link> : null}
                {user ? (
                    <button
                        type="button"
                        onClick={() => void handleSignOut()}
                        className="flex items-center gap-2 rounded px-2 py-1 text-xs text-on-surface-variant hover:text-on-surface"
                        title="Sign out"
                    >
                        <span className="max-w-32 truncate">{user.email}</span>
                        <User size={16} />
                    </button>
                ) : loading || pathname === '/login' || pathname === '/register' ? null : (
                    <Link href="/login" className="rounded px-3 py-1.5 text-xs font-semibold text-on-surface-variant hover:text-on-surface">Sign in</Link>
                )}
            </GlobalNav.Actions>
        </GlobalNav.Root>
    );
}
