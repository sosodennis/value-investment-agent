'use client';

import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { Activity, CircleAlert, Loader2, Menu, Play, Square, Wifi, WifiOff } from 'lucide-react';
import { useAgent } from '@/hooks/useAgent';
import { AGENT_CONFIGS } from '@/config/agents';
import type { AgentInfo, AgentStatus, StandardAgentOutput } from '@/types/agents';
import { WorkspaceOutputPanel } from './workspace-output-panel';
import type { ConnectionState, InteractionResponse, ValuationApprovalResponse, WorkflowActivity, WorkflowInteraction } from '@/features/workflow';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import type { WorkspaceRouteIntent } from './workspace-route-intent';

type WorkspacePageProps = { assistantId?: string; initialTicker?: string | null; initialPrompt?: string | null; autoStart?: boolean; routeIntent?: WorkspaceRouteIntent };
const NEW_ANALYSIS_INTENT: WorkspaceRouteIntent = { kind: 'new-analysis' };
type ReportTab = 'activity' | 'fundamental_analysis' | 'technical_analysis' | 'financial_news_research' | 'debate';
const reportTabs: { id: ReportTab; label: string }[] = [
    { id: 'activity', label: 'Activity' },
    { id: 'fundamental_analysis', label: 'Fundamental' },
    { id: 'technical_analysis', label: 'Technical' },
    { id: 'financial_news_research', label: 'News' },
    { id: 'debate', label: 'Debate' },
];
const isReportTab = (value: string): value is ReportTab =>
    reportTabs.some((tab) => tab.id === value);
const statusLabel: Record<AgentStatus, string> = { idle: 'Idle', running: 'Running', done: 'Complete', attention: 'Waiting', error: 'Failed', degraded: 'Degraded' };
const statusVariant: Record<AgentStatus, 'outline' | 'default' | 'success' | 'warning' | 'destructive'> = { idle: 'outline', running: 'default', done: 'success', attention: 'warning', error: 'destructive', degraded: 'warning' };
const connectionLabels: Record<ConnectionState, string> = { disconnected: 'Disconnected', connecting: 'Connecting', connected: 'Live', reconnecting: 'Reconnecting', closed: 'Connection closed' };

