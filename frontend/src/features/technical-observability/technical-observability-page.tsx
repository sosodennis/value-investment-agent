'use client';

import { useState, type ReactNode } from 'react';
import Link from 'next/link';
import { RefreshCw } from 'lucide-react';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useTechnicalObservability, useTechnicalObservabilityEventDetail } from '@/hooks/useTechnicalObservability';
import { createDefaultTechnicalObservabilityFilters, parseFilterListInput, type TechnicalObservabilityView } from '@/types/technical-observability';

const VIEWS: { id: TechnicalObservabilityView; label: string }[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'events', label: 'Events' },
    { id: 'cohorts', label: 'Cohorts' },
    { id: 'calibration', label: 'Calibration' },
];

export function TechnicalObservabilityPage() {
    const defaults = createDefaultTechnicalObservabilityFilters();
    const [draft, setDraft] = useState(defaults);
    const [filters, setFilters] = useState(defaults);
    const [view, setView] = useState<TechnicalObservabilityView>('overview');
    const [selectedId, setSelectedId] = useState<string | null>(null);
    const data = useTechnicalObservability(filters);
    const detail = useTechnicalObservabilityEventDetail(selectedId, filters.labelingMethodVersion);

    const activeCount = data.aggregates.reduce((sum, row) => sum + row.event_count, 0);
    const labeledCount = data.aggregates.reduce((sum, row) => sum + row.labeled_event_count, 0);
    const unresolvedCount = data.aggregates.reduce((sum, row) => sum + row.unresolved_event_count, 0);

    return (
        <main className="mx-auto flex w-full max-w-[1600px] flex-col gap-5 px-4 py-6 sm:px-6">
            <header className="flex flex-wrap items-center justify-between gap-4 border-b pb-4">
                <div><p className="text-sm text-muted-foreground">Monitoring / Technical</p><h1 className="mt-1 text-2xl font-semibold">Technical Observability</h1></div>
                <div className="flex items-center gap-3"><Badge variant="outline">Read model</Badge><Link className="text-sm text-primary underline-offset-4 hover:underline" href="/workspace">Workspace</Link></div>
            </header>

            <form className="grid gap-4 rounded-md border bg-card p-4 md:grid-cols-2 xl:grid-cols-4" onSubmit={(event) => { event.preventDefault(); setFilters(draft); }}>
                <Field label="Tickers" htmlFor="obs-tickers"><Input id="obs-tickers" value={draft.tickers.join(', ')} placeholder="AAPL, MSFT" onChange={(event) => setDraft((current) => ({ ...current, tickers: parseFilterListInput(event.target.value) }))} /></Field>
                <Field label="Timeframe" htmlFor="obs-timeframe"><select id="obs-timeframe" className="h-10 rounded-md border border-input bg-background px-3 text-sm" value={draft.timeframes[0] ?? ''} onChange={(event) => setDraft((current) => ({ ...current, timeframes: event.target.value ? [event.target.value] : [] }))}><option value="">All timeframes</option><option value="1d">1D</option><option value="1wk">1W</option><option value="1mo">1M</option></select></Field>
                <Field label="Horizon" htmlFor="obs-horizon"><select id="obs-horizon" className="h-10 rounded-md border border-input bg-background px-3 text-sm" value={draft.horizons[0] ?? ''} onChange={(event) => setDraft((current) => ({ ...current, horizons: event.target.value ? [event.target.value] : [] }))}><option value="">All horizons</option>{['1d','1wk','1mo','3mo'].map((value) => <option key={value}>{value}</option>)}</select></Field>
                <Field label="Labeling method" htmlFor="obs-labeling"><Input id="obs-labeling" value={draft.labelingMethodVersion} onChange={(event) => setDraft((current) => ({ ...current, labelingMethodVersion: event.target.value }))} /></Field>
                <div className="flex items-end gap-2 md:col-span-2 xl:col-span-4"><Button type="submit"><RefreshCw aria-hidden="true" />Apply filters</Button><Button type="button" variant="outline" onClick={() => { const next = createDefaultTechnicalObservabilityFilters(); setDraft(next); setFilters(next); }}>Reset</Button><span className="ml-auto text-sm text-muted-foreground">{data.isLoading ? 'Refreshing data…' : `${activeCount} events in scope`}</span></div>
            </form>

            <section aria-label="Monitoring summary" className="grid gap-3 sm:grid-cols-3">
                <Metric label="Events" value={activeCount} loading={data.isLoading} error={data.aggregatesError} />
                <Metric label="Labeled" value={labeledCount} loading={data.isLoading} error={data.aggregatesError} />
                <Metric label="Unresolved" value={unresolvedCount} loading={data.isLoading} error={data.aggregatesError} />
            </section>

            <Tabs value={view} onValueChange={(value) => setView(value as TechnicalObservabilityView)}>
                <TabsList aria-label="Observability views" className="w-full justify-start overflow-x-auto">
                    {VIEWS.map((item) => <TabsTrigger key={item.id} value={item.id}>{item.label}</TabsTrigger>)}
                </TabsList>
                {VIEWS.map((item) => <TabsContent key={item.id} value={item.id}>
                    {item.id === 'overview' && <div className="grid gap-4 xl:grid-cols-2"><DataState title="Event volume by cohort" loading={data.isLoading} error={data.aggregatesError} empty={data.aggregates.length === 0}><Table><TableHeader><TableRow><TableHead>Timeframe</TableHead><TableHead>Horizon</TableHead><TableHead>Logic</TableHead><TableHead>Events</TableHead><TableHead>Labeled</TableHead><TableHead>Unresolved</TableHead></TableRow></TableHeader><TableBody>{data.aggregates.map((row) => <TableRow key={`${row.timeframe}-${row.horizon}-${row.logic_version}`}><TableCell>{row.timeframe}</TableCell><TableCell>{row.horizon}</TableCell><TableCell>{row.logic_version}</TableCell><TableCell>{row.event_count}</TableCell><TableCell>{row.labeled_event_count}</TableCell><TableCell>{row.unresolved_event_count}</TableCell></TableRow>)}</TableBody></Table></DataState><DataState title="Data quality" loading={data.isLoading} error={data.rowsError} empty={data.rows.length === 0}><p className="text-sm text-muted-foreground">{data.rows.filter((row) => row.data_quality_flags.length > 0).length} of {data.rows.length} returned rows have quality flags.</p><div className="mt-3 flex flex-wrap gap-2">{[...new Set(data.rows.flatMap((row) => row.data_quality_flags))].map((flag) => <Badge key={flag} variant="secondary">{flag}</Badge>)}</div></DataState></div>}
                    {item.id === 'events' && <EventExplorer rows={data.rows} loading={data.isLoading} error={data.rowsError} selectedId={selectedId} onSelect={setSelectedId} detail={detail} />}
                    {item.id === 'cohorts' && <DataState title="Cohort analysis" loading={data.isLoading} error={data.aggregatesError} empty={data.aggregates.length === 0}><Table><TableHeader><TableRow><TableHead>Timeframe</TableHead><TableHead>Horizon</TableHead><TableHead>Logic version</TableHead><TableHead>Samples</TableHead><TableHead>Avg confidence</TableHead><TableHead>Avg forward return</TableHead></TableRow></TableHeader><TableBody>{data.aggregates.map((row) => <TableRow key={`${row.timeframe}-${row.horizon}-${row.logic_version}`}><TableCell>{row.timeframe}</TableCell><TableCell>{row.horizon}</TableCell><TableCell>{row.logic_version}</TableCell><TableCell>{row.event_count}</TableCell><TableCell>{formatNumber(row.avg_confidence)}</TableCell><TableCell>{formatNumber(row.avg_forward_return)}</TableCell></TableRow>)}</TableBody></Table></DataState>}
                    {item.id === 'calibration' && <DataState title="Calibration readiness" loading={data.isLoading} error={data.calibrationError} empty={!data.calibrationReadiness}><dl className="grid gap-4 sm:grid-cols-3"><Metric label="Source rows" value={data.calibrationReadiness?.row_count ?? 0} /><Metric label="Usable rows" value={data.calibrationReadiness?.usable_row_count ?? 0} /><Metric label="Dropped rows" value={data.calibrationReadiness?.dropped_row_count ?? 0} /></dl><ul className="mt-4 flex flex-wrap gap-2">{Object.entries(data.calibrationReadiness?.dropped_reasons ?? {}).map(([reason, count]) => <li key={reason}><Badge variant="outline">{reason}: {count}</Badge></li>)}</ul></DataState>}
                </TabsContent>)}
            </Tabs>
        </main>
    );
}

