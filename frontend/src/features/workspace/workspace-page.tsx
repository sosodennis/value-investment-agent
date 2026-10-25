'use client';

import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { Activity, CircleAlert, Loader2, Menu, Play, Square, Wifi, WifiOff } from 'lucide-react';
import { useAgent } from '@/hooks/useAgent';
import { AGENT_CONFIGS } from '@/config/agents';
import type { AgentInfo, AgentStatus, StandardAgentOutput } from '@/types/agents';
import { adaptAgentOutput } from '@/types/agents/output-adapter';
import type { ConnectionState, TickerSelectionResponse, WorkflowActivity } from '@/features/workflow';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Separator } from '@/components/ui/separator';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

type WorkspacePageProps = { assistantId?: string; initialTicker?: string | null; autoStart?: boolean };
type ReportTab = 'activity' | 'fundamental_analysis' | 'technical_analysis' | 'financial_news_research' | 'debate';
const reportTabs: { id: ReportTab; label: string }[] = [
    { id: 'activity', label: 'Activity' },
    { id: 'fundamental_analysis', label: 'Fundamental' },
    { id: 'technical_analysis', label: 'Technical' },
    { id: 'financial_news_research', label: 'News' },
    { id: 'debate', label: 'Debate' },
];
const statusLabel: Record<AgentStatus, string> = { idle: 'Idle', running: 'Running', done: 'Complete', attention: 'Waiting', error: 'Failed', degraded: 'Degraded' };
const statusVariant: Record<AgentStatus, 'outline' | 'default' | 'success' | 'warning' | 'destructive'> = { idle: 'outline', running: 'default', done: 'success', attention: 'warning', error: 'destructive', degraded: 'warning' };
const connectionLabels: Record<ConnectionState, string> = { disconnected: 'Disconnected', connecting: 'Connecting', connected: 'Live', reconnecting: 'Reconnecting', closed: 'Connection closed' };