export function WorkspacePage({ assistantId = 'agent', initialTicker = null, initialPrompt = null, autoStart = false, routeIntent = NEW_ANALYSIS_INTENT }: WorkspacePageProps) {
    const agent = useAgent(assistantId);
    const { loadHistory, sendMessage, isLoading } = agent;
    const [ticker, setTicker] = useState(initialTicker?.toUpperCase() ?? '');
    const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
    const [activeTab, setActiveTab] = useState<ReportTab>('activity');
    const autoStarted = useRef(false);
    const agents: AgentInfo[] = useMemo(() => AGENT_CONFIGS.map((config) => ({
        id: config.id,
        name: config.name,
        role: config.role,
        description: config.description,
        avatar: config.avatar,
        status: agent.agentStatuses[config.id] ?? 'idle',
    })), [agent.agentStatuses]);
    const preferredAgentId = agents.find((item) => item.status === 'running' || item.status === 'attention')?.id ?? agents.find((item) => item.status !== 'idle')?.id ?? null;
    const isActive = agent.workflow?.runStatus === 'running' || agent.workflow?.runStatus === 'queued' || agent.workflow?.runStatus === 'waiting';
    const autoStartMessage = initialPrompt?.trim() || (initialTicker?.trim() ? `Valuate ${initialTicker.trim().toUpperCase()}` : null);
    const historyThreadId = routeIntent.kind === 'exact-run' ? routeIntent.threadId : null;
    const historyRunId = routeIntent.kind === 'exact-run' ? routeIntent.runId : null;
    const isHistoryRoute = routeIntent.kind !== 'new-analysis';

    useEffect(() => {
        if (!historyThreadId || !historyRunId) return;
        void loadHistory(historyThreadId, historyRunId);
    }, [historyRunId, historyThreadId, loadHistory]);

    useEffect(() => {
        if (routeIntent.kind !== 'new-analysis' || autoStarted.current || !autoStart || !autoStartMessage || isLoading) return;
        autoStarted.current = true;
        void sendMessage(autoStartMessage, true);
    }, [autoStart, autoStartMessage, isLoading, routeIntent.kind, sendMessage]);

    function startRun(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
        const symbol = ticker.trim().toUpperCase();
        if (routeIntent.kind !== 'new-analysis' || !symbol || agent.isLoading) return;
        setTicker(symbol);
        void agent.sendMessage(`Valuate ${symbol}`, true);
    }

    const roster = <AgentRoster agents={agents} selected={selectedAgentId ?? preferredAgentId} onSelect={(id) => {
        setSelectedAgentId(id);
        if (isReportTab(id)) setActiveTab(id);
    }} />;
    return (
        <main className="mx-auto grid min-h-[calc(100dvh-3.5rem)] w-full max-w-[1600px] grid-rows-[auto_auto_1fr] text-foreground">
            <header className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3 sm:px-6">
                <div className="flex min-w-0 items-center gap-3">
                    <Sheet><SheetTrigger asChild><Button variant="outline" size="icon" className="min-[1440px]:hidden" aria-label="Open agent list"><Menu /></Button></SheetTrigger><SheetContent side="left" className="w-[min(22rem,90vw)] p-0"><SheetHeader className="border-b px-4 py-4"><SheetTitle>Analysis agents</SheetTitle></SheetHeader>{roster}</SheetContent></Sheet>
                    <div className="min-w-0"><p className="text-xs text-muted-foreground">Analysis workspace</p><h1 className="truncate text-lg font-semibold">{routeIntent.kind === 'invalid-history' ? 'Analysis link unavailable' : ticker || agent.workflow ? ticker || 'Analysis run' : routeIntent.kind === 'exact-run' ? 'Analysis run' : 'New analysis'}</h1></div>
                </div>
                <div className="flex items-center gap-2">
                    <ConnectionBadge state={agent.connectionState} />
                    {isActive && <Button variant="outline" size="sm" onClick={() => void agent.cancelRun()} disabled={agent.isLoading}><Square />Cancel run</Button>}
                </div>
            </header>

            {routeIntent.kind === 'new-analysis' && <form className="flex flex-wrap items-end gap-3 border-b bg-muted/20 px-4 py-4 sm:px-6" onSubmit={startRun}>
                <Field label="Company ticker" htmlFor="workspace-ticker" className="w-full max-w-sm"><Input id="workspace-ticker" autoComplete="off" value={ticker} onChange={(event) => setTicker(event.target.value.toUpperCase())} placeholder="AAPL" maxLength={16} /></Field>
                <Button type="submit" disabled={!ticker.trim() || agent.isLoading}>{agent.isLoading ? <Loader2 className="animate-spin" /> : <Play />}{agent.isLoading ? 'Starting…' : 'Start analysis'}</Button>
                {agent.threadId && <p className="ml-auto max-w-full truncate font-mono text-xs text-muted-foreground" title={agent.threadId}>Thread {agent.threadId}</p>}
            </form>}

            <div className="grid min-h-0 min-[1440px]:grid-cols-[17rem_minmax(0,1fr)]">
                <aside className="hidden border-r min-[1440px]:block" aria-label="Analysis agents">{roster}</aside>
                <section className="min-w-0 px-4 py-5 sm:px-6">
                    {routeIntent.kind === 'invalid-history' && <Alert variant="destructive" role="alert" className="mb-4"><CircleAlert className="size-4" /><AlertTitle>History link is incomplete</AlertTitle><AlertDescription>This history link must include both a thread ID and a run ID. Return to dashboard history and open the run again.</AlertDescription></Alert>}
                    {agent.error && <Alert variant="destructive" role="alert" className="mb-4"><CircleAlert className="size-4" /><AlertTitle>{routeIntent.kind === 'exact-run' ? 'Selected analysis run could not be loaded' : 'Workflow request failed'}</AlertTitle><AlertDescription className="break-words">{routeIntent.kind === 'exact-run' && historyRunId ? `Run ${historyRunId} for thread ${historyThreadId} is unavailable. ` : ''}{agent.error}</AlertDescription></Alert>}
                    {routeIntent.kind === 'exact-run' && agent.isLoading && !agent.workflow && <p role="status" className="mb-4 text-sm text-muted-foreground">Loading selected analysis run {routeIntent.runId}…</p>}
                    <div className="mb-4 flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-base font-semibold">Run details</h2><p className="text-sm text-muted-foreground">{agent.workflow ? `Run ${agent.runId ?? agent.workflow.runId} · cursor ${agent.workflow.cursor}` : routeIntent.kind === 'exact-run' ? agent.error ? 'The selected historical run is unavailable.' : 'Loading the selected historical run.' : isHistoryRoute ? 'The selected history link is unavailable.' : 'Run a valuation to follow agent activity and reports.'}</p></div>{agent.workflow && <Badge variant={agent.workflow.runStatus === 'failed' ? 'destructive' : agent.workflow.runStatus === 'completed' ? 'success' : agent.workflow.runStatus === 'waiting' ? 'warning' : 'secondary'}>{agent.workflow.runStatus}</Badge>}</div>
                    <Tabs value={activeTab} onValueChange={(value) => { if (isReportTab(value)) setActiveTab(value); }}>
                        <TabsList aria-label="Workspace views" className="mb-4 h-auto w-full justify-start overflow-x-auto rounded-none border-b bg-transparent p-0">
                            {reportTabs.map((tab) => <TabsTrigger key={tab.id} value={tab.id} className="min-h-10 shrink-0 rounded-none border-b-2 border-transparent px-3 data-[state=active]:border-primary data-[state=active]:bg-transparent">{tab.label}</TabsTrigger>)}
                        </TabsList>
                        <TabsContent value="activity"><ActivityPanel workflow={agent.workflow} connectionState={agent.connectionState} onResumeInteraction={agent.submitCommand} isSubmitting={agent.isSubmittingInteraction} /></TabsContent>
                        {reportTabs.filter((item): item is { id: Exclude<ReportTab, 'activity'>; label: string } => item.id !== 'activity').map((item) => <TabsContent key={item.id} value={item.id}><ReportPanel tab={item.id} outputs={agent.agentOutputs} statuses={agent.agentStatuses} ticker={ticker} /></TabsContent>)}
                    </Tabs>
                </section>
            </div>
        </main>
    );
}

