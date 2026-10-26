import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
    createWorkflowActivityState,
    parseWorkflowActivitySnapshot,
    type WorkflowActivityState,
} from '@/features/workflow';
import { ReportPanel, WorkspacePage } from './workspace-page';
import type { StandardAgentOutput } from '@/types/agents';

const hook = vi.hoisted(() => ({
    sendMessage: vi.fn(),
    submitCommand: vi.fn(),
    loadHistory: vi.fn(),
    cancelRun: vi.fn(),
    value: null as unknown,
}));

vi.mock('@/hooks/useAgent', () => ({ useAgent: () => hook.value }));

function workflowState(overrides: Record<string, unknown> = {}): WorkflowActivityState {
    return createWorkflowActivityState(parseWorkflowActivitySnapshot({
        thread_id: 'thread-1',
        run_id: 'run-1',
        run_status: 'running',
        cursor: 4,
        active_activities: [],
        recent_activities: [{
            activity_id: 'fundamental_analysis',
            thread_id: 'thread-1',
            run_id: 'run-1',
            scope_path: ['fundamental_analysis'],
            kind: 'node',
            status: 'running',
            label: 'Loading financial reports',
            attempt: 1,
            progress: 45,
        }],
        pending_interactions: [],
        completed_outputs: [],
        ...overrides,
    }));
}

const tickerActivity = {
    activity_id: 'intent-selection',
    thread_id: 'thread-1',
    run_id: 'run-1',
    scope_path: ['intent_extraction'],
    kind: 'subgraph',
    status: 'waiting',
    label: 'Choose a company',
    attempt: 1,
};

const tickerInteraction = {
    identity: {
        thread_id: 'thread-1',
        run_id: 'run-1',
        activity_id: 'intent-selection',
        interaction_id: 'interaction-1',
    },
    kind: 'ticker_selection',
    status: 'pending',
    request: {
        type: 'ticker_selection',
        title: 'Choose the company',
        description: 'Select the intended ticker.',
        candidates: [
            { symbol: 'AAPL', name: 'Apple Inc.', exchange: 'NASDAQ', type: 'Common Stock', confidence: 0.9 },
            { symbol: 'APLE', name: 'Apple Hospitality REIT', exchange: 'NYSE', type: 'REIT', confidence: 0.6 },
        ],
    },
};

const waitingWorkflow = workflowState({
    run_status: 'waiting',
    active_activities: [tickerActivity],
    recent_activities: [tickerActivity],
    pending_interactions: [tickerInteraction],
});

const waitingInteraction = [...waitingWorkflow.interactions.values()].find(
    (item) => item.identity.interaction_id === 'interaction-1',
);
if (!waitingInteraction) throw new Error('Ticker selection fixture failed to parse.');

function defaultHook(overrides: Record<string, unknown> = {}) {
    return {
        messages: [], sendMessage: hook.sendMessage, submitCommand: hook.submitCommand,
        loadHistory: hook.loadHistory, isLoading: false, error: null, threadId: null,
        runId: null, connectionState: 'disconnected', cancelRun: hook.cancelRun,
        hasMore: false, agentStatuses: {}, agentOutputs: {}, workflow: null,
        activeActivities: [], ...overrides,
    };
}

describe('WorkspacePage', () => {
    afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.clearAllMocks(); });

    it('starts an analysis from the entered ticker and shows run progress and reconnect state', () => {
        hook.value = defaultHook({
            threadId: 'thread-1', runId: 'run-1', workflow: { ...workflowState(), connection: 'reconnecting' },
            connectionState: 'reconnecting', agentStatuses: { fundamental_analysis: 'running' },
        });
        render(<WorkspacePage />);
        fireEvent.change(screen.getByLabelText('Company ticker'), { target: { value: 'msft' } });
        fireEvent.click(screen.getByRole('button', { name: 'Start analysis' }));
        expect(hook.sendMessage).toHaveBeenCalledWith('Valuate MSFT', true);
        expect(screen.getByText('Loading financial reports')).toBeTruthy();
        expect(screen.getByText('Reconnecting')).toBeTruthy();
        expect(screen.getByText('Running')).toBeTruthy();
    });

    it('shows actionable failure details and cancellation state', () => {
        hook.value = defaultHook({
            error: 'Analysis Service unavailable (HTTP 503).',
            workflow: workflowState(),
            runId: 'run-1', cancelRun: hook.cancelRun,
        });
        render(<WorkspacePage />);
        screen.getByText('Analysis Service unavailable (HTTP 503).');
        fireEvent.click(screen.getByRole('button', { name: 'Cancel run' }));
        expect(hook.cancelRun).toHaveBeenCalledOnce();
    });

    it('renders completed and cancelled run states explicitly', () => {
        hook.value = defaultHook({ workflow: workflowState({ run_status: 'completed' }) });
        const { rerender } = render(<WorkspacePage />);
        screen.getByText('Run completed');

        hook.value = defaultHook({ workflow: workflowState({ run_status: 'cancelled' }) });
        rerender(<WorkspacePage />);
        screen.getByText('Run cancelled');
    });

    it('loads the exact run requested by a recent-analysis link', () => {
        hook.value = defaultHook();
        render(<WorkspacePage initialThreadId="thread-1" expectedRunId="run-1" />);
        expect(hook.loadHistory).toHaveBeenCalledWith('thread-1', 'run-1');
    });

    it('does not start a new run when an exact history link is unavailable', () => {
        hook.value = defaultHook({ error: 'History unavailable.' });
        render(<WorkspacePage initialThreadId="thread-1" expectedRunId="missing-run" autoStart={false} />);
        expect(hook.loadHistory).toHaveBeenCalledWith('thread-1', 'missing-run');
        expect(hook.sendMessage).not.toHaveBeenCalled();
    });

    it('renders a typed ticker interaction outside the activity projection and submits its identity', () => {
        vi.stubGlobal('ResizeObserver', class {
            observe() {}
            unobserve() {}
            disconnect() {}
        });
        hook.value = defaultHook({ workflow: waitingWorkflow });
        render(<WorkspacePage />);

        fireEvent.click(screen.getByRole('radio', { name: /AAPL Apple Inc\./ }));
        fireEvent.click(screen.getByRole('button', { name: 'Continue with AAPL' }));

        expect(hook.submitCommand).toHaveBeenCalledWith(waitingInteraction, {
            type: 'ticker_selection',
            selected_symbol: 'AAPL',
        });
    });

    it('shows waiting as unavailable when the snapshot has no pending interaction', () => {
        hook.value = defaultHook({ workflow: workflowState({ run_status: 'waiting' }) });
        render(<WorkspacePage />);
        screen.getByText('The workflow is waiting for an interaction request that is not available in this activity snapshot.');
        expect(screen.queryByRole('button', { name: /Continue with/ })).toBeNull();
    });

    it('renders the parsed output summary and the specialized report renderer', () => {
        const output: StandardAgentOutput = {
            kind: 'debate.output', version: 'v1', summary: 'Structured report parsed successfully.',
            preview: { verdict_display: 'Positive outlook', thesis_display: '0.82' },
        };
        render(<ReportPanel tab="debate" outputs={{ debate: output }} statuses={{ debate: 'done' }} ticker="AAPL" />);
        screen.getByText('Structured report parsed successfully.');
        screen.getByText('Debate Council');
        screen.getByText('Verdict Summary (Simulation)');
        screen.getByText(/Positive outlook/);
    });
});
