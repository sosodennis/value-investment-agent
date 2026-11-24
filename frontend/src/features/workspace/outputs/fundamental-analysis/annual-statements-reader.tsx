import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import useSWR from 'swr';
import { ChevronsUpDown } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Command, CommandEmpty, CommandInput, CommandItem, CommandList } from '@/components/ui/command';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { useArtifact } from '@/hooks/useArtifact';
import { parseFundamentalArtifact } from '@/types/agents/artifact-parsers';
import type { ArtifactReference } from '@/types/agents';
import type { EvidenceSelection } from '../../workspace-evidence-inspector';
import { loadAnnualStatementCatalog, readAnnualStatementArtifact, type AnnualStatementReadIntent } from './annual-statements-api';
import { projectAnnualStatements } from './annual-statements-model';
import { AnnualStatementsTable } from './annual-statements-table';

const REFERENCE_EVENT = 'annual-statement-reference';
function subscribeLocation(callback: () => void) {
    window.addEventListener('popstate', callback);
    window.addEventListener(REFERENCE_EVENT, callback);
    return () => {
        window.removeEventListener('popstate', callback);
        window.removeEventListener(REFERENCE_EVENT, callback);
    };
}
function currentLocation() { return window.location.search; }
function serverLocation() { return ''; }
function savedReference(search: string, threadId: string): ArtifactReference | null {
    const params = new URLSearchParams(search);
    const id = params.get('statement_artifact');
    return params.get('statement_thread') === threadId && id && /^[A-Za-z0-9-]{1,128}$/.test(id)
        ? { artifact_id: id, download_url: `/api/v1/artifacts/${encodeURIComponent(id)}?thread_id=${encodeURIComponent(threadId)}`, type: 'financial_reports' } : null;
}
function saveReference(threadId: string, reference: ArtifactReference) {
    const url = new URL(window.location.href);
    url.searchParams.set('statement_thread', threadId);
    url.searchParams.set('statement_artifact', reference.artifact_id);
    if (url.href !== window.location.href) window.history.pushState(window.history.state, '', url);
    window.dispatchEvent(new Event(REFERENCE_EVENT));
}

function retainCreationId(): string {
    const url = new URL(window.location.href);
    const retained = url.searchParams.get('statement_creation');
    const id = retained && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(retained) ? retained : crypto.randomUUID();
    url.searchParams.set('statement_creation', id);
    window.history.replaceState(window.history.state, '', url);
    return id;
}

