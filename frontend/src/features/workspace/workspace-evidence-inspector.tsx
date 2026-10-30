import { ExternalLink, FileSearch, PanelRight } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { AgentOutputViewModel } from '@/types/agents/output-adapter';
import type { AgentInfo } from '@/types/agents';
import { isRecord, type UnknownRecord } from '@/types/preview';
import { cn } from '@/lib/cn';

export interface EvidenceSelection {
    id: string;
    title: string;
    value: string;
    source?: string;
    period?: string;
    formula?: string;
    confidence?: string;
    artifactId?: string;
    artifactUrl?: string;
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

        if (viewModel.kind === 'fundamental_analysis') {
            appendFinancialReportEvidence(items, agent, preview as UnknownRecord);
        }
    }
    return items;
}

function appendFinancialReportEvidence(
    items: EvidenceSelection[],
    agent: AgentInfo,
    preview: UnknownRecord,
) {
    if (!Array.isArray(preview.financial_reports)) return;
    const report = preview.financial_reports[0];
    if (!isRecord(report) || !isRecord(report.base)) return;

    const periodField = isTraceableField(report.base.period_end_date) ? report.base.period_end_date : undefined;
    const period = periodField?.value === null || periodField?.value === undefined
        ? undefined
        : String(periodField.value);
    const fields = Object.entries(report.base).filter(([key]) => key !== 'period_end_date');
    for (const [key, value] of fields) {
        if (items.length >= 12 || !isTraceableField(value) || value.value === null) continue;
        const provenance = isRecord(value.provenance) ? value.provenance : undefined;
        const concept = typeof provenance?.concept === 'string' ? provenance.concept : undefined;
        const expression = typeof provenance?.expression === 'string' ? provenance.expression : undefined;
        items.push({
            id: `${agent.id}:financial-report:${key}`,
            title: `Financial report · ${formatEvidenceLabel(key)}`,
            value: String(value.value),
            source: concept ? `SEC XBRL concept ${concept}` : 'Typed financial report artifact',
            period,
            formula: expression,
        });
    }
}

export function EvidenceInspector({
    items,
    selected,
    onSelect,
    className,
}: {
    items: EvidenceSelection[];
    selected: EvidenceSelection | null;
    onSelect: (item: EvidenceSelection) => void;
    className?: string;
}) {
    return (
        <aside aria-label="Evidence inspector" className={cn('flex min-h-0 min-w-0 flex-col bg-muted/10', className)}>
            <div className="flex items-center justify-between gap-3 border-b px-4 py-3">
                <div className="flex items-center gap-2">
                    <FileSearch aria-hidden="true" className="size-4 text-primary" />
                    <div>
                        <h2 className="text-sm font-semibold">Evidence inspector</h2>
                        <p className="text-xs text-muted-foreground">Select a report value to inspect its source.</p>
                    </div>
                </div>
                <Badge variant="outline">{items.length} items</Badge>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-3">
                {items.length === 0 ? (
                    <div className="grid min-h-40 place-items-center border border-dashed p-4 text-center text-sm text-muted-foreground">
                        <p>Evidence becomes available when a report artifact is loaded.</p>
                    </div>
                ) : (
                    <div className="grid gap-2">
                        {items.map((item) => (
                            <Button
                                key={item.id}
                                type="button"
                                variant={selected?.id === item.id ? 'secondary' : 'ghost'}
                                className="h-auto min-w-0 justify-start whitespace-normal border border-transparent px-3 py-2 text-left hover:border-border"
                                onClick={() => onSelect(item)}
                            >
                                <span className="min-w-0">
                                    <span className="block truncate text-xs font-semibold">{item.title}</span>
                                    <span className="mt-1 block break-words text-xs font-normal text-muted-foreground">{item.value}</span>
                                </span>
                            </Button>
                        ))}
                    </div>
                )}
                {selected ? <EvidenceDetail item={selected} /> : null}
            </div>
        </aside>
    );
}

function EvidenceDetail({ item }: { item: EvidenceSelection }) {
    return (
        <Card className="mt-4 border-primary/30">
            <CardHeader className="p-4 pb-3">
                <CardTitle className="text-sm">{item.title}</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-3 p-4 pt-0 text-sm">
                <div>
                    <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Value</p>
                    <p className="mt-1 break-words font-mono tabular-nums">{item.value}</p>
                </div>
                <dl className="grid gap-2 text-xs">
                    <EvidenceField label="Source" value={item.source} />
                    <EvidenceField label="Period" value={item.period} />
                    <EvidenceField label="Formula" value={item.formula} />
                    <EvidenceField label="Confidence" value={item.confidence} />
                </dl>
                {item.artifactUrl ? (
                    <Button asChild variant="outline" size="sm" className="justify-start">
                        <a href={item.artifactUrl} target="_blank" rel="noreferrer">
                            <ExternalLink aria-hidden="true" /> Open artifact
                        </a>
                    </Button>
                ) : null}
            </CardContent>
        </Card>
    );
}

function EvidenceField({ label, value }: { label: string; value?: string }) {
    return value ? (
        <div className="grid grid-cols-[5.5rem_minmax(0,1fr)] gap-2">
            <dt className="text-muted-foreground">{label}</dt>
            <dd className="break-words">{value}</dd>
        </div>
    ) : null;
}

function isInspectableValue(value: unknown): value is string | number | boolean {
    return typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean';
}

function isTraceableField(value: unknown): value is { value: string | number | null; provenance?: UnknownRecord | null } {
    return isRecord(value) && ('value' in value) && (value.value === null || typeof value.value === 'string' || typeof value.value === 'number');
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
