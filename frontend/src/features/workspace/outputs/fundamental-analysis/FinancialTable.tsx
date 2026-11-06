import { memo, useMemo } from 'react';
import { Info } from 'lucide-react';
import { Card } from '@/components/ui/card';
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from '@/components/ui/table';
import type { ArtifactReference } from '@/types/agents';
import type {
    FundamentalCanonicalFact,
    FundamentalFactsReadResult,
    FundamentalFactValue,
} from '@/types/agents/fundamental-service-facts';
import type { EvidenceSelection } from '../../workspace-evidence-inspector';

interface FinancialTableProps {
    facts: FundamentalFactsReadResult;
    artifactReference?: ArtifactReference | null;
    onSelectEvidence?: (item: EvidenceSelection) => void;
}

const FAMILY_LABELS = {
    bank: 'Bank',
    industrial: 'Industrial',
    reit: 'REIT',
} as const;

const FinancialTableComponent = ({ facts, artifactReference, onSelectEvidence }: FinancialTableProps) => {
    const sortedFacts = useMemo(
        () => [...facts.facts].sort((left, right) => left.normalized_field.localeCompare(right.normalized_field)),
        [facts.facts],
    );
    const familyLabel = facts.identity.family ? FAMILY_LABELS[facts.identity.family] : 'Family unspecified';

    if (sortedFacts.length === 0) return null;

    return (
        <section aria-label="Fundamental service facts" className="w-full py-2">
            <Card className="overflow-hidden">
                <div className="flex flex-wrap items-start justify-between gap-3 border-b bg-muted/50 px-4 py-3">
                    <div className="min-w-0">
                        <h3 className="flex items-center gap-2 font-semibold text-foreground">
                            <Info aria-hidden="true" className="size-4 text-primary" />
                            Service facts · <span className="text-primary">{facts.identity.issuer_name}</span>
                        </h3>
                        <p className="mt-1 text-xs text-muted-foreground">
                            {familyLabel} · {facts.identity.reporting_basis} · {facts.identity.currency} · {sortedFacts.length} selected facts
                        </p>
                    </div>
                    <dl className="grid min-w-0 gap-1 text-right text-xs text-muted-foreground">
                        <div>
                            <dt className="inline">Snapshot: </dt>
                            <dd className="inline break-all font-mono text-foreground">{facts.snapshot_id}</dd>
                        </div>
                        <div>
                            <dt className="inline">Manifest: </dt>
                            <dd className="inline break-all font-mono text-foreground">{facts.snapshot_manifest_digest}</dd>
                        </div>
                    </dl>
                </div>
                <div className="overflow-x-auto">
                    <Table>
                        <TableHeader>
                            <TableRow className="bg-background hover:bg-background">
                                <TableHead className="min-w-48">Canonical fact</TableHead>
                                <TableHead className="min-w-48">Value</TableHead>
                                <TableHead>Period</TableHead>
                                <TableHead>Unit</TableHead>
                                <TableHead>Quality</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {sortedFacts.map((fact) => (
                                <FactRow
                                    key={fact.fact_id}
                                    fact={fact}
                                    snapshotId={facts.snapshot_id}
                                    snapshotManifestDigest={facts.snapshot_manifest_digest}
                                    artifactReference={artifactReference}
                                    onSelectEvidence={onSelectEvidence}
                                />
                            ))}
                        </TableBody>
                    </Table>
                </div>
            </Card>
        </section>
    );
};

