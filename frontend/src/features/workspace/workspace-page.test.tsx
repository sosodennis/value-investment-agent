import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SWRConfig } from 'swr';
import {
    createWorkflowActivityState,
    parseWorkflowActivitySnapshot,
    type WorkflowActivityState,
} from '@/features/workflow';
import { ReportPanel, WorkspacePage } from './workspace-page';
import type { StandardAgentOutput } from '@/types/agents';
import { reference, uncertaintyReport } from './outputs/fundamental-analysis/fundamental-report.test-fixtures';
import { deferred, editableReport, revisedReport } from './outputs/fundamental-analysis/valuation-revision.test-fixtures';

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

describe('Workspace Fundamental revision lifecycle', () => {
    afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.clearAllMocks(); });

    async function startRevision(candidate: unknown) {
        Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1440 });
        const source = editableReport();
        const candidateReference = { ...reference, artifact_id: 'report-2', download_url: '/api/v1/artifacts/report-2?run_id=run-2' };
        const output: StandardAgentOutput = { kind: 'fundamental_analysis.output', version: 'v1', summary: 'Saved valuation.', reference };
        const candidateOutput: StandardAgentOutput = { ...output, reference: candidateReference };
        vi.stubGlobal('fetch', vi.fn((url: string) => Promise.resolve(new Response(JSON.stringify({
            kind: 'financial_reports', version: 'v1', produced_by: 'fundamental_analysis', created_at: '2026-11-23T00:00:00Z',
            data: { ticker: 'EXAMPLE', model_type: 'fcff_dcf', status: 'done', financial_reports: [], fundamental_service: url === reference.download_url ? source : candidate },
        }), { status: 200 }))));
        const pending = deferred<{ kind: 'started'; threadId: string; runId: string }>();
        hook.sendMessage.mockReturnValueOnce(pending.promise);
        hook.value = defaultHook({ threadId: 'thread-1', runId: 'run-1', agentOutputs: { fundamental_analysis: output }, agentStatuses: { fundamental_analysis: 'done' } });
        const cache = new Map();
        const page = () => <SWRConfig value={{ provider: () => cache }}><WorkspacePage /></SWRConfig>;
        const { rerender } = render(page());
        fireEvent.mouseDown(screen.getByRole('tab', { name: 'Fundamental' }), { button: 0, ctrlKey: false });
        await screen.findByLabelText('Terminal growth (%)');
        fireEvent.change(screen.getByLabelText('Terminal growth (%)'), { target: { value: '2.5' } });
        fireEvent.change(screen.getByLabelText('Reason for change'), { target: { value: 'Updated outlook.' } });
        expect(hook.sendMessage).not.toHaveBeenCalled();
        fireEvent.click(screen.getByRole('button', { name: 'Recalculate' }));
        expect(hook.sendMessage.mock.calls[0]?.[2].revision.value).toBe('0.025');
        return {
            pending,
            showRun: (overrides: Record<string, unknown> = {}) => {
                hook.value = defaultHook({ threadId: 'thread-1', runId: 'run-2', agentOutputs: { fundamental_analysis: candidateOutput }, agentStatuses: { fundamental_analysis: 'done' }, ...overrides });
                rerender(page());
            },
        };
    }

    it('keeps the draft and previous result through pending, then adopts only the parsed matching manual report', async () => {
        const { pending, showRun } = await startRevision(revisedReport());
        showRun({ connectionState: 'reconnecting', isLoading: true });
        within(screen.getByRole('article', { name: 'Fundamental valuation report' })).getByText('USD 25.12 / share');
        expect(screen.getByLabelText('Terminal growth (%)')).toHaveProperty('value', '2.5');
        expect(screen.getByRole('button', { name: 'Recalculating…' }).hasAttribute('disabled')).toBe(true);
        expect(screen.queryByText('USD 168.92 / share')).toBeNull();
        showRun();
        await act(async () => pending.resolve({ kind: 'started', threadId: 'thread-1', runId: 'run-2' }));
        const comparison = await screen.findByRole('region', { name: 'Revision comparison' });
        within(comparison).getByText('USD 25.12 / share');
        within(comparison).getByText('USD 168.92 / share');
        within(comparison).getByText('USD 150.00 / share');
        screen.getByText('Revised and manual reports are read-only. Start from an original automatic report for one revision.');
        expect(screen.queryByLabelText('Terminal growth (%)')).toBeNull();
        fireEvent.click(within(comparison).getAllByRole('button', { name: 'Inspect Deterministic base per share' })[0]);
        const inspector = within(screen.getByLabelText('Evidence inspector'));
        expect(inspector.getByLabelText('Original value · full precision')).toHaveProperty('value', '25.1234567890123456789');
        inspector.getByText('run-1');
        fireEvent.click(within(comparison).getAllByRole('button', { name: 'Inspect Deterministic base per share' })[1]);
        expect(inspector.getByLabelText('Original value · full precision')).toHaveProperty('value', '168.92123456789');
        inspector.getByText('run-2');
    });

    it('retains the previous artifact and draft after a service policy refusal without accepting a new valuation', async () => {
        const { pending, showRun } = await startRevision({ projection_type: 'degraded', contract_version: 'fundamental.v1', valuation_status: 'service_unavailable', quality_status: 'degraded', issue_codes: ['MANUAL_OVERRIDE_INVALID'], service_failure: { code: 'MANUAL_OVERRIDE_INVALID', message: 'Terminal growth must be at most 0.04.', retryable: false } });
        showRun();
        await act(async () => pending.resolve({ kind: 'started', threadId: 'thread-1', runId: 'run-2' }));
        await screen.findByText('MANUAL_OVERRIDE_INVALID · Terminal growth must be at most 0.04.');
        within(screen.getByRole('article', { name: 'Fundamental valuation report' })).getByText('USD 25.12 / share');
        expect(screen.getByLabelText('Terminal growth (%)')).toHaveProperty('value', '2.5');
        expect(screen.getByLabelText('Reason for change')).toHaveProperty('value', 'Updated outlook.');
        expect(screen.getByRole('button', { name: 'Recalculate' }).hasAttribute('disabled')).toBe(true);
        expect(screen.queryByRole('region', { name: 'Revision comparison' })).toBeNull();
    });

    it.each(['wrong value', 'wrong origin', 'parser failure'])('keeps the old report when a new artifact has %s', async (failure) => {
        const candidate = revisedReport(failure === 'wrong value' ? '0.03' : '0.025');
        if (failure === 'wrong origin' && candidate.automatic_preparation) {
            for (const assumption of candidate.automatic_preparation.assumptions_evidence) {
                if (assumption.manual_provenance) assumption.manual_provenance.automatic_preparation_digest = 'f'.repeat(64);
            }
        }
        const { pending, showRun } = await startRevision(failure === 'parser failure' ? {} : candidate);
        showRun();
        await act(async () => pending.resolve({ kind: 'started', threadId: 'thread-1', runId: 'run-2' }));
        await screen.findByText(/REVISION_RESULT_UNCONFIRMED|REVISION_ARTIFACT_ERROR/);
        within(screen.getByRole('article', { name: 'Fundamental valuation report' })).getByText('USD 25.12 / share');
        expect(screen.queryByRole('region', { name: 'Revision comparison' })).toBeNull();
        expect(screen.queryByText('USD 168.92 / share')).toBeNull();
    });

    it('ignores a late successful request after switching to a different thread', async () => {
        const { pending, showRun } = await startRevision(revisedReport());
        showRun({ threadId: 'thread-other', runId: 'run-other', agentOutputs: {}, agentStatuses: {} });
        await act(async () => pending.resolve({ kind: 'started', threadId: 'thread-1', runId: 'run-2' }));
        expect(screen.queryByRole('region', { name: 'Revision comparison' })).toBeNull();
        expect(screen.queryByText('USD 168.92 / share')).toBeNull();
        expect(screen.queryByText('USD 25.12 / share')).toBeNull();
    });
});