export function WorkspacePage({ assistantId = 'agent', initialTicker = null, autoStart = false }: WorkspacePageProps) {
    const agent = useAgent(assistantId);
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
    const selectedAgent = agents.find((item) => item.id === selectedAgentId) ?? null;
    const orderedActivity = agent.workflow ? [...agent.workflow.recent].reverse() : [];
    const waitingActivities = agent.activeActivities.filter((item) => item.status === 'waiting' && item.interruption);
    const isActive = agent.workflow?.runStatus === 'running' || agent.workflow?.runStatus === 'queued' || agent.workflow?.runStatus === 'waiting';

    useEffect(() => {
        if (autoStarted.current || !autoStart || !initialTicker || agent.isLoading) return;
        autoStarted.current = true;
        void agent.sendMessage(`Valuate ${initialTicker.toUpperCase()}`, true);
    }, [agent.isLoading, agent.sendMessage, autoStart, initialTicker]);

    useEffect(() => {
        if (!selectedAgentId && agents.some((item) => item.status !== 'idle')) {
            setSelectedAgentId(agents.find((item) => item.status === 'running' || item.status === 'attention')?.id ?? agents.find((item) => item.status !== 'idle')?.id ?? null);
        }
    }, [agents, selectedAgentId]);

    function startRun(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
        const symbol = ticker.trim().toUpperCase();
        if (!symbol || agent.isLoading) return;
        setTicker(symbol);
        void agent.sendMessage(`Valuate ${symbol}`, true);
    }

    const roster = <AgentRoster agents={agents} selected={selectedAgentId} onSelect={setSelectedAgentId} />;
    return (
        <main className="mx-auto grid min-h-[calc(100dvh-3.5rem)] w-full max-w-[1600px] grid-rows-[auto_auto_1fr] text-foreground">
            <header className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3 sm:px-6">
                <div className="flex min-w-0 items-center gap-3">
                    <Sheet><SheetTrigger asChild><Button variant="outline" size="icon" className="lg:hidden" aria-label="Open agent list"><Menu /></Button></SheetTrigger><SheetContent side="left" className="w-[min(22rem,90vw)] p-0"><SheetHeader className="border-b px-4 py-4"><SheetTitle>Analysis agents</SheetTitle></SheetHeader>{roster}</SheetContent></Sheet>
                    <div className="min-w-0"><p className="text-xs text-muted-foreground">Analysis workspace</p><h1 className="truncate text-lg font-semibold">{ticker || agent.workflow ? ticker || 'Analysis run' : 'New analysis'}</h1></div>
                </div>
                <div className="flex items-center gap-2">
                    <ConnectionBadge state={agent.connectionState} />
                    {isActive && <Button variant="outline" size="sm" onClick={() => void agent.cancelRun()} disabled={agent.isLoading}><Square />Cancel run</Button>}
                </div>
            </header>

            <form className="flex flex-wrap items-end gap-3 border-b bg-muted/20 px-4 py-4 sm:px-6" onSubmit={startRun}>
                <Field label="Company ticker" htmlFor="workspace-ticker" className="w-full max-w-sm"><Input id="workspace-ticker" autoComplete="off" value={ticker} onChange={(event) => setTicker(event.target.value.toUpperCase())} placeholder="AAPL" maxLength={16} /></Field>
                <Button type="submit" disabled={!ticker.trim() || agent.isLoading}>{agent.isLoading ? <Loader2 className="animate-spin" /> : <Play />}{agent.isLoading ? 'Starting…' : 'Start analysis'}</Button>
                {agent.threadId && <p className="ml-auto max-w-full truncate font-mono text-xs text-muted-foreground" title={agent.threadId}>Thread {agent.threadId}</p>}
            </form>

            <div className="grid min-h-0 lg:grid-cols-[17rem_minmax(0,1fr)]">
                <aside className="hidden border-r lg:block" aria-label="Analysis agents">{roster}</aside>
                <section className="min-w-0 px-4 py-5 sm:px-6">
                    {agent.error && <Alert variant="destructive" role="alert" className="mb-4"><CircleAlert className="size-4" /><AlertTitle>Workflow request failed</AlertTitle><AlertDescription className="break-words">{agent.error}</AlertDescription></Alert>}
                    <div className="mb-4 flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-base font-semibold">Run details</h2><p className="text-sm text-muted-foreground">{agent.workflow ? `Run ${agent.runId ?? agent.workflow.runId} · cursor ${agent.workflow.cursor}` : 'Run a valuation to follow agent activity and reports.'}</p></div>{agent.workflow && <Badge variant={agent.workflow.runStatus === 'failed' ? 'destructive' : agent.workflow.runStatus === 'completed' ? 'success' : agent.workflow.runStatus === 'waiting' ? 'warning' : 'secondary'}>{agent.workflow.runStatus}</Badge>}</div>
                    <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as ReportTab)}>
                        <TabsList aria-label="Workspace views" className="mb-4 h-auto w-full justify-start overflow-x-auto rounded-none border-b bg-transparent p-0">
                            {reportTabs.map((tab) => <TabsTrigger key={tab.id} value={tab.id} className="min-h-10 shrink-0 rounded-none border-b-2 border-transparent px-3 data-[state=active]:border-primary data-[state=active]:bg-transparent">{tab.label}</TabsTrigger>)}
                        </TabsList>
                        <TabsContent value="activity"><ActivityPanel workflow={agent.workflow} waiting={waitingActivities} onResume={agent.submitCommand} isSubmitting={agent.isLoading} /></TabsContent>
                        {reportTabs.filter((item) => item.id !== 'activity').map((tab) => <TabsContent key={tab.id} value={tab.id}><ReportPanel tab={tab.id} outputs={agent.agentOutputs} statuses={agent.agentStatuses} ticker={ticker} /></TabsContent>)}
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

