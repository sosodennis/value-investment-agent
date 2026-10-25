import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AppShell } from './app-shell';
import { ThemeProvider } from '@/components/theme-provider';
import { TooltipProvider } from '@/components/ui/tooltip';

const mocks = vi.hoisted(() => ({
    pathname: '/workspace',
    replace: vi.fn(),
    signOut: vi.fn(),
}));

vi.mock('next/navigation', () => ({
    usePathname: () => mocks.pathname,
    useRouter: () => ({ replace: mocks.replace }),
}));

vi.mock('@/components/auth/AuthProvider', () => ({
    useAuth: () => ({
        user: {
            auth_type: 'session',
            email: 'preview@example.test',
            role: 'user',
            subject: 'preview-user',
            user_id: 'preview-user',
        },
        loading: false,
        signOut: mocks.signOut,
    }),
}));

afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    mocks.pathname = '/workspace';
    mocks.replace.mockReset();
    mocks.signOut.mockReset();
});

beforeEach(() => {
    vi.stubGlobal('matchMedia', (media: string) => ({
        matches: false,
        media,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
    }));
});

describe('AppShell', () => {
    it('opens mobile navigation and returns focus after Escape closes it', async () => {
        render(
            <ThemeProvider>
                <TooltipProvider>
                    <AppShell>
                        <main>Workspace content</main>
                    </AppShell>
                </TooltipProvider>
            </ThemeProvider>,
        );

        const trigger = screen.getByRole('button', { name: 'Open navigation' });
        fireEvent.click(trigger);

        const dialog = await screen.findByRole('dialog', { name: 'FinanceAI Lab' });
        expect(
            within(dialog).getByRole('link', { name: 'Workspace' }).getAttribute('aria-current'),
        ).toBe('page');
        expect(within(dialog).getByRole('link', { name: 'Markets' }).getAttribute('href')).toBe('/');

        fireEvent.keyDown(document, { key: 'Escape', keyCode: 27 });

        await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
        expect(document.activeElement).toBe(trigger);
    });

    it('keeps login and registration routes outside the private app navigation', () => {
        mocks.pathname = '/login';

        render(
            <ThemeProvider>
                <TooltipProvider>
                    <AppShell>
                        <main>Login content</main>
                    </AppShell>
                </TooltipProvider>
            </ThemeProvider>,
        );

        expect(screen.queryByRole('navigation', { name: 'Primary navigation' })).toBeNull();
        expect(screen.getByRole('main').textContent).toBe('Login content');
        expect(screen.getByRole('main').parentElement?.getAttribute('tabindex')).toBe('-1');
    });

    it('provides a focusable destination for the skip link', () => {
        render(
            <ThemeProvider>
                <TooltipProvider>
                    <AppShell>
                        <main>Workspace content</main>
                    </AppShell>
                </TooltipProvider>
            </ThemeProvider>,
        );

        const skipLink = screen.getByRole('link', { name: 'Skip to main content' });
        const destination = document.getElementById('main-content');

        expect(skipLink.getAttribute('href')).toBe('#main-content');
        expect(destination?.getAttribute('tabindex')).toBe('-1');
    });
});
