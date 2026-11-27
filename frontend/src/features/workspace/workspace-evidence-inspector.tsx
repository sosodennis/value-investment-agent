import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { Copy, ExternalLink, FileSearch, PanelRight } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Textarea } from '@/components/ui/textarea';
import type { AgentOutputViewModel } from '@/types/agents/output-adapter';
import type { AgentInfo } from '@/types/agents';
import { cn } from '@/lib/cn';

export interface EvidenceSelection {
    id: string;
    title: string;
    value: string;
    displayValue?: string;
    dataQuality?: string;
    assumptionMethod?: string;
    sourceUrl?: string;
    source?: string;
    citation?: string;
    licenseReference?: string;
    author?: string;
    modifiedAt?: string;
    rationale?: string;
    period?: string;
    formula?: string;
    confidence?: string;
    artifactId?: string;
    artifactUrl?: string;
    threadId?: string;
    runId?: string;
    preparationDigest?: string;
    originalPreparationDigest?: string;
    inputDigest?: string;
    resultHash?: string;
    inputs?: string[];
    dimensions?: string[];
    factId?: string;
    concept?: string;
    accessionNumber?: string;
    capturedAt?: string;
    availableAt?: string;
    filedAt?: string;
    parserVersion?: string;
    taxonomyVersion?: string;
    taxonomyManifestDigest?: string;
    mappingVersion?: string;
    sourceHash?: string;
    snapshotId?: string;
    snapshotManifestDigest?: string;
    unit?: string;
    scale?: number | null;
    issueCodes?: string[];
    statementId?: string;
    cellId?: string;
    rowId?: string;
    periodId?: string;
    selectedVersionId?: string;
    statementRelease?: string;
    statementCutoff?: string;
    contextId?: string;
    selectionKind?: string;
    sourceReportPeriodEnd?: string;
    mappingDigest?: string;
    cashBasis?: string;
    candidateFactIds?: string[];
    rejectedCandidates?: string[];
    statementEvidence?: string;
    editionId?: string;
    rawText?: string;
    sign?: string;
    decimals?: string;
    archiveMemberHash?: string;
    sourceBindingDigest?: string;
    formulaVersion?: string;
    evidenceLinks?: { id: string; label: string; relationship: string; coefficient?: -1 | 1 }[];
}

export function buildEvidenceItems(agent: AgentInfo, viewModel: AgentOutputViewModel): EvidenceSelection[] {
    const items: EvidenceSelection[] = [];
    if (viewModel.reference?.artifact_id) {
        items.push({
            id: `${agent.id}:artifact`,
            title: `${agent.name} report artifact`,
            value: viewModel.reference.artifact_id,
            source: 'Persisted run artifact',
            period: 'This exact thread and run',
            artifactId: viewModel.reference.artifact_id,
            artifactUrl: viewModel.reference.download_url,
        });
    }
    if (viewModel.summary) {
        items.push({
            id: `${agent.id}:summary`,
            title: `${agent.name} summary`,
            value: viewModel.summary,
            source: 'Agent output summary',
            period: 'This exact run',
            artifactId: viewModel.reference?.artifact_id,
            artifactUrl: viewModel.reference?.download_url,
        });
    }

    const preview = viewModel.preview;
    if (preview && typeof preview === 'object') {
        for (const [key, value] of Object.entries(preview)) {
            if (!isInspectableValue(value)) continue;
            items.push({
                id: `${agent.id}:value:${key}`,
                title: formatEvidenceLabel(key),
                value: formatEvidenceValue(value),
                source: viewModel.reference?.artifact_id ? `Artifact ${viewModel.reference.artifact_id}` : 'Typed report preview',
                period: 'This exact run',
                artifactId: viewModel.reference?.artifact_id,
                artifactUrl: viewModel.reference?.download_url,
            });
            if (items.length >= 8) break;
        }
    }
    return items;
}

export function EvidenceInspector({
    items,
    selected,
    onSelect,
    className,
    headerAction,
}: {
    items: EvidenceSelection[];
    selected: EvidenceSelection | null;
    onSelect: (item: EvidenceSelection) => void;
    className?: string;
    headerAction?: ReactNode;
}) {
    return (
        <aside aria-label="Evidence inspector" className={cn('flex min-h-0 min-w-0 flex-col bg-muted/10', className)}>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b px-4 py-3">
                <div className="flex min-w-0 flex-1 items-center gap-2">
                    <FileSearch aria-hidden="true" className="size-4 shrink-0 text-primary" />
                    <div className="min-w-0">
                        <h2 className="text-sm font-semibold">Evidence inspector</h2>
                        <p className="text-xs text-muted-foreground">Select a report value to inspect its source.</p>
                    </div>
                </div>
                <Badge variant="outline" className="shrink-0">{items.length} items</Badge>
                {headerAction}
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-3">
                {selected ? <EvidenceDetail key={`detail:${selected.id}`} item={selected} items={items} onSelect={onSelect} /> : null}
                {items.length === 0 ? (
                    <div className="grid min-h-40 place-items-center border border-dashed p-4 text-center text-sm text-muted-foreground">
                        <p>Evidence becomes available when a report artifact is loaded.</p>
                    </div>
                ) : (
                    <EvidenceInventory key={`inventory:${selected?.id ?? 'unselected'}`} items={items} selected={selected} onSelect={onSelect} />
                )}
            </div>
        </aside>
    );
}

