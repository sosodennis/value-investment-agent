import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
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

const approvalActivity = {
    activity_id: 'fundamental.calculation',
    thread_id: 'thread-1',
    run_id: 'run-1',
    scope_path: ['fundamental_analysis', 'calculation'],
    kind: 'node',
    status: 'waiting',
    label: 'Review valuation assumptions',
    attempt: 1,
};
const approvalInteraction = {
    identity: {
        thread_id: 'thread-1',
        run_id: 'run-1',
        activity_id: 'fundamental.calculation',
        interaction_id: 'approval-1',
    },
    kind: 'valuation_approval',
    status: 'pending',
    request: {
        type: 'valuation_approval',
        contract_version: 'v1',
        ticker: 'AAPL',
        model_type: 'dcf_growth',
        title: 'Review valuation assumptions',
        description: 'Approve before deterministic calculation.',
        parameters: { wacc: 0.09, terminal_growth: 0.025 },
        audit_messages: ['PASS: assumptions are consistent'],
    },
};
const approvalWorkflow = workflowState({
    run_status: 'waiting',
    active_activities: [approvalActivity],
    recent_activities: [approvalActivity],
    pending_interactions: [approvalInteraction],
});

function defaultHook(overrides: Record<string, unknown> = {}) {
    return {
        messages: [], sendMessage: hook.sendMessage, submitCommand: hook.submitCommand,
        loadHistory: hook.loadHistory, isLoading: false, isSubmittingInteraction: false, error: null, threadId: null,
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

    it('keeps backend retry and resume attempt counts out of user-facing activity', () => {
        hook.value = defaultHook({
            workflow: workflowState({
                recent_activities: [{
                    activity_id: 'fundamental_analysis',
                    thread_id: 'thread-1',
                    run_id: 'run-1',
                    scope_path: ['fundamental_analysis'],
                    kind: 'node',
                    status: 'running',
                    label: 'Loading financial reports',
                    attempt: 4,
                }],
            }),
        });
        render(<WorkspacePage />);

        expect(screen.getByText('Loading financial reports')).toBeTruthy();
        expect(screen.queryByText(/attempt\s+4/i)).toBeNull();
    });

    it('shows the live SSE connection state beside the activity cursor', () => {
        hook.value = defaultHook({
            workflow: workflowState(),
            connectionState: 'connected',
        });
        render(<WorkspacePage />);

        expect(screen.getByText('Connection Live · activity cursor 4')).toBeTruthy();
    });

    it('shows one latest row for nested callbacks representing the same workflow step', () => {
        hook.value = defaultHook({
            workflow: workflowState({
                recent_activities: [
                    {
                        activity_id: 'extraction-child',
                        parent_activity_id: 'extraction-parent',
                        thread_id: 'thread-1',
                        run_id: 'run-1',
                        scope_path: ['intent_extraction', 'extraction'],
                        kind: 'node',
                        status: 'completed',
                        label: 'Extracting company intent',
                        attempt: 1,
                    },
                    {
                        activity_id: 'extraction-parent',
                        thread_id: 'thread-1',
                        run_id: 'run-1',
                        scope_path: ['intent_extraction', 'extraction'],
                        kind: 'node',
                        status: 'completed',
                        label: 'Extracting company intent',
                        attempt: 1,
                    },
                    {
                        activity_id: 'extraction-child',
                        parent_activity_id: 'extraction-parent',
                        thread_id: 'thread-1',
                        run_id: 'run-1',
                        scope_path: ['intent_extraction', 'extraction'],
                        kind: 'node',
                        status: 'running',
                        label: 'Extracting company intent',
                        attempt: 1,
                    },
                    {
                        activity_id: 'extraction-parent',
                        thread_id: 'thread-1',
                        run_id: 'run-1',
                        scope_path: ['intent_extraction', 'extraction'],
                        kind: 'node',
                        status: 'running',
                        label: 'Extracting company intent',
                        attempt: 1,
                    },
                ],
            }),
        });
        render(<WorkspacePage />);

        const activityList = within(screen.getByRole('list', { name: 'Workflow activity' }));
        expect(activityList.getAllByText('Extracting company intent')).toHaveLength(1);
        expect(activityList.getByText('completed')).toBeTruthy();
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

    it('shows versioned approval inline in the waiting activity and preserves it across report navigation', () => {
        hook.value = defaultHook({
            workflow: approvalWorkflow,
            threadId: 'thread-1',
            runId: 'run-1',
        });
        render(<WorkspacePage />);

        const activityItems = within(screen.getByRole('list', { name: 'Workflow activity' })).getAllByRole('listitem');
        const activityItem = activityItems[0];
        if (!activityItem) throw new Error('Waiting activity row was not rendered.');
        expect(within(activityItem).getAllByText('Review valuation assumptions').length).toBeGreaterThanOrEqual(2);
        expect(within(activityItem).getByText('AAPL · dcf_growth')).toBeTruthy();
        expect(within(activityItem).getByText('PASS: assumptions are consistent')).toBeTruthy();
        expect(within(activityItem).getByText('Validated parameters (2)')).toBeTruthy();
        expect(within(activityItem).getByRole('button', { name: 'Approve valuation' })).toBeTruthy();
        expect(screen.queryByRole('dialog')).toBeNull();

        fireEvent.click(screen.getByRole('tab', { name: 'Fundamental' }));
        fireEvent.click(screen.getByRole('tab', { name: 'Activity' }));
        expect(screen.getByRole('button', { name: 'Approve valuation' })).toBeTruthy();
        fireEvent.click(screen.getByRole('button', { name: 'Approve valuation' }));
        expect(hook.submitCommand).toHaveBeenCalledWith(
            expect.objectContaining({ kind: 'valuation_approval' }),
            { type: 'valuation_approval', contract_version: 'v1', decision: 'approve' },
        );
    });

    it('renders safe typed failure provenance for a failed run', () => {
        hook.value = defaultHook({
            workflow: workflowState({
                run_status: 'failed',
                failure: {
                    code: 'schema_validation_failed',
                    owner: 'llm_provider',
                    activity_id: 'intent.extraction',
                    retryable: false,
                    message: 'The provider returned data that did not match the workflow contract.',
                },
                recent_activities: [{ ...tickerActivity, status: 'failed' }],
            }),
        });
        render(<WorkspacePage />);
        screen.getByText('The provider returned data that did not match the workflow contract.');
        screen.getByText(/schema_validation_failed/);
        screen.getByText(/Retry is not expected/);
    });

    it('loads the exact run requested by a recent-analysis link', () => {
        hook.value = defaultHook();
        render(<WorkspacePage routeIntent={{ kind: 'exact-run', threadId: 'thread-1', runId: 'run-1' }} />);
        expect(hook.loadHistory).toHaveBeenCalledWith('thread-1', 'run-1');
    });

    it('keeps an unavailable exact history link in an explicit error state', () => {
        hook.value = defaultHook({ error: 'History unavailable.' });
        render(<WorkspacePage routeIntent={{ kind: 'exact-run', threadId: 'thread-1', runId: 'missing-run' }} />);
        expect(hook.loadHistory).toHaveBeenCalledWith('thread-1', 'missing-run');
        screen.getByRole('alert');
        screen.getByText(/selected analysis run could not be loaded/i);
        screen.getByText('The selected historical run is unavailable.');
        expect(screen.queryByText('Loading the selected historical run.')).toBeNull();
        expect(screen.queryByRole('button', { name: 'Start analysis' })).toBeNull();
        expect(hook.sendMessage).not.toHaveBeenCalled();
    });

    it('rejects an incomplete history link without loading or starting an analysis', () => {
        hook.value = defaultHook();
        render(<WorkspacePage routeIntent={{ kind: 'invalid-history' }} initialTicker="AAPL" autoStart />);
        screen.getByText(/history link must include both a thread id and a run id/i);
        expect(screen.queryByRole('button', { name: 'Start analysis' })).toBeNull();
        expect(hook.loadHistory).not.toHaveBeenCalled();
        expect(hook.sendMessage).not.toHaveBeenCalled();
    });

    it('does not auto-start when an exact run link also contains a ticker', () => {
        hook.value = defaultHook();
        render(<WorkspacePage routeIntent={{ kind: 'exact-run', threadId: 'thread-1', runId: 'run-1' }} initialTicker="AAPL" autoStart />);
        expect(hook.loadHistory).toHaveBeenCalledWith('thread-1', 'run-1');
        expect(hook.sendMessage).not.toHaveBeenCalled();
    });

    it('starts an initial research prompt without rewriting it as a ticker valuation command', () => {
        hook.value = defaultHook();
        const prompt = 'What are the main risks to Apple\'s valuation?';
        render(<WorkspacePage initialPrompt={prompt} autoStart />);
        expect(hook.sendMessage).toHaveBeenCalledWith(prompt, true);
    });

    it('renders a typed ticker interaction outside the activity projection and submits its identity', () => {
        vi.stubGlobal('ResizeObserver', class {
            observe() {}
            unobserve() {}
            disconnect() {}
        });
        hook.value = defaultHook({ workflow: waitingWorkflow, isLoading: true });
        render(<WorkspacePage />);

        const aaplOption = screen.getByRole('radio', { name: /AAPL Apple Inc\./ });
        expect(aaplOption.hasAttribute('disabled')).toBe(false);
        fireEvent.click(aaplOption);
        fireEvent.click(screen.getByRole('button', { name: 'Continue with AAPL' }));

        expect(hook.submitCommand).toHaveBeenCalledWith(waitingInteraction, {
            type: 'ticker_selection',
            selected_symbol: 'AAPL',
        });
    });

    it('disables a pending ticker interaction only while its response is submitting', () => {
        vi.stubGlobal('ResizeObserver', class {
            observe() {}
            unobserve() {}
            disconnect() {}
        });
        hook.value = defaultHook({ workflow: waitingWorkflow, isLoading: true, isSubmittingInteraction: true });
        render(<WorkspacePage />);

        expect(screen.getByRole('radio', { name: /AAPL Apple Inc\./ }).hasAttribute('disabled')).toBe(true);
        expect(screen.getByRole('button', { name: 'Continue with selected company' }).hasAttribute('disabled')).toBe(true);
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

    it('keeps the desktop workbench resizable and exposes selected report evidence', () => {
        const output: StandardAgentOutput = {
            kind: 'debate.output', version: 'v1', summary: 'Evidence-backed debate.',
            preview: { verdict_display: 'Positive outlook', thesis_display: '0.82' },
            reference: { artifact_id: 'artifact-debate-1', download_url: '/api/v1/artifacts/artifact-debate-1', type: 'debate' },
        };
        hook.value = defaultHook({
            agentOutputs: { debate: output },
            agentStatuses: { debate: 'done' },
            workflow: workflowState({ run_status: 'completed' }),
        });
        render(<WorkspacePage />);

        expect(screen.getAllByRole('separator', { name: 'Resize workspace panel' })).toHaveLength(2);
        fireEvent.click(screen.getByRole('tab', { name: 'Debate' }));
        fireEvent.click(screen.getByRole('button', { name: /Verdict Display/i }));

        expect(screen.getByRole('heading', { name: 'Evidence inspector' })).toBeTruthy();
        expect(screen.getByText('Artifact artifact-debate-1')).toBeTruthy();
        expect(screen.getByText('This exact run')).toBeTruthy();
        fireEvent.click(screen.getByRole('tab', { name: 'Activity' }));
        expect(screen.getAllByText('Positive outlook').length).toBeGreaterThanOrEqual(2);
        expect(screen.getByText('Artifact artifact-debate-1')).toBeTruthy();
    });

    it('opens evidence details from the mobile evidence sheet', () => {
        hook.value = defaultHook({
            agentOutputs: {
                debate: {
                    kind: 'debate.output', version: 'v1', summary: 'Evidence-backed debate.',
                    preview: { verdict_display: 'Positive outlook' },
                },
            },
            agentStatuses: { debate: 'done' },
        });
        render(<WorkspacePage />);
        fireEvent.click(screen.getByRole('button', { name: 'Evidence' }));
        const dialog = screen.getByRole('dialog');
        expect(dialog).toBeTruthy();
        expect(within(dialog).getByText('Evidence inspector')).toBeTruthy();
    });
});
