import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import useSWR from 'swr';
import { ChevronsUpDown } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Command, CommandEmpty, CommandInput, CommandItem, CommandList } from '@/components/ui/command';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { parseFundamentalArtifact } from '@/types/agents/artifact-parsers';
import { parseArtifactEnvelope } from '@/types/agents/artifact-envelope-parser';
import type { FundamentalAnalysisSuccess } from '@/types/agents/fundamental';
import type { ArtifactReference } from '@/types/agents';
import { parseApiErrorMessage } from '@/types/protocol';
import { statementEditionIdentity } from '@/types/agents/statement-read';
import type { EvidenceSelection } from '../../workspace-evidence-inspector';
import { loadStatementCatalog, readStatementArtifact, type StatementReadIntent, type StatementFrequency, type StatementEdition } from './statement-reader-api';
import { projectAnnualStatements } from './annual-statements-model';
import { AnnualStatementsTable } from './annual-statements-table';
import { projectFiscalStatements } from './fiscal-statements-model';
import { FiscalStatementsTable } from './fiscal-statements-table';

import { retainStatementCreationId, savedStatementExpectation, saveStatementPeriod, saveStatementReference, statementLocationSnapshot, statementServerLocationSnapshot, subscribeStatementLocation, type SavedStatementExpectation } from '../../workspace-statement-location';
const FREQUENCIES = [{ id: 'annual', label: 'Annual' }, { id: 'quarter', label: 'Quarterly' }, { id: 'ttm', label: 'TTM' }] satisfies { id: StatementFrequency; label: string }[];
function isFrequency(value: string): value is StatementFrequency { return FREQUENCIES.some(({ id }) => id === value); }
function savedSelection(search: string, threadId: string | null) {
    const params = new URLSearchParams(search);
    const id = params.get('statement_artifact');
    const savedThread = params.get('statement_thread');
    const frequency = params.get('statement_frequency') ?? 'annual';
    if (!id || !savedThread || (threadId !== null && savedThread !== threadId)) return null;
    if (['statement_artifact', 'statement_thread', 'statement_frequency', 'statement_period'].some((key) => params.getAll(key).length > 1)
        || !/^[A-Za-z0-9-]{1,128}$/.test(id) || !/^[A-Za-z0-9_-]{1,128}$/.test(savedThread) || !isFrequency(frequency)) return null;
    return {
        threadId: savedThread, frequency, period: params.get('statement_period'),
        reference: { artifact_id: id, download_url: `/api/v1/artifacts/${encodeURIComponent(id)}?thread_id=${encodeURIComponent(savedThread)}`, type: 'financial_reports' } satisfies ArtifactReference,
    };
}
type SavedSelection = ReturnType<typeof savedSelection>;
type ArtifactState = { key: string; kind: 'loading' } | { key: string; kind: 'ready'; data: FundamentalAnalysisSuccess } | { key: string; kind: 'failed'; message: string };
function useSavedStatement(saved: SavedSelection, expectation: SavedStatementExpectation) {
    const [retry, setRetry] = useState(0);
    const [state, setState] = useState<ArtifactState | null>(null);
    const url = saved?.reference.download_url;
    const frequency = saved?.frequency;
    const expectedIdentity = expectation.kind === 'bound' ? expectation.value.editionIdentity : null;
    const invalidExpectation = expectation.kind === 'invalid';
    const key = url ? `${url}:${frequency}:${invalidExpectation}:${expectedIdentity}:${retry}` : null;
    useEffect(() => {
        const recheck = () => setRetry((count) => count + 1);
        window.addEventListener('focus', recheck);
        return () => window.removeEventListener('focus', recheck);
    }, []);
    useEffect(() => {
        if (!url || !key) return;
        const controller = new AbortController();
        void (async () => {
            try {
                if (invalidExpectation) throw new TypeError('Saved statement history identity is invalid. Reopen the saved report link.');
                const response = await fetch(url, { credentials: 'include', cache: 'no-store', signal: controller.signal });
                const wire: unknown = await response.json().catch(() => {
                    throw new Error(response.ok ? 'Saved statement response is not valid JSON.' : `Saved statements unavailable (HTTP ${response.status}).`);
                });
                if (!response.ok) throw new Error(parseApiErrorMessage(wire) || `Saved statements unavailable (HTTP ${response.status}).`);
                const envelope = parseArtifactEnvelope(wire, 'statement artifact', 'financial_reports');
                const data = parseFundamentalArtifact(envelope.data, 'statement artifact.data');
                const actualFrequency = data.statement_read ? data.statement_read.read.kind === 'annual' ? 'annual' : data.statement_read.read.request.frequency : data.annual_statements ? 'annual' : null;
                if (frequency !== actualFrequency) throw new TypeError('Saved URL frequency differs from the returned statement artifact.');
                if (expectedIdentity !== null && (!data.statement_read || statementEditionIdentity(data.statement_read.edition) !== expectedIdentity)) throw new TypeError('Returned statement artifact differs from the requested saved edition.');
                if (!controller.signal.aborted) setState({ key, kind: 'ready', data });
            } catch (error) {
                if (!controller.signal.aborted) setState({ key, kind: 'failed', message: error instanceof Error ? error.message : 'Saved statements unavailable.' });
            }
        })();
        return () => controller.abort();
    }, [url, frequency, key, retry, expectedIdentity, invalidExpectation]);
    return { state: state?.key === key ? state : key ? { key, kind: 'loading' } satisfies ArtifactState : null, retry: () => setRetry((count) => count + 1) };
}