function FactRow({
    fact,
    snapshotId,
    snapshotManifestDigest,
    artifactReference,
    onSelectEvidence,
}: {
    fact: FundamentalCanonicalFact;
    snapshotId: string;
    snapshotManifestDigest: string;
    artifactReference?: ArtifactReference | null;
    onSelectEvidence?: (item: EvidenceSelection) => void;
}) {
    const value = formatFactValue(fact.value, fact.scale);
    const period = fact.period.kind === 'instant'
        ? `Instant · ${fact.period.instant}`
        : `${fact.period.start} → ${fact.period.end}`;
    const evidence = buildFactEvidence({
        fact,
        value,
        period,
        snapshotId,
        snapshotManifestDigest,
        artifactReference,
    });

    return (
        <TableRow>
            <TableCell>
                <div className="font-medium text-foreground">{formatLabel(fact.normalized_field)}</div>
                <div className="mt-1 break-all font-mono text-xs text-muted-foreground" title={fact.fact_id}>{fact.fact_id}</div>
            </TableCell>
            <TableCell className="font-mono tabular-nums">
                {onSelectEvidence ? (
                    <button
                        type="button"
                        className="max-w-full rounded-sm border-b border-dashed border-primary/50 text-left text-primary underline-offset-2 hover:bg-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        aria-label={`Inspect ${formatLabel(fact.normalized_field)} evidence`}
                        onClick={() => onSelectEvidence(evidence)}
                    >
                        {value}
                    </button>
                ) : value}
            </TableCell>
            <TableCell className="whitespace-nowrap text-xs text-muted-foreground">{period}</TableCell>
            <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                {fact.currency ? `${fact.currency} · ` : ''}{fact.unit}{fact.scale === 0 ? '' : ` · 10^${fact.scale}`}
            </TableCell>
            <TableCell>
                <span className={qualityClass(fact.quality)}>{fact.quality}</span>
                {fact.issue_codes.length > 0 && (
                    <span className="mt-1 block max-w-32 break-words text-xs text-muted-foreground">
                        {fact.issue_codes.join(', ')}
                    </span>
                )}
            </TableCell>
        </TableRow>
    );
}

function buildFactEvidence({
    fact,
    value,
    period,
    snapshotId,
    snapshotManifestDigest,
    artifactReference,
}: {
    fact: FundamentalCanonicalFact;
    value: string;
    period: string;
    snapshotId: string;
    snapshotManifestDigest: string;
    artifactReference?: ArtifactReference | null;
}): EvidenceSelection {
    const source = fact.source;
    return {
        id: `fundamental:service-fact:${fact.fact_id}`,
        title: `Service fact · ${formatLabel(fact.normalized_field)}`,
        value,
        source: `${source.source_role} · ${source.source_url}`,
        period,
        confidence: `${fact.quality}${fact.mapping_confidence ? ` · mapping ${fact.mapping_confidence}` : ''}`,
        artifactId: artifactReference?.artifact_id,
        artifactUrl: artifactReference?.download_url,
        factId: fact.fact_id,
        concept: fact.concept,
        accessionNumber: fact.accession_number ?? source.accession_number,
        capturedAt: fact.captured_at,
        availableAt: fact.available_at,
        filedAt: fact.filed_at ?? source.filed_at,
        parserVersion: source.parser_version,
        taxonomyVersion: fact.taxonomy_version,
        taxonomyManifestDigest: source.taxonomy_manifest_digest,
        mappingVersion: source.mapping_version,
        sourceHash: source.source_hash,
        snapshotId,
        snapshotManifestDigest,
        unit: fact.unit,
        scale: fact.scale,
        issueCodes: fact.issue_codes,
    };
}

function formatFactValue(value: FundamentalFactValue, scale: number): string {
    switch (value.kind) {
        case 'numeric': {
            const scaled = value.numeric * (10 ** scale);
            return Number.isFinite(scaled)
                ? scaled.toLocaleString(undefined, { maximumFractionDigits: 6 })
                : value.raw;
        }
        case 'text':
            return value.value;
        case 'boolean':
            return value.value ? 'True' : 'False';
        case 'missing':
            return `Unavailable · ${value.status}: ${value.reason}`;
        default: {
            const unreachable: never = value;
            return unreachable;
        }
    }
}

function formatLabel(value: string): string {
    return value.replaceAll('_', ' ').replace(/\b\w/g, (character) => character.toUpperCase());
}

function qualityClass(value: FundamentalCanonicalFact['quality']): string {
    if (value === 'verified') return 'text-xs font-medium text-success';
    if (value === 'error' || value === 'abstain') return 'text-xs font-medium text-destructive';
    return 'text-xs font-medium text-warning';
}

export const FinancialTable = memo(FinancialTableComponent);
