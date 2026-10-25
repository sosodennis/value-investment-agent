import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ReportPanel, WorkspacePage } from './workspace-page';
import type { WorkflowActivityState } from '@/features/workflow';
import type { StandardAgentOutput } from '@/types/agents';

const hook = vi.hoisted(() => ({
    sendMessage: vi.fn(),
    submitCommand: vi.fn(),
    loadHistory: vi.fn(),
    cancelRun: vi.fn(),
    value: null as unknown,
}));

vi.mock('@/hooks/useAgent', () => ({ useAgent: () => hook.value }));

const runningWorkflow: WorkflowActivityState = {
    threadId: 'thread-1', runId: 'run-1', cursor: 4, runStatus: 'running',
    active: new Map(), eventIds: new Set(), connection: 'reconnecting', gapDetected: false,
    recent: [{ activity_id: 'fundamental_analysis', thread_id: 'thread-1', run_id: 'run-1', scope_path: ['fundamental_analysis'], kind: 'node', status: 'running', label: 'Loading financial reports', attempt: 1, progress: 45 }],
};

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
    afterEach(() => { cleanup(); vi.clearAllMocks(); });

    it('starts an analysis from the entered ticker and shows run progress and reconnect state', () => {
        hook.value = defaultHook({
            threadId: 'thread-1', runId: 'run-1', workflow: runningWorkflow,
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
            workflow: runningWorkflow,
            runId: 'run-1', cancelRun: hook.cancelRun,
        });
        render(<WorkspacePage />);
        screen.getByText('Analysis Service unavailable (HTTP 503).');
        fireEvent.click(screen.getByRole('button', { name: 'Cancel run' }));
        expect(hook.cancelRun).toHaveBeenCalledOnce();
    });

    it('renders output values only through the parsed output adapter', () => {
        const output: StandardAgentOutput = {
            kind: 'debate.output', version: 'v1', summary: 'Structured report parsed successfully.',
            preview: { verdict_display: 'Positive outlook', thesis_display: '0.82' },
        };
        render(<ReportPanel tab="debate" outputs={{ debate: output }} statuses={{ debate: 'done' }} ticker="AAPL" />);
        screen.getByText('Structured report parsed successfully.');
        screen.getByText('Positive outlook');
        screen.getByText('0.82');
    });
});