type ReadOperation = { kind: 'idle' } | { kind: 'pending'; key: string; intent: StatementReadIntent; edition: StatementEdition } | { kind: 'failed'; key: string; intent: StatementReadIntent; edition: StatementEdition; message: string };

type StatementReaderProps = {
    threadId: string | null; ticker?: string | null; onSelectEvidence?: (item: EvidenceSelection) => void;
    onEvidenceItems: (items: EvidenceSelection[]) => void;
};

export function StatementReader(props: StatementReaderProps) {
    const location = useSyncExternalStore(subscribeStatementLocation, statementLocationSnapshot, statementServerLocationSnapshot);
    const saved = useMemo(() => savedSelection(location ? window.location.search : '', props.threadId), [location, props.threadId]);
    const savedKey = saved ? `${saved.threadId}:${saved.reference.artifact_id}:${saved.frequency}` : `unbound:${props.threadId}`;
    const expectation = saved ? savedStatementExpectation(saved.threadId, saved.reference.artifact_id) : { kind: 'absent' } satisfies SavedStatementExpectation;
    return <StatementReaderSession key={savedKey} {...props} saved={saved} savedKey={savedKey} expectation={expectation} />;
}

function StatementReaderSession({ threadId, ticker, onSelectEvidence, onEvidenceItems, saved, savedKey, expectation }: StatementReaderProps & {
    saved: SavedSelection; savedKey: string; expectation: SavedStatementExpectation;
}) {
    const reportThreadId = threadId ?? saved?.threadId ?? null;
    const artifact = useSavedStatement(saved, expectation);
    const [selectedEdition, setSelectedEdition] = useState<string | null>(null);
    const [draftFrequency, setDraftFrequency] = useState<StatementFrequency>('annual');
    const [pickerOpen, setPickerOpen] = useState(false);
    const catalog = useSWR(pickerOpen || selectedEdition !== null ? 'statement-catalog-v2' : null, loadStatementCatalog, { revalidateOnFocus: false, shouldRetryOnError: false });
    const selected = catalog.data?.find((entry) => entry.edition_id === selectedEdition)
        ?? (!saved ? catalog.data?.find((entry) => entry.ticker === ticker) : undefined);
    const [operation, setOperation] = useState<ReadOperation>({ kind: 'idle' });
    const request = useRef<AbortController | null>(null);
    const creationId = useRef<string | null>(null);
    useEffect(() => () => request.current?.abort(), []);
    const data = artifact.state?.kind === 'ready' ? artifact.state.data : null;
    const canShowSaved = selectedEdition === null && operation.kind === 'idle';
    const annualResponse = data?.statement_read?.read.kind === 'annual' ? data.statement_read.read.response : data?.annual_statements;
    const annualReport = useMemo(() => annualResponse && saved && data ? projectAnnualStatements({
        response: annualResponse, reference: saved.reference, threadId: saved.threadId, companyName: data.company_name, ticker: data.ticker,
    }) : null, [annualResponse, data, saved]);
    const fiscalReport = useMemo(() => data?.statement_read?.read.kind === 'fiscal' && saved ? projectFiscalStatements({ saved: data.statement_read, reference: saved.reference, threadId: saved.threadId }) : null, [data, saved]);
    const evidence = useMemo(() => canShowSaved ? annualReport?.evidence ?? fiscalReport?.evidence ?? [] : [], [annualReport, canShowSaved, fiscalReport]);
    useEffect(() => onEvidenceItems(evidence), [evidence, onEvidenceItems]);
    const periods = useMemo(() => annualReport ? [...new Map(annualReport.tables.flatMap((table) => table.columns.map((column) => [column.id, { id: column.id, label: `${column.label} · ${column.period}` }] satisfies [string, { id: string; label: string }]))).values()]
        : fiscalReport?.columns.map((column) => ({ id: column.id, label: column.quarters.map((quarter) => quarter.period.kind === 'instant' ? `As of ${quarter.period.instant}` : `${quarter.period.start} to ${quarter.period.end}`).join(' · ') })) ?? [], [annualReport, fiscalReport]);
    const validPeriod = saved?.period && periods.some((period) => period.id === saved.period) ? saved.period : null;
    const frequency = selectedEdition !== null || !saved ? draftFrequency : operation.kind === 'pending' ? operation.intent.frequency : saved.frequency;

    function cancelRead() { request.current?.abort(); request.current = null; artifact.retry(); setOperation({ kind: 'idle' }); }
    async function read(intent: StatementReadIntent, key: string, edition: StatementEdition) {
        request.current?.abort();
        const controller = new AbortController(); request.current = controller;
        setOperation({ kind: 'pending', key, intent, edition });
        try {
            const next = await readStatementArtifact({ intent, signal: controller.signal });
            if (controller.signal.aborted || request.current !== controller) return;
            if (next.editionId !== edition.edition_id) throw new TypeError('Statement frequency change returned a different saved edition.');
            saveStatementReference({ threadId: next.threadId, artifactId: next.reference.artifact_id, editionIdentity: statementEditionIdentity(edition) }, intent.frequency);
            setOperation({ kind: 'idle' }); setSelectedEdition(null);
        } catch (error) {
            if (!controller.signal.aborted && request.current === controller) setOperation({ kind: 'failed', key, intent, edition, message: error instanceof Error ? error.message : 'Statements unavailable.' });
        } finally { if (request.current === controller) request.current = null; }
    }
    function readEdition() {
        if (!selected) return;
        const intent: StatementReadIntent = reportThreadId
            ? { contract_version: 'workspace.statement-reader.v2', kind: 'existing_thread', thread_id: reportThreadId, edition_id: selected.edition_id, frequency: draftFrequency }
            : { contract_version: 'workspace.statement-reader.v2', kind: 'new_thread', creation_id: creationId.current ??= retainStatementCreationId(), edition_id: selected.edition_id, frequency: draftFrequency };
        void read(intent, JSON.stringify({ edition: selected, frequency: draftFrequency, threadId: reportThreadId }), selected);
    }
    function changeFrequency(next: string) {
        if (!isFrequency(next)) return;
        if (selectedEdition !== null || !saved) { cancelRead(); setDraftFrequency(next); return; }
        if (!data?.statement_read) return;
        const intent: StatementReadIntent = { contract_version: 'workspace.statement-reader.v2', kind: 'saved_artifact', thread_id: saved.threadId, artifact_id: saved.reference.artifact_id, frequency: next };
        void read(intent, `${savedKey}:${next}`, data.statement_read.edition);
    }
    return <section aria-label="Financial statement reader" className="@container min-w-0 space-y-3">
        <div className="min-w-0 space-y-3 rounded-lg border bg-muted/10 p-3">
            <h2 tabIndex={-1} className="font-semibold">Read financial statements</h2>
            <p className="text-xs text-muted-foreground">Choose a prepared edition, then read annual, quarterly or TTM statements. Saved frequency changes retain the original release pair and cutoff.</p>
            <div className="flex min-w-0 flex-wrap items-center gap-2">
                <Popover open={pickerOpen} onOpenChange={setPickerOpen}>
                    <PopoverTrigger asChild><Button type="button" role="combobox" aria-label="Statement company and edition" aria-expanded={pickerOpen} variant="outline" className="h-auto min-h-10 max-w-full justify-between whitespace-normal text-left">
                        <span className="min-w-0 [overflow-wrap:anywhere]">{selected ? `${selected.company_name} · ${selected.ticker} · ${selected.label}` : data?.statement_read ? `${data.statement_read.edition.company_name} · ${data.statement_read.edition.label}` : 'Choose company and edition'}</span><ChevronsUpDown aria-hidden="true" className="shrink-0" />
                    </Button></PopoverTrigger>
                    <PopoverContent align="start" className="w-[min(28rem,calc(100vw-2rem))] p-0"><Command>
                        <CommandInput placeholder="Find company, CIK or edition" aria-label="Find statement edition" />
                        <CommandList><CommandEmpty>No prepared editions found.</CommandEmpty>{catalog.data?.map((entry) => <CommandItem key={entry.edition_id} value={`${entry.company_name} ${entry.ticker} ${entry.scope.issuer_id} ${entry.label} ${entry.cutoff_at} ${entry.edition_id}`} onSelect={() => { cancelRead(); setSelectedEdition(entry.edition_id); setPickerOpen(false); }}>
                            <span className="min-w-0 [overflow-wrap:anywhere]">{entry.company_name} · {entry.ticker} · {entry.label}<span className="block text-xs text-muted-foreground">CIK {entry.scope.issuer_id} · cutoff {entry.cutoff_at}</span></span>
                        </CommandItem>)}</CommandList>
                    </Command></PopoverContent>
                </Popover>
                <Button type="button" disabled={!selected || operation.kind === 'pending'} onClick={readEdition}>Read prepared statements</Button>
                {selectedEdition !== null && saved && <Button type="button" variant="ghost" onClick={() => { cancelRead(); setSelectedEdition(null); }}>Return to saved version</Button>}
            </div>
            <RadioGroup aria-label="Statement frequency" value={frequency} onValueChange={changeFrequency} className="flex flex-wrap gap-3">
                {FREQUENCIES.map(({ id, label }) => <label key={id} className="flex min-h-10 cursor-pointer items-center gap-2 rounded-md border px-3 text-sm"><RadioGroupItem value={id} disabled={saved !== null && selectedEdition === null && !data?.statement_read} />{label}</label>)}
            </RadioGroup>
            {selected && <p className="text-xs text-muted-foreground">Prepared cutoff · {selected.cutoff_at}</p>}
            {canShowSaved && data?.statement_read && <p className="text-xs text-muted-foreground">Saved edition · {data.statement_read.edition.label} · cutoff {data.statement_read.edition.cutoff_at}</p>}
            {catalog.isLoading && <p role="status" className="text-sm">Loading prepared editions…</p>}
            {catalog.error && <Alert variant="warning"><AlertTitle>Edition list unavailable</AlertTitle><AlertDescription><Button type="button" variant="outline" size="sm" onClick={() => void catalog.mutate()}>Retry edition list</Button></AlertDescription></Alert>}
            {catalog.data?.length === 0 && <p className="text-sm text-muted-foreground">No prepared statement editions are available.</p>}
            {canShowSaved && periods.length > 0 && <label className="block text-xs">Selected period
                <select aria-label="Statement period" value={validPeriod ?? ''} onChange={(event) => saveStatementPeriod(event.target.value)} className="mt-1 block min-h-10 w-full max-w-full rounded-md border bg-background px-2 text-sm">
                    <option value="">All returned periods</option>{periods.map((period) => <option key={period.id} value={period.id}>{period.label}</option>)}
                </select>
            </label>}
            {canShowSaved && saved?.period && periods.length > 0 && !validPeriod && <p role="alert" className="text-sm text-warning-foreground">The linked period is not present in this saved artifact. Choose one of the returned periods.</p>}
        </div>
        {operation.kind === 'pending' && <p role="status" className="text-sm">Reading {operation.intent.frequency} statements…</p>}
        {operation.kind === 'failed' && <Alert variant="warning"><AlertTitle>Statement read failed</AlertTitle><AlertDescription>{operation.message}<Button type="button" variant="outline" size="sm" onClick={() => void read(operation.intent, operation.key, operation.edition)}>Retry statement read</Button></AlertDescription></Alert>}
        {canShowSaved && artifact.state?.kind === 'loading' && <p role="status" className="text-sm">Checking saved statement access…</p>}
        {canShowSaved && artifact.state?.kind === 'failed' && <Alert variant="warning"><AlertTitle>Saved statements unavailable</AlertTitle><AlertDescription>{artifact.state.message}<Button type="button" variant="outline" size="sm" onClick={artifact.retry}>Retry saved report</Button></AlertDescription></Alert>}
        {canShowSaved && annualReport && <AnnualStatementsTable report={annualReport} selectedPeriod={validPeriod} onSelectEvidence={onSelectEvidence} />}
        {canShowSaved && fiscalReport && <FiscalStatementsTable report={fiscalReport} selectedPeriod={validPeriod} onSelectEvidence={onSelectEvidence} />}
    </section>;
}