const waitingInteraction = [...waitingWorkflow.interactions.values()].find(
    (item) => item.identity.interaction_id === 'interaction-1',
);
if (!waitingInteraction) throw new Error('Ticker selection fixture failed to parse.');

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
        expect(hook.sendMessage).toHaveBeenCalledWith('Valuate MSFT', true, {
            contract_version: 'fundamental.v1',
            assumptions: {},
            uncertainty: { mode: 'monte_carlo' },
        });
        expect(screen.getByText('Loading financial reports')).toBeTruthy();
        expect(screen.getByText('Reconnecting')).toBeTruthy();
        expect(screen.getByText('Running')).toBeTruthy();
    });

    it('exposes one automatic analysis action without a caller-owned assumptions form', () => {
        hook.value = defaultHook();
        render(<WorkspacePage />);
        fireEvent.change(screen.getByLabelText('Company ticker'), { target: { value: 'aapl' } });
        expect(screen.getAllByRole('button', { name: 'Start analysis' })).toHaveLength(1);
        expect(screen.queryByRole('button', { name: 'Start valuation' })).toBeNull();
        expect(screen.queryByLabelText('Base revenue')).toBeNull();
        fireEvent.click(screen.getByRole('button', { name: 'Start analysis' }));

        expect(hook.sendMessage).toHaveBeenCalledWith(
            'Valuate AAPL',
            true,
            {
                contract_version: 'fundamental.v1',
                assumptions: {},
                uncertainty: { mode: 'monte_carlo' },
            },
        );
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
        expect(hook.sendMessage).toHaveBeenCalledWith(prompt, true, {
            contract_version: 'fundamental.v1',
            assumptions: {},
            uncertainty: { mode: 'monte_carlo' },
        });
    });

    it('uses the same valuation request for automatic and manual ticker starts', () => {
        hook.value = defaultHook();
        const { unmount } = render(<WorkspacePage initialTicker="aapl" autoStart />);
        const automaticCall = hook.sendMessage.mock.calls[0];
        unmount();
        hook.sendMessage.mockClear();

        render(<WorkspacePage initialTicker="aapl" />);
        fireEvent.click(screen.getByRole('button', { name: 'Start analysis' }));

        expect(hook.sendMessage.mock.calls[0]).toEqual(automaticCall);
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
        Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1440 });
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

    it('opens the mobile evidence sheet when a report value is selected', async () => {
        Object.defineProperty(window, 'innerWidth', { configurable: true, value: 390 });
        hook.value = defaultHook({
            agentOutputs: {
                debate: {
                    kind: 'debate.output', version: 'v1', summary: 'Evidence-backed debate.',
                    preview: { verdict_display: 'Positive outlook' },
                    reference: { artifact_id: 'artifact-debate-1', download_url: '/api/v1/artifacts/artifact-debate-1', type: 'debate' },
                },
            },
            agentStatuses: { debate: 'done' },
        });
        render(<WorkspacePage />);

        fireEvent.click(screen.getByRole('tab', { name: 'Debate' }));
        const evidenceButton = screen.getByRole('button', { name: /Verdict Display/i });
        evidenceButton.focus();
        fireEvent.click(evidenceButton);

        const dialog = screen.getByRole('dialog');
        expect(within(dialog).getByText('Evidence inspector')).toBeTruthy();
        expect(within(dialog).getByText('Debate Arena summary')).toBeTruthy();
        fireEvent.click(within(dialog).getByRole('button', { name: 'Close evidence inspector' }));
        await waitFor(() => expect(document.activeElement).toBe(evidenceButton));
    });
    it.each([390, 1440])('uses the loaded Fundamental inventory in the inspector at %spx and clears selection for another run', async (width) => {
        Object.defineProperty(window, 'innerWidth', { configurable: true, value: width });
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
            kind: 'financial_reports', version: 'v1', produced_by: 'fundamental_analysis', created_at: '2026-11-23T00:00:00Z',
            data: { ticker: 'EXAMPLE', model_type: 'fcff_dcf', status: 'done', financial_reports: [], fundamental_service: uncertaintyReport() },
        }), { status: 200 })));
        const cache = new Map();
        const page = () => <SWRConfig value={{ provider: () => cache }}><WorkspacePage /></SWRConfig>;
        hook.value = defaultHook({ threadId: 'thread-1', runId: 'run-1', agentOutputs: {
            fundamental_analysis: { kind: 'fundamental_analysis.output', version: 'v1', summary: 'Loaded valuation.', reference },
        }, agentStatuses: { fundamental_analysis: 'done' } });
        const { rerender } = render(page());
        fireEvent.mouseDown(screen.getByRole('tab', { name: 'Fundamental' }), { button: 0, ctrlKey: false });
        fireEvent.click(await screen.findByText('All financial facts (1)'));
        const fact = screen.getByRole('button', { name: 'Inspect Service fact · revenue' });
        fact.focus();
        fireEvent.click(fact);
        const inspector = width < 1440
            ? within(screen.getByRole('dialog')).getByLabelText('Evidence inspector')
            : screen.getByLabelText('Evidence inspector');
        fireEvent.click(within(inspector).getByText(/Browse all evidence/));
        await waitFor(() => expect(within(inspector).getByRole('button', { name: /Assumption · assumptions.wacc/ })).toBeTruthy());
        within(inspector).getByText('Fact ID');
        fireEvent.click(within(inspector).getByRole('button', { name: /Calculation · equity_value/ }));
        within(inspector).getByText('enterprise_value, cash, debt');
        within(inspector).getByText('run-1');
        if (width < 1440) {
            fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Close evidence inspector' }));
            await waitFor(() => expect(document.activeElement).toBe(fact));
        }
        hook.value = defaultHook({ threadId: 'thread-2', runId: 'run-2', agentStatuses: { fundamental_analysis: 'running' } });
        rerender(page());
        const currentInspector = screen.getByLabelText('Evidence inspector');
        expect(within(currentInspector).queryByText('Inputs')).toBeNull();
        expect(within(currentInspector).queryByRole('button', { name: /Calculation · equity_value/ })).toBeNull();
    });
    it('recalculates from the saved source in the same thread and labels its retained result', async () => {
        const source = editableReport();
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
            kind: 'financial_reports', version: 'v1', produced_by: 'fundamental_analysis', created_at: '2026-11-23T00:00:00Z',
            data: { ticker: 'EXAMPLE', model_type: 'fcff_dcf', status: 'done', financial_reports: [], fundamental_service: source },
        }), { status: 200 })));
        const pending = deferred<{ kind: 'started'; threadId: string; runId: string }>();
        hook.sendMessage.mockReturnValueOnce(pending.promise);
        hook.value = defaultHook({ threadId: 'thread-1', runId: 'run-1', agentOutputs: {
            fundamental_analysis: { kind: 'fundamental_analysis.output', version: 'v1', reference },
        }, agentStatuses: { fundamental_analysis: 'done' } });
        const cache = new Map();
        const page = () => <SWRConfig value={{ provider: () => cache }}><WorkspacePage /></SWRConfig>;
        const { rerender } = render(page());
        fireEvent.mouseDown(screen.getByRole('tab', { name: 'Fundamental' }), { button: 0, ctrlKey: false });
        await screen.findByLabelText('Terminal growth (%)');
        fireEvent.change(screen.getByLabelText('Company ticker'), { target: { value: 'WRONG' } });
        fireEvent.change(screen.getByLabelText('Terminal growth (%)'), { target: { value: '2.51234567890123456789' } });
        fireEvent.change(screen.getByLabelText('Reason for change'), { target: { value: 'Updated long-term outlook.' } });
        fireEvent.click(screen.getByRole('button', { name: 'Recalculate' }));
        expect(hook.sendMessage).toHaveBeenCalledWith('Recalculate EXAMPLE valuation from its saved report', false, {
            contract_version: 'fundamental.v1', revision: { source: { thread_id: 'thread-1', run_id: 'run-1', artifact_id: 'report-1', preparation_digest: source.automatic_preparation?.preparation_digest }, path: 'assumptions.terminal_growth', value: '0.0251234567890123456789', reason: 'Updated long-term outlook.' },
        });
        screen.getByText('Previous result');
        hook.value = defaultHook({ threadId: 'thread-1', runId: 'run-2', agentOutputs: {}, agentStatuses: { fundamental_analysis: 'running' }, isLoading: true });
        rerender(page());
        screen.getByText('Previous result');
        within(screen.getByRole('article', { name: 'Fundamental valuation report' })).getByText('USD 25.12 / share');
        expect(screen.getByLabelText('Terminal growth (%)')).toHaveProperty('value', '2.51234567890123456789');
        expect(screen.getByRole('button', { name: 'Recalculating…' }).hasAttribute('disabled')).toBe(true);
        expect(screen.queryByRole('button', { name: 'Recalculate' })).toBeNull();
        await act(async () => pending.resolve({ kind: 'started', threadId: 'thread-1', runId: 'run-2' }));
    });
});