function AgentRoster({ agents, selected, onSelect }: { agents: AgentInfo[]; selected: string | null; onSelect: (id: string) => void }) {
    return <ul className="divide-y">
        {agents.map((item) => <li key={item.id}><button type="button" onClick={() => onSelect(item.id)} aria-current={selected === item.id ? 'true' : undefined} className={`grid min-h-16 w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-3 px-4 py-3 text-left hover:bg-accent/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${selected === item.id ? 'bg-accent/70' : ''}`}>
            <span className="min-w-0"><span className="block truncate text-sm font-medium">{item.name}</span><span className="mt-0.5 block truncate text-xs text-muted-foreground">{item.role || item.description}</span></span><Badge variant={statusVariant[item.status]}>{statusLabel[item.status]}</Badge>
        </button></li>)}
    </ul>;
}

function ConnectionBadge({ state }: { state: ConnectionState }) {
    const Icon = state === 'connected' ? Wifi : state === 'disconnected' || state === 'closed' ? WifiOff : Loader2;
    return <Badge variant={state === 'connected' ? 'success' : state === 'reconnecting' ? 'warning' : 'outline'}><Icon className={`mr-1 size-3 ${state === 'connecting' || state === 'reconnecting' ? 'animate-spin' : ''}`} />{connectionLabels[state]}</Badge>;
}

