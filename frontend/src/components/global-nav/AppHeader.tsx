'use client';

import React from 'react';
import { GlobalNav } from './index';
// Next.js automatically optimizes these via optmizePackageImports in next.config.ts
import { Bell, Settings, User } from 'lucide-react';

export function AppHeader() {
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
                    className="p-2 text-on-surface-variant hover:text-on-surface transition-all duration-200 focus:ring-2 focus:ring-primary-container focus:outline-none rounded"
                    aria-label="Notifications"
                >
                    <Bell size={18} />
                </button>
                <button
                    className="p-2 text-on-surface-variant hover:text-on-surface transition-all duration-200 focus:ring-2 focus:ring-primary-container focus:outline-none rounded"
                    aria-label="Settings"
                >
                    <Settings size={18} />
                </button>
                <div className="h-8 w-8 rounded-full overflow-hidden border border-outline-variant flex items-center justify-center text-on-surface-variant">
                    <User size={16} />
                </div>
            </GlobalNav.Actions>
        </GlobalNav.Root>
    );
}