function ActivityPanel({ workflow, waiting, onResume, isSubmitting }: {
    workflow: ReturnType<typeof useAgent>['workflow'];
    waiting: WorkflowActivity[];
    onResume: (activity: WorkflowActivity, response: TickerSelectionResponse) => Promise<void>;
    isSubmitting: boolean;
}) {
    if (!workflow) return <div className="grid min-h-48 place-items-center border-y text-sm text-muted-foreground"><p>No workflow activity is available yet.</p></div>;
    const activities = [...workflow.recent].reverse();
    return <div className="grid gap-4">
        {waiting.map((activity) => <TickerPrompt key={activity.activity_id} activity={activity} isSubmitting={isSubmitting} onSubmit={(response) => onResume(activity, response)} />)}
        {workflow.runStatus === 'failed' && <Alert variant="destructive" role="alert"><CircleAlert className="size-4" /><AlertTitle>Run failed</AlertTitle><AlertDescription>{activities.find((item) => item.status === 'failed')?.label ?? 'The workflow ended with a failure.'}</AlertDescription></Alert>}
        {workflow.runStatus === 'cancelled' && <Alert variant="warning"><AlertTitle>Run cancelled</AlertTitle><AlertDescription>The workflow was cancelled and its current run has ended.</AlertDescription></Alert>}
        {workflow.runStatus === 'completed' && <Alert variant="success"><AlertTitle>Run completed</AlertTitle><AlertDescription>Agent activity has finished. Select a report tab to inspect available results.</AlertDescription></Alert>}
        {activities.length === 0 ? <div className="border-y py-8 text-sm text-muted-foreground">No recent activity was returned for this run.</div> : <ol className="divide-y border-y" aria-label="Workflow activity">
            {activities.map((item) => <li key={`${item.activity_id}:${item.attempt}:${item.status}`} className="grid grid-cols-[1.25rem_minmax(0,1fr)_auto] gap-3 py-3" style={{ paddingLeft: `${Math.min(3, Math.max(0, item.scope_path.length - 1)) * 12}px` }}>
                <Activity aria-hidden="true" className={`mt-0.5 size-4 ${item.status === 'failed' ? 'text-destructive' : item.status === 'completed' ? 'text-success' : 'text-primary'}`} />
                <div className="min-w-0"><p className="text-sm font-medium">{item.label}</p><p className="mt-0.5 truncate text-xs text-muted-foreground">{item.scope_path.join(' / ')} · {item.kind} · attempt {item.attempt}</p>{item.progress !== undefined && <div className="mt-2 flex items-center gap-2"><progress className="h-1.5 flex-1 accent-primary" max={100} value={item.progress} aria-label={`${item.label} progress`} /><span className="w-10 text-right text-xs tabular-nums text-muted-foreground">{item.progress}%</span></div>}</div>
                <Badge variant={item.status === 'failed' ? 'destructive' : item.status === 'completed' ? 'success' : item.status === 'waiting' ? 'warning' : 'outline'}>{item.status}</Badge>
            </li>)}
        </ol>}
        <p className="text-xs text-muted-foreground">Connection {connectionLabels[workflow.connection]} · activity cursor {workflow.cursor}</p>
    </div>;
}

function TickerPrompt({ activity, isSubmitting, onSubmit }: { activity: WorkflowActivity; isSubmitting: boolean; onSubmit: (response: TickerSelectionResponse) => Promise<void> }) {
    const [symbol, setSymbol] = useState('');
    const request = activity.interruption?.request;
    if (!request) return null;
    return <Card className="border-warning/40">
        <CardHeader><CardTitle className="text-base">{request.title}</CardTitle><p className="text-sm text-muted-foreground">{request.description}</p></CardHeader>
        <CardContent><form className="grid gap-3" onSubmit={(event) => { event.preventDefault(); if (symbol) void onSubmit({ type: 'ticker_selection', selected_symbol: symbol }); }}>
            <fieldset className="grid gap-2"><legend className="mb-1 text-sm font-medium">Select the company</legend>{request.candidates.map((candidate) => <label key={candidate.symbol} className="flex cursor-pointer items-start gap-3 border px-3 py-2.5 has-[:checked]:border-primary has-[:checked]:bg-primary/5"><input type="radio" name={`ticker-selection-${activity.activity_id}`} value={candidate.symbol} checked={symbol === candidate.symbol} onChange={() => setSymbol(candidate.symbol)} disabled={isSubmitting} className="mt-1 accent-primary" /><span className="min-w-0"><span className="font-medium">{candidate.symbol}</span><span className="ml-2 text-sm text-muted-foreground">{candidate.name}</span><span className="mt-1 block text-xs text-muted-foreground">{[candidate.exchange, candidate.type, `${Math.round(candidate.confidence * 100)}% match`].filter(Boolean).join(' · ')}</span></span></label>)}</fieldset>
            <Button type="submit" className="justify-self-start" disabled={!symbol || isSubmitting}>{isSubmitting && <Loader2 className="animate-spin" />}Continue with {symbol || 'selected ticker'}</Button>
        </form></CardContent>
    </Card>;
}