function EvidenceInventory({ items, selected, onSelect }: { items: EvidenceSelection[]; selected: EvidenceSelection | null; onSelect: (item: EvidenceSelection) => void }) {
    const [open, setOpen] = useState(selected === null);
    return <details open={open} onToggle={(event) => setOpen(event.currentTarget.open)} className="mt-3 min-w-0">
        <summary className="cursor-pointer rounded-sm py-2 text-sm font-medium">Browse all evidence ({items.length})</summary>
        {open && <div className="grid gap-2">{items.map((item) => <Button
            key={item.id} type="button" variant={selected?.id === item.id ? 'secondary' : 'ghost'}
            className="h-auto min-w-0 justify-start whitespace-normal border border-transparent px-3 py-2 text-left hover:border-border"
            onClick={() => onSelect(item)}
        ><span className="min-w-0">
            <span className="block truncate text-xs font-semibold">{item.title}</span>
            <span className="mt-1 block text-xs font-normal text-muted-foreground [overflow-wrap:anywhere]">{item.displayValue ?? item.value}</span>
        </span></Button>)}</div>}
    </details>;
}

function EvidenceDetail({ item, items, onSelect }: { item: EvidenceSelection; items: EvidenceSelection[]; onSelect: (item: EvidenceSelection) => void }) {
    const rawId = useId();
    const detail = useRef<HTMLDivElement>(null);
    const rawField = useRef<HTMLTextAreaElement>(null);
    const displayField = useRef<HTMLTextAreaElement>(null);
    const [copy, setCopy] = useState<{ kind: 'idle' } | { kind: 'pending' | 'copied' | 'failed'; target: 'raw' | 'display' }>({ kind: 'idle' });
    const sourceUrl = safeSourceUrl(item.sourceUrl);
    useEffect(() => { detail.current?.focus(); }, [item.id]);
    useEffect(() => {
        if (copy.kind !== 'failed') return;
        const field = copy.target === 'raw' ? rawField.current : displayField.current;
        field?.focus();
        field?.select();
    }, [copy]);
    async function copyValue(target: 'raw' | 'display') {
        setCopy({ kind: 'pending', target });
        try {
            await navigator.clipboard.writeText(target === 'raw' ? item.value : item.displayValue ?? item.value);
            setCopy({ kind: 'copied', target });
        } catch {
            setCopy({ kind: 'failed', target });
        }
    }
    return (
        <div ref={detail} tabIndex={-1} aria-label={`${item.title} details`} className="min-w-0 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"><Card className="min-w-0 border-primary/30">
            <CardHeader className="p-4 pb-3">
                <CardTitle className="text-sm">{item.title}</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-3 p-4 pt-0 text-sm">
                <div>
                    <p className="text-xs font-medium text-muted-foreground">Displayed value</p>
                    <p className="mt-1 font-mono tabular-nums [overflow-wrap:anywhere]">{item.displayValue ?? item.value}</p>
                    <label htmlFor={rawId} className="mt-3 block text-xs font-medium text-muted-foreground">Original value · full precision</label>
                    <Textarea id={rawId} ref={rawField} readOnly value={item.value} rows={3} className="mt-1 min-h-16 resize-y font-mono text-xs [overflow-wrap:anywhere]" />
                    <div className="mt-2 flex flex-wrap gap-2">
                        <Button type="button" variant="outline" size="sm" disabled={copy.kind === 'pending'} onClick={() => void copyValue('raw')}><Copy aria-hidden="true" />Copy original value</Button>
                        <Button type="button" variant="outline" size="sm" disabled={copy.kind === 'pending'} onClick={() => void copyValue('display')}><Copy aria-hidden="true" />Copy displayed value</Button>
                    </div>
                    <p role="status" className="mt-2 text-xs text-muted-foreground">
                        {copy.kind === 'copied' ? `${copy.target === 'raw' ? 'Original' : 'Displayed'} value copied.` : copy.kind === 'failed' ? `Clipboard unavailable. Select the ${copy.target === 'raw' ? 'original value above' : 'displayed value below'} and copy it manually.` : copy.kind === 'pending' ? 'Copying value…' : ''}
                    </p>
                    {copy.kind === 'failed' && copy.target === 'display' && <Textarea ref={displayField} aria-label="Displayed value for manual copy" readOnly value={item.displayValue ?? item.value} rows={2} className="mt-2 font-mono text-xs" />}
                </div>
                <dl className="grid gap-2 text-xs">
                    <EvidenceField label="Selection" value={item.selectionKind?.replaceAll('_', ' ')} />
                    <EvidenceField label="Source report end" value={item.sourceReportPeriodEnd} />
                    <EvidenceField label="Cash definition" value={item.cashBasis?.replaceAll('_', ' ')} />
                    <EvidenceField label="Source" value={item.source} />
                    <EvidenceField label="Citation" value={item.citation} />
                    <EvidenceField label="License" value={item.licenseReference} />
                    <EvidenceField label="Author" value={item.author} />
                    <EvidenceField label="Modified" value={item.modifiedAt} />
                    <EvidenceField label="Reason" value={item.rationale} />
                    <EvidenceField label="Period" value={item.period} />
                    <EvidenceField label="Formula" value={item.formula} />
                    <EvidenceField label="Formula version" value={item.formulaVersion} />
                    <EvidenceField label="Reported raw text" value={item.rawText} />
                    <EvidenceField label="Reported sign" value={item.sign} />
                    <EvidenceField label="Reported decimals" value={item.decimals} />
                    <EvidenceField label="Data quality" value={item.dataQuality} />
                    <EvidenceField label="Assumption method" value={item.assumptionMethod} />
                    <EvidenceField label="Evidence assessment" value={item.confidence} />
                    <EvidenceField label="Inputs" value={item.inputs?.join(', ') || undefined} />
                    <EvidenceField label="Dimensions" value={item.dimensions?.join(', ') || undefined} />
                    <EvidenceField label="Concept" value={factMetadataValue(item, item.concept)} />
                    <EvidenceField label="Accession" value={factMetadataValue(item, item.accessionNumber)} />
                    <EvidenceField label="Unit" value={factMetadataValue(item, item.unit)} />
                    <EvidenceField label="Source scale" value={item.scale === undefined ? undefined : item.scale === null ? 'Unspecified' : String(item.scale)} />
                    <EvidenceField label="Issue codes" value={formatIssueCodes(item)} />
                </dl>
                {item.evidenceLinks && item.evidenceLinks.length > 0 && <section aria-label="Statement lineage" className="min-w-0 space-y-2">
                    <h3 className="text-sm font-semibold">Inputs and verification</h3>
                    <p className="text-xs text-muted-foreground">Follow a signed input to its quarterly value or reported source. Parent links return to the value that uses this evidence.</p>
                    <ul className="space-y-2">{item.evidenceLinks.map((link, index) => {
                        const target = items.find((candidate) => candidate.id === link.id);
                        return <li key={`${link.relationship}:${link.id}:${index}`}>
                            {target && <Button type="button" variant="outline" aria-label={`${link.coefficient === undefined ? '' : `${link.coefficient > 0 ? '+1' : '−1'} · `}${link.relationship} ${target.title}`} className="h-auto min-h-10 w-full justify-start whitespace-normal text-left text-xs" onClick={() => onSelect(target)}>
                                <span className="min-w-0 [overflow-wrap:anywhere]">
                                    <span className="block font-medium">{link.coefficient === undefined ? '' : `${link.coefficient > 0 ? '+1' : '−1'} · `}{link.relationship}</span>
                                    <span className="mt-1 block">{target.title}</span>
                                    {link.relationship === 'candidate' && <span className="mt-1 block text-muted-foreground">{link.label}</span>}
                                </span>
                            </Button>}
                        </li>;
                    })}</ul>
                </section>}
                {item.statementEvidence && <details className="min-w-0 rounded-md border px-3 py-2 text-xs">
                    <summary className="cursor-pointer font-medium">Complete statement selection evidence</summary>
                    <Textarea aria-label="Statement cell and candidate evidence" readOnly value={item.statementEvidence} rows={12} className="mt-3 font-mono text-xs" />
                </details>}
                <details className="min-w-0 rounded-md border px-3 py-2 text-xs">
                    <summary className="cursor-pointer font-medium">Technical identity</summary>
                    <dl className="mt-3 grid gap-2">
                    <EvidenceField label="Thread" value={item.threadId} />
                    <EvidenceField label="Run" value={item.runId} />
                    <EvidenceField label="Artifact" value={item.artifactId} />
                    <EvidenceField label="Preparation" value={item.preparationDigest} />
                    <EvidenceField label="Original automatic preparation digest" value={item.originalPreparationDigest} />
                    <EvidenceField label="Input digest" value={item.inputDigest} />
                    <EvidenceField label="Result hash" value={item.resultHash} />
                    <EvidenceField label="Statement" value={item.statementId} />
                    <EvidenceField label="Statement cutoff" value={item.statementCutoff} />
                    <EvidenceField label="Statement release" value={item.statementRelease} />
                    <EvidenceField label="Edition" value={item.editionId} />
                    <EvidenceField label="Source binding" value={item.sourceBindingDigest} />
                    <EvidenceField label="Archive member hash" value={item.archiveMemberHash} />
                    <EvidenceField label="Cell" value={item.cellId} />
                    <EvidenceField label="Row" value={item.rowId} />
                    <EvidenceField label="Period identity" value={item.periodId} />
                    <EvidenceField label="Selected version" value={item.selectedVersionId} />
                    <EvidenceField label="Context ID" value={item.contextId} />
                    <EvidenceField label="Mapping digest" value={item.mappingDigest} />
                    <EvidenceField label="Candidate facts" value={item.candidateFactIds?.join(', ')} />
                    <EvidenceField label="Rejected candidates" value={item.rejectedCandidates?.join('; ')} />
                    <EvidenceField label="Fact ID" value={item.factId} />
                    <EvidenceField label="Filed at" value={factMetadataValue(item, item.filedAt)} />
                    <EvidenceField label="Available at" value={factMetadataValue(item, item.availableAt)} />
                    <EvidenceField label="Captured at" value={factMetadataValue(item, item.capturedAt)} />
                    <EvidenceField label="Parser" value={factMetadataValue(item, item.parserVersion)} />
                    <EvidenceField label="Taxonomy" value={factMetadataValue(item, item.taxonomyVersion)} />
                    <EvidenceField label="Taxonomy manifest" value={factMetadataValue(item, item.taxonomyManifestDigest)} />
                    <EvidenceField label="Mapping" value={factMetadataValue(item, item.mappingVersion)} />
                    <EvidenceField label="Source hash" value={factMetadataValue(item, item.sourceHash)} />
                    <EvidenceField label="Snapshot" value={factMetadataValue(item, item.snapshotId)} />
                    <EvidenceField label="Snapshot manifest" value={factMetadataValue(item, item.snapshotManifestDigest)} />
                    </dl>
                </details>
                {sourceUrl && <Button asChild variant="outline" size="sm" className="justify-start"><a href={sourceUrl} target="_blank" rel="noreferrer"><ExternalLink aria-hidden="true" />Open source document</a></Button>}
                {item.artifactUrl ? (
                    <Button asChild variant="outline" size="sm" className="justify-start">
                        <a href={item.artifactUrl} target="_blank" rel="noreferrer">
                            <ExternalLink aria-hidden="true" /> Open artifact
                        </a>
                    </Button>
                ) : null}
            </CardContent>
        </Card></div>
    );
}

