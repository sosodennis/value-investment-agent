'use client';

import React from 'react';

function Root({ children, className = '' }: { children: React.ReactNode; className?: string }) {
    return (
        <div className={`flex flex-col h-[calc(100vh-4rem)] w-full bg-surface overflow-hidden font-body text-on-surface selection:bg-primary-container/30 ${className}`}>
            {children}
        </div>
    );
}

function Toolbar({ children, className = '' }: { children: React.ReactNode; className?: string }) {
    return (
        <header className={`h-16 w-full border-b border-outline-variant/20 bg-surface-container-low px-6 md:px-8 flex items-center justify-between z-10 ${className}`}>
            {children}
        </header>
    );
}

function Main({ children, className = '' }: { children: React.ReactNode; className?: string }) {
    return (
        <main className={`flex-1 overflow-hidden relative flex ${className}`}>
            {children}
        </main>
    );
}

function Sidebar({ children, className = '' }: { children: React.ReactNode; className?: string }) {
    return (
        <aside className={`h-full overflow-y-auto custom-scrollbar border-r border-outline-variant/20 bg-surface-container-lowest ${className}`}>
            {children}
        </aside>
    );
}

function Content({ children, className = '' }: { children: React.ReactNode; className?: string }) {
    return (
        <section className={`flex-1 h-full overflow-y-auto custom-scrollbar bg-surface relative flex flex-col ${className}`}>
            {children}
        </section>
    );
}

function Footer({ children, className = '' }: { children: React.ReactNode; className?: string }) {
    return (
        <footer className={`h-8 w-full bg-surface-container border-t border-outline-variant/20 px-8 flex items-center justify-between z-10 ${className}`}>
            {children}
        </footer>
    );
}

export const WorkspaceLayout = {
    Root,
    Toolbar,
    Main,
    Sidebar,
    Content,
    Footer
};