function ReportPanel({ tab, outputs, statuses, ticker }: { tab: Exclude<ReportTab, 'activity'>; outputs: Record<string, StandardAgentOutput | null>; statuses: Record<string, AgentStatus>; ticker: string }) {
    const model = useMemo(() => {
        const raw = outputs[tab] ?? null;
        return adaptAgentOutput(tab, raw, `workspace.${tab}`);
    }, [outputs, tab]);
    if (!model.summary && !model.preview) return <div className="grid min-h-48 place-items-center border-y px-4 text-center"><div><p className="text-sm font-medium">Report unavailable</p><p className="mt-1 max-w-lg text-sm text-muted-foreground">This workflow run did not provide a report reference. Completed reports become available when the backend returns artifact references for the run.</p>{statuses[tab] && <Badge className="mt-3" variant={statusVariant[statuses[tab]]}>{statusLabel[statuses[tab]]}</Badge>}</div></div>;
    const details = reportDetails(model);
    return <div className="grid gap-4">
        <Card className="border"><CardHeader><CardTitle className="text-base">{ticker || AGENT_CONFIGS.find((item) => item.id === tab)?.name || 'Agent report'}</CardTitle>{model.summary && <p className="text-sm leading-6 text-muted-foreground">{model.summary}</p>}</CardHeader><CardContent>
            {details.length ? <dl className="grid gap-x-6 gap-y-4 sm:grid-cols-2">{details.map(([label, value]) => <div key={label} className="border-t pt-3"><dt className="text-xs text-muted-foreground">{label}</dt><dd className="mt-1 break-words text-sm font-medium">{value}</dd></div>)}</dl> : <p className="text-sm text-muted-foreground">The parsed report contains no preview fields.</p>}
        </CardContent></Card>
        {model.reference && <p className="font-mono text-xs text-muted-foreground">Artifact {model.reference.artifact_id} · {model.reference.type}</p>}
        {model.errorLogs.map((item, index) => <Alert key={`${item.node}:${index}`} variant={item.severity === 'error' ? 'destructive' : 'warning'} role={item.severity === 'error' ? 'alert' : 'status'}><AlertTitle>{item.node}</AlertTitle><AlertDescription>{item.error}</AlertDescription></Alert>)}
    </div>;
}

function reportDetails(model: ReturnType<typeof adaptAgentOutput>): [string, string][] {
    switch (model.kind) {
        case 'fundamental_analysis': return model.preview ? Object.entries({ Company: model.preview.company_name, Ticker: model.preview.ticker, Sector: model.preview.sector, Industry: model.preview.industry, 'Selected model': model.preview.selected_model, 'Valuation score': model.preview.valuation_score === undefined ? undefined : String(model.preview.valuation_score), ...model.preview.key_metrics }).filter((entry): entry is [string, string] => typeof entry[1] === 'string') : [];
        case 'technical_analysis': return model.preview ? Object.entries({ Ticker: model.preview.ticker, Price: model.preview.latest_price_display, Signal: model.preview.signal_display, 'Z-score': model.preview.z_score_display, 'Optimal d': model.preview.optimal_d_display, Strength: model.preview.strength_display }).filter((entry): entry is [string, string] => typeof entry[1] === 'string') : [];
        case 'financial_news_research': return model.preview ? [['Sentiment', model.preview.sentiment_display], ['Articles', model.preview.article_count_display], ...(model.preview.top_headlines ?? []).map((headline, index) => [`Headline ${index + 1}`, headline])] : [];
        case 'debate': return model.preview ? [['Verdict', model.preview.verdict_display], ['Thesis', model.preview.thesis_display], ['Catalyst', model.preview.catalyst_display], ['Risk', model.preview.risk_display], ['Rounds', model.preview.debate_rounds_display]].filter((entry): entry is [string, string] => typeof entry[1] === 'string') : [];
        case 'generic': return model.preview ? Object.entries(model.preview).filter((entry): entry is [string, string] => typeof entry[1] === 'string') : [];
        default: { const exhaustive: never = model; return exhaustive; }
    }
}