export function AnnualStatementsReader({ threadId, ticker, onSelectEvidence, onEvidenceItems }: {
    threadId: string | null; ticker?: string | null; onSelectEvidence?: (item: EvidenceSelection) => void;
    onEvidenceItems: (items: EvidenceSelection[]) => void;
}) {
    const search = useSyncExternalStore(subscribeLocation, currentLocation, serverLocation);
    const reportThreadId = threadId ?? new URLSearchParams(search).get('statement_thread');
    const reference = useMemo(() => savedReference(search, reportThreadId ?? ''), [search, reportThreadId]);
    const artifact = useArtifact(reference, parseFundamentalArtifact, 'annual_statements.artifact', 'financial_reports');
    const [selectedIssuer, setSelectedIssuer] = useState<string | null>(null);
    const [pickerOpen, setPickerOpen] = useState(false);
    const catalog = useSWR(pickerOpen || selectedIssuer !== null ? 'annual-statement-catalog' : null, loadAnnualStatementCatalog, { revalidateOnFocus: false });
    const [operation, setOperation] = useState<{ kind: 'idle' | 'pending' } | { kind: 'failed'; message: string }>({ kind: 'idle' });
    const request = useRef<AbortController | null>(null);
    const creationId = useRef<string | null>(null);
    useEffect(() => () => request.current?.abort(), []);
    const selected = catalog.data?.find((entry) => entry.issuer_id === selectedIssuer)
        ?? catalog.data?.find((entry) => entry.ticker === ticker);
    const response = artifact.data?.annual_statements;
    const report = useMemo(() => response ? projectAnnualStatements({
        response, reference, threadId: reportThreadId, companyName: artifact.data?.company_name ?? `SEC issuer ${response.statements.scope.issuer_id}`,
        ticker: artifact.data?.ticker ?? '',
    }) : null, [artifact.data?.company_name, artifact.data?.ticker, reference, response, reportThreadId]);
    useEffect(() => onEvidenceItems(report?.evidence ?? []), [onEvidenceItems, report]);
    async function read() {
        if (!selected || request.current) return;
        const controller = new AbortController();
        request.current = controller;
        setOperation({ kind: 'pending' });
        try {
            const intent: AnnualStatementReadIntent = reportThreadId
                ? { kind: 'existing_thread', thread_id: reportThreadId, issuer_id: selected.issuer_id }
                : { kind: 'new_thread', creation_id: creationId.current ??= retainCreationId(), issuer_id: selected.issuer_id };
            const next = await readAnnualStatementArtifact({ intent, signal: controller.signal });
            if (controller.signal.aborted) return;
            saveReference(next.threadId, next.reference);
            setOperation({ kind: 'idle' });
        } catch (error) {
            if (!controller.signal.aborted) setOperation({ kind: 'failed', message: error instanceof Error ? error.message : 'Annual statements unavailable.' });
        } finally { request.current = null; }
    }
    return <section aria-label="Annual statement reader" className="@container min-w-0 space-y-3">
        <div className="min-w-0 space-y-3 rounded-lg border bg-muted/10 p-3">
            <h2 className="font-semibold">Read annual statements</h2>
            <p className="text-xs text-muted-foreground">Choose a prepared company report. Saved versions retain their original cutoff and filing selection.</p>
            <div className="flex min-w-0 flex-wrap items-center gap-2">
                <Popover open={pickerOpen} onOpenChange={setPickerOpen}>
                    <PopoverTrigger asChild><Button type="button" role="combobox" aria-label="Statement company" aria-expanded={pickerOpen} variant="outline" disabled={catalog.isLoading || operation.kind === 'pending'} className="h-auto min-h-10 max-w-full justify-between whitespace-normal text-left">
                        <span className="min-w-0 [overflow-wrap:anywhere]">{selected ? `${selected.company_name} · ${selected.ticker} · CIK ${selected.issuer_id}` : 'Choose company'}</span><ChevronsUpDown aria-hidden="true" className="shrink-0" />
                    </Button></PopoverTrigger>
                    <PopoverContent align="start" className="w-[min(24rem,calc(100vw-2rem))] p-0"><Command>
                        <CommandInput placeholder="Find company or CIK" aria-label="Find statement company" />
                        <CommandList><CommandEmpty>No prepared companies found.</CommandEmpty>{catalog.data?.map((entry) => <CommandItem key={entry.issuer_id} value={`${entry.company_name} ${entry.ticker} ${entry.issuer_id}`} onSelect={() => { setSelectedIssuer(entry.issuer_id); setPickerOpen(false); }}>
                            {entry.company_name} · {entry.ticker} · CIK {entry.issuer_id}
                        </CommandItem>)}</CommandList>
                    </Command></PopoverContent>
                </Popover>
                <Button type="button" disabled={!selected || operation.kind === 'pending'} onClick={() => void read()}>{operation.kind === 'pending' ? 'Reading statements…' : 'Read prepared statements'}</Button>
            </div>
            {selected && <p className="text-xs text-muted-foreground">Prepared cutoff · {selected.cutoff_at}</p>}
            {catalog.isLoading && <p role="status" className="text-sm">Loading prepared companies…</p>}
            {catalog.error && <Alert variant="warning"><AlertTitle>Company list unavailable</AlertTitle><AlertDescription><Button type="button" variant="outline" size="sm" onClick={() => void catalog.mutate()}>Retry company list</Button></AlertDescription></Alert>}
            {catalog.data?.length === 0 && <p className="text-sm text-muted-foreground">No prepared annual statement reports are available.</p>}
        </div>
        {operation.kind === 'failed' && <Alert variant="warning"><AlertTitle>Annual statement read failed</AlertTitle><AlertDescription>{operation.message}{report && ' The saved version remains visible.'}</AlertDescription></Alert>}
        {artifact.isLoading && <p role="status" className="text-sm">Loading saved annual statements…</p>}
        {artifact.error && <Alert variant="warning"><AlertTitle>Saved annual statements unavailable</AlertTitle><AlertDescription>{artifact.error instanceof Error ? artifact.error.message : 'Saved report could not be read.'}{report && ' The previously loaded version remains visible.'}<Button type="button" variant="outline" size="sm" onClick={() => void artifact.retry()} disabled={artifact.isRetrying}>Retry saved report</Button></AlertDescription></Alert>}
        {artifact.data && !response && <Alert variant="destructive"><AlertTitle>Annual statements absent</AlertTitle><AlertDescription>This saved artifact contains no annual statement contract.</AlertDescription></Alert>}
        {report && <AnnualStatementsTable report={report} onSelectEvidence={onSelectEvidence} />}
    </section>;
}
