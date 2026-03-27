'use client';

import React, { createContext } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';

type GlobalNavContextValue = Record<string, never>;

const GlobalNavContext = createContext<GlobalNavContextValue>({});

function Root({ children }: { children: React.ReactNode }) {
    return (
        <GlobalNavContext.Provider value={{}}>
            <nav className="w-full sticky top-0 z-50 bg-surface-container-low/95 backdrop-blur shadow-[0_1px_0_0_rgba(255,255,255,0.05)] h-16 px-6 md:px-8 flex justify-between items-center font-headline text-sm tracking-tight">
                {children}
            </nav>
        </GlobalNavContext.Provider>
    );
}

function Logo() {
    return (
        <Link
            href="/"
            className="text-xl font-extrabold tracking-tighter text-primary-container focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-container/50 rounded"
        >
            Oracle AI
        </Link>
    );
}

function Links({ children }: { children: React.ReactNode }) {
    return <div className="hidden md:flex gap-6 items-center ml-8">{children}</div>;
}

function NavLink({ href, children }: { href: string; children: React.ReactNode }) {
    const pathname = usePathname();
    // Default to handling basic matching, with exact matches preferred for route highlights
    const isActive = pathname === href || (href !== '/' && pathname?.startsWith(href));

    return (
        <Link
            href={href}
            className={`transition-colors duration-200 ease-in-out focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-container/50 rounded px-1 pt-1 ${
                isActive
                    ? 'text-primary-container border-b-2 border-primary-container pb-1'
                    : 'text-on-surface-variant hover:text-on-surface border-b-2 border-transparent pb-1'
            }`}
        >
            {children}
        </Link>
    );
}

function Actions({ children }: { children: React.ReactNode }) {
    return <div className="flex items-center gap-4">{children}</div>;
}

export const GlobalNav = {
    Root,
    Logo,
    Links,
    Link: NavLink,
    Actions,
};
