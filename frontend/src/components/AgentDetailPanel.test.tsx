import { render, screen, fireEvent } from '@testing-library/react';
import { AgentDetailPanel } from './AgentDetailPanel';
import { AgentInfo } from '../types/agents';
import { describe, it, expect } from 'vitest';
import React from 'react';

const mockAgent: AgentInfo = {
    id: 'test_agent',
    name: 'Test Agent',
    description: 'A test agent',
    avatar: '/avatar.png',
    status: 'idle',
    role: 'Test Role'
};

describe('AgentDetailPanel Tab Switching', () => {
    it('keeps all tabs mounted and toggles visibility', () => {
        render(<AgentDetailPanel agent={mockAgent} messages={[]} />);

        // Workspace tab content identifier
        const workspaceHeader = screen.getByText('Active Workspace');
        // The container div is the grandparent or great-grandparent.
        // Looking at code: <div class="..."> <section> ... <h3 ...>Active Workspace</h3> ...
        // So closest('.p-8') should work as the container has p-8.
        const workspaceTab = workspaceHeader.closest('.p-8');

        // Score tab content identifier
        const scoreHeader = screen.getByText('Analysis Dimensions');
        // Use space-y-8 to distinguish from inner section which also has p-8
        const scoreTab = scoreHeader.closest('.space-y-8');

        // Initial state: Workspace active
        expect(workspaceTab).toBeTruthy();
        expect(workspaceTab?.className).toContain('block');
        expect(workspaceTab?.className).not.toContain('hidden');

        expect(scoreTab).toBeTruthy();
        expect(scoreTab?.className).toContain('hidden');

        // Switch to Score tab
        // Find the button "Score" (uppercase in UI "Score")
        const scoreButton = screen.getByRole('button', { name: /Score/i });
        fireEvent.click(scoreButton);

        // Check visibility
        expect(workspaceTab?.className).toContain('hidden');
        expect(scoreTab?.className).toContain('block');
        expect(scoreTab?.className).not.toContain('hidden');
    });
});
