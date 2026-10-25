import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createWorkflowActivityState, parseWorkflowActivitySnapshot } from '@/features/workflow';
import type { AgentInfo } from '@/types/agents';
import { AgentWorkspaceTab } from './AgentWorkspaceTab';

afterEach(cleanup);

const agent: AgentInfo = {
    id: 'intent_extraction',
    name: 'Intent',
    role: 'Strategist',
    description: 'Resolve user intent.',
    avatar: '/agents/intent.png',
    status: 'attention',
};

describe('AgentWorkspaceTab ticker interaction', () => {
    it('renders the durable prompt and submits a typed answer bound to its activity', () => {
        const snapshot = parseWorkflowActivitySnapshot({
            thread_id: 'thread-1',
            run_id: 'run-1',
            run_status: 'waiting',
            cursor: 1,
            active_activities: [{
                activity_id: 'intent.clarifying',
                thread_id: 'thread-1',
                run_id: 'run-1',
                scope_path: ['intent_extraction', 'clarifying'],
                kind: 'node',
                status: 'waiting',
                label: 'Resolve ticker ambiguity',
                attempt: 1,
                interruption: {
                    interaction_id: 'interaction-1',
                    request: {
                        type: 'ticker_selection',
                        title: 'Ticker Resolution',
                        description: 'Choose the intended company.',
                        candidates: [{ symbol: 'GOOG', name: 'Alphabet Inc.', confidence: 0.91 }],
                    },
                },
            }],
            recent_activities: [],
        });
        const onResume = vi.fn(async () => undefined);

        render(<AgentWorkspaceTab
            agent={agent}
            workflow={createWorkflowActivityState(snapshot)}
            connectionState="connected"
            onResumeInteraction={onResume}
            isSubmitting={false}
        />);

        screen.getByText('Choose the intended company.');
        fireEvent.click(screen.getByRole('radio', { name: /GOOG/ }));
        fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
        expect(onResume).toHaveBeenCalledWith(
            expect.objectContaining({ activity_id: 'intent.clarifying' }),
            { type: 'ticker_selection', selected_symbol: 'GOOG' },
        );
    });
});