function EvidenceField({ label, value }: { label: string; value?: string }) {
    return value ? (
        <div className="grid grid-cols-[5.5rem_minmax(0,1fr)] gap-2">
            <dt className="text-muted-foreground">{label}</dt>
            <dd className="min-w-0 [overflow-wrap:anywhere]">{value}</dd>
        </div>
    ) : null;
}

function safeSourceUrl(value: string | undefined): string | null {
    if (!value) return null;
    try {
        const url = new URL(value);
        return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null;
    } catch {
        return null;
    }
}

function factMetadataValue(item: EvidenceSelection, value: string | undefined): string | undefined {
    if (!item.factId) return value;
    return value ?? 'Unavailable';
}

function formatIssueCodes(item: EvidenceSelection): string | undefined {
    if (!item.factId && !item.cellId) return undefined;
    if (item.issueCodes === undefined) return 'Unavailable';
    return item.issueCodes.length === 0 ? 'None' : item.issueCodes.join(', ');
}

function isInspectableValue(value: unknown): value is string | number | boolean {
    return typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean';
}

function formatEvidenceLabel(value: string) {
    return value.replaceAll('_', ' ').replace(/\b\w/g, (character) => character.toUpperCase());
}

function formatEvidenceValue(value: string | number | boolean) {
    return typeof value === 'number' ? value.toLocaleString(undefined, { maximumFractionDigits: 6 }) : String(value);
}

export function EvidenceInspectorTrigger({ onClick }: { onClick?: () => void } = {}) {
    return (
        <Button type="button" variant="outline" size="sm" onClick={onClick}>
            <PanelRight aria-hidden="true" /> Evidence
        </Button>
    );
}
