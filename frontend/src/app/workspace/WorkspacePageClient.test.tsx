import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const navigation = vi.hoisted(() => ({ searchParams: new URLSearchParams() }));

vi.mock('next/navigation', () => ({ useSearchParams: () => navigation.searchParams }));
vi.mock('@/features/workspace/workspace-page', () => ({
    WorkspacePage: ({ initialPrompt, autoStart }: { initialPrompt?: string | null; autoStart?: boolean }) => (
        <div data-testid="workspace-props" data-prompt={initialPrompt ?? ''} data-auto-start={String(autoStart)} />
    ),
}));

import { WorkspacePageClient } from './WorkspacePageClient';

describe('WorkspacePageClient', () => {
    beforeEach(() => {
        navigation.searchParams = new URLSearchParams('prompt=%20Compare%20Apple%20and%20Microsoft%20&source=dashboard');
        window.history.pushState({ retained: true }, '', '/workspace?prompt=%20Compare%20Apple%20and%20Microsoft%20&source=dashboard');
    });

    afterEach(() => cleanup());

    it('hands the initial prompt to the workflow and removes only the one-time prompt query', async () => {
        render(<WorkspacePageClient />);

        const workspace = screen.getByTestId('workspace-props');
        expect(workspace.getAttribute('data-prompt')).toBe('Compare Apple and Microsoft');
        expect(workspace.getAttribute('data-auto-start')).toBe('true');

        await waitFor(() => expect(window.location.search).toBe('?source=dashboard'));
        expect(window.history.state).toEqual({ retained: true });
    });
});