function ActivityPanel({ workflow, connectionState, onResumeInteraction, isSubmitting }: {
    workflow: ReturnType<typeof useAgent>['workflow'];
    connectionState: ConnectionState;
    onResumeInteraction: (interaction: WorkflowInteraction, response: InteractionResponse) => Promise<void>;
    isSubmitting: boolean;
}) {
    if (!workflow) return <div className="grid min-h-48 place-items-center border-y text-sm text-muted-foreground"><p>No workflow activity is available yet.</p></div>;
    const activities = activityRowsForDisplay(workflow.recent);
    const pendingInteractions = [...workflow.interactions.values()].filter((item) => item.status === 'pending');
    return <div className="grid gap-4">
        {workflow.runStatus === 'waiting' && pendingInteractions.length === 0 && <Alert variant="warning"><CircleAlert className="size-4" /><AlertTitle>Workflow is waiting</AlertTitle><AlertDescription>The workflow is waiting for an interaction request that is not available in this activity snapshot.</AlertDescription></Alert>}
        {workflow.runStatus === 'failed' && <Alert variant="destructive" role="alert"><CircleAlert className="size-4" /><AlertTitle>Run failed</AlertTitle><AlertDescription><span className="block">{workflow.failure?.message ?? activities.find((item) => item.status === 'failed')?.label ?? 'The workflow ended with a failure.'}</span>{workflow.failure && <span className="mt-1 block text-xs">Code: {workflow.failure.code} · {workflow.failure.retryable ? 'Retry may succeed' : 'Retry is not expected to change the result'}</span>}</AlertDescription></Alert>}
        {workflow.runStatus === 'cancelled' && <Alert variant="warning"><AlertTitle>Run cancelled</AlertTitle><AlertDescription>The workflow was cancelled and its current run has ended.</AlertDescription></Alert>}
        {workflow.runStatus === 'completed' && <Alert variant="success"><AlertTitle>Run completed</AlertTitle><AlertDescription>Agent activity has finished. Select a report tab to inspect available results.</AlertDescription></Alert>}
        {activities.length === 0 ? <div className="border-y py-8 text-sm text-muted-foreground">No recent activity was returned for this run.</div> : <ol className="divide-y border-y" aria-label="Workflow activity">
            {activities.map((item) => {
                const activityInteractions = pendingInteractions.filter((interaction) => interaction.identity.activity_id === item.activity_id);
                return <li key={`${item.activity_id}:${item.attempt}:${item.status}`} className="grid grid-cols-[1.25rem_minmax(0,1fr)_auto] gap-3 py-3" style={{ paddingLeft: `${Math.min(3, Math.max(0, item.scope_path.length - 1)) * 12}px` }}>
                    <Activity aria-hidden="true" className={`mt-0.5 size-4 ${item.status === 'failed' ? 'text-destructive' : item.status === 'completed' ? 'text-success' : 'text-primary'}`} />
                    <div className="min-w-0"><p className="text-sm font-medium">{item.label}</p><p className="mt-0.5 truncate text-xs text-muted-foreground">{item.scope_path.join(' / ')} · {item.kind}</p>{item.progress !== undefined && item.progress !== null && <div className="mt-2 flex items-center gap-2"><progress className="h-1.5 flex-1 accent-primary" max={100} value={item.progress} aria-label={`${item.label} progress`} /><span className="w-10 text-right text-xs tabular-nums text-muted-foreground">{item.progress}%</span></div>}
                        {activityInteractions.map((interaction) => <PendingInteractionPrompt key={interaction.identity.interaction_id} interaction={interaction} disabled={isSubmitting} onSubmit={onResumeInteraction} />)}
                    </div>
                    <Badge variant={item.status === 'failed' ? 'destructive' : item.status === 'completed' ? 'success' : item.status === 'waiting' ? 'warning' : 'outline'}>{item.status}</Badge>
                </li>;
            })}
        </ol>}
        {pendingInteractions.filter((interaction) => !activities.some((item) => item.activity_id === interaction.identity.activity_id)).map((interaction) => <PendingInteractionPrompt key={interaction.identity.interaction_id} interaction={interaction} disabled={isSubmitting} onSubmit={onResumeInteraction} />)}
        <p className="text-xs text-muted-foreground">Connection {connectionLabels[connectionState]} · activity cursor {workflow.cursor}</p>
    </div>;
}

function activityRowsForDisplay(recent: WorkflowActivity[]): WorkflowActivity[] {
    const latestById = new Map<string, WorkflowActivity>();
    for (const activity of recent) {
        if (!latestById.has(activity.activity_id)) latestById.set(activity.activity_id, activity);
    }
    const latest = [...latestById.values()];
    const byId = new Map<string, WorkflowActivity>();
    for (const activity of latest) byId.set(activity.activity_id, activity);
    const redundantWrapperIds = new Set<string>();

    for (const child of latest) {
        if (!child.parent_activity_id) continue;
        const parent = byId.get(child.parent_activity_id);
        if (
            parent
            && parent.kind === child.kind
            && parent.label === child.label
            && parent.scope_path.length === child.scope_path.length
            && parent.scope_path.every((part, index) => part === child.scope_path[index])
        ) {
            redundantWrapperIds.add(parent.activity_id);
        }
    }

    return latest.filter((activity) => !redundantWrapperIds.has(activity.activity_id));
}

function PendingInteractionPrompt({ interaction, disabled, onSubmit }: {
    interaction: WorkflowInteraction;
    disabled: boolean;
    onSubmit: (interaction: WorkflowInteraction, response: InteractionResponse) => Promise<void>;
}) {
    if (interaction.kind === 'ticker_selection') {
        return <TickerSelectionPrompt interaction={interaction} disabled={disabled} onSubmit={onSubmit} />;
    }
    return <ValuationApprovalPrompt interaction={interaction} disabled={disabled} onSubmit={onSubmit} />;
}