function Metric({ label, value, loading = false, error = null }: { label: string; value: number; loading?: boolean; error?: Error | null }) {
    return <Card className="border"><CardHeader className="pb-2"><CardTitle className="text-sm text-muted-foreground">{label}</CardTitle></CardHeader><CardContent><p className="text-2xl font-semibold">{error ? 'Unavailable' : loading ? '…' : value.toLocaleString()}</p></CardContent></Card>;
}

function DataState({ title, loading, error, empty, children }: { title: string; loading: boolean; error: Error | null; empty: boolean; children: ReactNode }) {
    return <Card className="border"><CardHeader><CardTitle>{title}</CardTitle></CardHeader><CardContent>{error ? <Alert variant="destructive"><AlertTitle>Could not load this data</AlertTitle><AlertDescription>{error.message}</AlertDescription></Alert> : loading ? <p role="status" className="text-sm text-muted-foreground">Loading {title.toLowerCase()}…</p> : empty ? <p className="text-sm text-muted-foreground">No data matches the applied filters.</p> : children}</CardContent></Card>;
}

function EventExplorer({ rows, loading, error, selectedId, onSelect, detail }: { rows: ReturnType<typeof useTechnicalObservability>['rows']; loading: boolean; error: Error | null; selectedId: string | null; onSelect: (id: string | null) => void; detail: ReturnType<typeof useTechnicalObservabilityEventDetail> }) {
    return <div className="grid gap-4 xl:grid-cols-[minmax(0,1.6fr)_minmax(300px,1fr)]"><DataState title="Prediction events" loading={loading} error={error} empty={rows.length === 0}><Table><TableHeader><TableRow><TableHead>Event time</TableHead><TableHead>Ticker</TableHead><TableHead>Direction</TableHead><TableHead>Frame</TableHead><TableHead>Horizon</TableHead><TableHead>Outcome</TableHead><TableHead>Quality</TableHead></TableRow></TableHeader><TableBody>{rows.map((row) => <TableRow key={row.event_id} data-state={selectedId === row.event_id ? 'selected' : undefined}><TableCell><button aria-label={`Open event ${row.event_id}`} className="text-left text-primary underline-offset-4 hover:underline" onClick={() => onSelect(row.event_id)}>{new Date(row.event_time).toLocaleString()}</button></TableCell><TableCell>{row.ticker}</TableCell><TableCell>{row.direction}</TableCell><TableCell>{row.timeframe}</TableCell><TableCell>{row.horizon}</TableCell><TableCell>{formatNumber(row.forward_return)}</TableCell><TableCell>{row.data_quality_flags.length ? <Badge variant="warning">{row.data_quality_flags.length} flags</Badge> : <Badge variant="secondary">Clear</Badge>}</TableCell></TableRow>)}</TableBody></Table></DataState><Card className="border"><CardHeader className="flex-row items-center justify-between"><CardTitle>Event detail</CardTitle>{selectedId && <Button size="sm" variant="ghost" onClick={() => onSelect(null)}>Close</Button>}</CardHeader><CardContent>{!selectedId ? <p className="text-sm text-muted-foreground">Select an event to inspect its stored context and source references.</p> : detail.error ? <Alert variant="destructive"><AlertTitle>Detail unavailable</AlertTitle><AlertDescription>{detail.error.message}</AlertDescription></Alert> : detail.isLoading ? <p role="status">Loading event detail…</p> : detail.detail ? <dl className="grid gap-3 text-sm"><Detail label="Ticker" value={detail.detail.ticker} /><Detail label="Event ID" value={detail.detail.event_id} /><Detail label="Contract" value={detail.detail.feature_contract_version} /><Detail label="Artifact" value={detail.detail.full_report_artifact_id} /><Detail label="Context" value={JSON.stringify(detail.detail.context_payload, null, 2)} /><Detail label="Source references" value={JSON.stringify(detail.detail.source_artifact_refs, null, 2)} /></dl> : <p className="text-sm text-muted-foreground">No detail available.</p>}</CardContent></Card></div>;
}

function Detail({ label, value }: { label: string; value: string }) { return <div><dt className="font-medium text-muted-foreground">{label}</dt><dd className="mt-1 break-all font-mono text-xs">{value}</dd></div>; }
function formatNumber(value: number | null | undefined): string { return value == null ? '—' : `${(value * 100).toFixed(2)}%`; }
