import { useState } from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const navigation = vi.hoisted(() => ({ searchParams: new URLSearchParams() }));

vi.mock('next/navigation', () => ({ useSearchParams: () => navigation.searchParams }));
vi.mock('@/features/workspace/workspace-page', () => ({
    WorkspacePage: function WorkspacePage({ initialPrompt, autoStart }: { initialPrompt?: string | null; autoStart?: boolean }) {
        const [panel, setPanel] = useState('closed');
        return <div data-testid="workspace-props" data-prompt={initialPrompt ?? ''} data-auto-start={String(autoStart)} data-panel={panel}><button onClick={() => setPanel('open')}>Open workspace panel</button></div>;
    },
}));

import { WorkspacePageClient } from './WorkspacePageClient';

describe('WorkspacePageClient', () => {
    beforeEach(() => {
        navigation.searchParams = new URLSearchParams('prompt=%20Compare%20Apple%20and%20Microsoft%20&source=dashboard');
        window.history.pushState({ statementReadExpectation: { threadId: 'thread_1', artifactId: 'saved-1', editionIdentity: 'expected-edition' } }, '', '/workspace?prompt=%20Compare%20Apple%20and%20Microsoft%20&source=dashboard');
    });

    afterEach(() => cleanup());

    it('hands the initial prompt to the workflow and removes only the one-time prompt query', async () => {
        render(<WorkspacePageClient />);

        const workspace = screen.getByTestId('workspace-props');
        expect(workspace.getAttribute('data-prompt')).toBe('Compare Apple and Microsoft');
        expect(workspace.getAttribute('data-auto-start')).toBe('true');

        await waitFor(() => expect(window.location.search).toBe('?source=dashboard'));
        expect(window.history.state).toEqual({ statementReadExpectation: { threadId: 'thread_1', artifactId: 'saved-1', editionIdentity: 'expected-edition' } });
    });

    it('retains workspace state across saved frequency and period changes, and resets for another thread', () => {
        navigation.searchParams = new URLSearchParams('statement_thread=thread-1&statement_artifact=quarter-1&statement_frequency=quarter');
        const view = render(<WorkspacePageClient />);
        fireEvent.click(screen.getByRole('button', { name: 'Open workspace panel' }));
        navigation.searchParams = new URLSearchParams('statement_thread=thread-1&statement_artifact=ttm-1&statement_frequency=ttm&statement_period=returned-period');
        view.rerender(<WorkspacePageClient />);
        expect(screen.getByTestId('workspace-props').getAttribute('data-panel')).toBe('open');
        expect(screen.getByTestId('workspace-props').getAttribute('data-auto-start')).toBe('false');
        navigation.searchParams = new URLSearchParams('statement_thread=other-thread&statement_artifact=ttm-1&statement_frequency=ttm');
        view.rerender(<WorkspacePageClient />);
        expect(screen.getByTestId('workspace-props').getAttribute('data-panel')).toBe('closed');
    });
});