function TickerSelectionPrompt({ interaction, disabled, onSubmit }: {
    interaction: Extract<WorkflowInteraction, { kind: 'ticker_selection' }>;
    disabled: boolean;
    onSubmit: (interaction: WorkflowInteraction, response: InteractionResponse) => Promise<void>;
}) {
    const [selectedSymbol, setSelectedSymbol] = useState('');
    const { request } = interaction;
    const promptId = `ticker-selection-${interaction.identity.activity_id}`;

    return <Card className="border-warning/50">
        <CardHeader>
            <CardTitle className="text-base">{request.title}</CardTitle>
            <p className="text-sm text-muted-foreground">{request.description}</p>
        </CardHeader>
        <CardContent>
            <form className="grid gap-4" onSubmit={(event) => {
                event.preventDefault();
                if (selectedSymbol) void onSubmit(interaction, { type: 'ticker_selection', selected_symbol: selectedSymbol });
            }}>
                <RadioGroup value={selectedSymbol} onValueChange={setSelectedSymbol} aria-label={request.title}>
                    {request.candidates.map((candidate, index) => {
                        const id = `${promptId}-${index}`;
                        return <div key={candidate.symbol} className="flex items-start gap-3 border p-3 has-[:checked]:border-primary has-[:checked]:bg-accent/40">
                            <RadioGroupItem id={id} value={candidate.symbol} disabled={disabled} className="mt-1" />
                            <Label htmlFor={id} className="min-w-0 cursor-pointer">
                                <span className="block">{candidate.symbol} <span className="font-normal text-muted-foreground">{candidate.name}</span></span>
                                <span className="mt-1 block text-xs font-normal text-muted-foreground">{[candidate.exchange, candidate.type, `${Math.round(candidate.confidence * 100)}% match`].filter(Boolean).join(' · ')}</span>
                            </Label>
                        </div>;
                    })}
                </RadioGroup>
                <Button type="submit" disabled={disabled || !selectedSymbol} className="justify-self-start">Continue with {selectedSymbol || 'selected company'}</Button>
            </form>
        </CardContent>
    </Card>;
}

function ValuationApprovalPrompt({ interaction, disabled, onSubmit }: {
    interaction: Extract<WorkflowInteraction, { kind: 'valuation_approval' }>;
    disabled: boolean;
    onSubmit: (interaction: WorkflowInteraction, response: InteractionResponse) => Promise<void>;
}) {
    const { request } = interaction;
    const respond = (decision: ValuationApprovalResponse['decision']) => {
        void onSubmit(interaction, {
            type: 'valuation_approval',
            contract_version: request.contract_version,
            decision,
        });
    };
    return <Alert variant="warning" role="alert" className="mt-3">
        <CircleAlert className="size-4" />
        <AlertTitle>{request.title}</AlertTitle>
        <div className="col-start-2 grid gap-3 text-sm opacity-90">
            <p>{request.description}</p>
            <p className="font-medium text-foreground">{request.ticker} · {request.model_type}</p>
            <details className="text-sm">
                <summary className="cursor-pointer font-medium">Validated parameters ({Object.keys(request.parameters).length})</summary>
                <dl className="mt-2 grid gap-x-4 gap-y-1 border-l pl-3 sm:grid-cols-[minmax(9rem,auto)_minmax(0,1fr)]">
                    {Object.entries(request.parameters).map(([name, value]) => <div key={name} className="contents">
                        <dt className="break-words text-muted-foreground">{name}</dt>
                        <dd className="break-all tabular-nums">{typeof value === 'string' ? value : JSON.stringify(value)}</dd>
                    </div>)}
                </dl>
            </details>
            {request.audit_messages.length > 0 && <div><p className="text-sm font-medium text-foreground">Audit</p><ul className="mt-1 grid gap-1">{request.audit_messages.map((message, index) => <li key={`${index}:${message}`} className="break-words text-sm">{message}</li>)}</ul></div>}
            <div className="flex flex-wrap gap-2">
                <Button type="button" disabled={disabled} onClick={() => respond('approve')}>Approve valuation</Button>
                <Button type="button" variant="outline" disabled={disabled} onClick={() => respond('reject')}>Reject calculation</Button>
            </div>
        </div>
    </Alert>;
}

export function ReportPanel({ tab, outputs, statuses, ticker }: { tab: Exclude<ReportTab, 'activity'>; outputs: Record<string, StandardAgentOutput | null>; statuses: Record<string, AgentStatus>; ticker: string }) {
    const output = outputs[tab] ?? null;
    const config = AGENT_CONFIGS.find((item) => item.id === tab);
    const status = statuses[tab] ?? 'idle';
    if (!config) return null;
    if (!output) return <div className="grid min-h-48 place-items-center border-y px-4 text-center"><div><p className="text-sm font-medium">Report unavailable</p><p className="mt-1 max-w-lg text-sm text-muted-foreground">This run has not supplied an output preview or artifact reference for this agent.</p><Badge className="mt-3" variant={statusVariant[status]}>{statusLabel[status]}</Badge></div></div>;

    const agent: AgentInfo = {
        id: config.id,
        name: config.name,
        description: config.description,
        avatar: config.avatar,
        role: config.role,
        status,
    };
    return <WorkspaceOutputPanel agent={agent} output={output} resolvedTicker={ticker || null} status={status} />;
}
