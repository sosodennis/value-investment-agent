import { memo, useMemo } from 'react';
import { Info } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import {
    Table,
    TableBody,
    TableCaption,
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
import { sortFundamentalFacts } from '@/types/agents/fundamental-service-facts';
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
        () => sortFundamentalFacts(facts.facts),
        [facts.facts],
    );
    const familyLabel = facts.identity.family ? FAMILY_LABELS[facts.identity.family] : 'Family unspecified';
    const hasQualityWarning = facts.quality_status !== 'verified' || facts.issue_codes.length > 0;
    const qualityAlertVariant = qualityAlertTone(facts.quality_status);

    if (sortedFacts.length === 0) {
        return (
            <section aria-label="Fundamental service facts" className="w-full py-2">
                <Alert role="status">
                    <Info aria-hidden="true" className="size-4 text-muted-foreground" />
                    <AlertTitle>No canonical facts available</AlertTitle>
                    <AlertDescription>
                        The Fundamental service returned no selectable facts for snapshot{' '}
                        <span className="break-all font-mono text-foreground">{facts.snapshot_id}</span>.
                        {facts.issue_codes.length > 0 && (
                            <span className="mt-1 block break-all">Issues: {facts.issue_codes.join(', ')}</span>
                        )}
                    </AlertDescription>
                </Alert>
            </section>
        );
    }

    return (
        <section aria-label="Fundamental service facts" className="w-full py-2">
            {hasQualityWarning && (
                <Alert
                    role={facts.quality_status === 'error' ? 'alert' : 'status'}
                    variant={qualityAlertVariant}
                    className="mb-3"
                >
                    <Info aria-hidden="true" className="size-4" />
                    <AlertTitle>Facts quality: {facts.quality_status}</AlertTitle>
                    {facts.issue_codes.length > 0 && (
                        <AlertDescription className="break-all">
                            Issues: {facts.issue_codes.join(', ')}
                        </AlertDescription>
                    )}
                </Alert>
            )}
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
                        {facts.data_release_manifest_digest && (
                            <div>
                                <dt className="inline">Data release: </dt>
                                <dd className="inline break-all font-mono text-foreground">
                                    {facts.data_release_manifest_digest}
                                </dd>
                            </div>
                        )}
                    </dl>
                </div>
                <div className="overflow-x-auto">
                    <Table>
                        <TableHeader>
                            <TableRow className="bg-background hover:bg-background">
                        <TableHead scope="col" className="min-w-48">Canonical fact</TableHead>
                        <TableHead scope="col" className="min-w-48">Value</TableHead>
                        <TableHead scope="col">Period</TableHead>
                        <TableHead scope="col">Unit</TableHead>
                        <TableHead scope="col">Quality</TableHead>
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
                        <TableCaption className="px-3 pb-3 text-left">
                            Canonical facts selected from the immutable {facts.snapshot_id} snapshot.
                        </TableCaption>
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
    const value = formatFactValue(fact.value);
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
                {formatFactUnit(fact)}
            </TableCell>
            <TableCell>
                <Badge variant={qualityVariant(fact.quality)} aria-label={`Quality: ${fact.quality}`}>
                    {fact.quality}
                </Badge>
                {fact.issue_codes.length > 0 && (
                    <span className="mt-1 block max-w-32 break-all text-xs text-muted-foreground">
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

function formatFactValue(value: FundamentalFactValue): string {
    switch (value.kind) {
        case 'numeric': {
            return Number.isFinite(value.numeric)
                ? value.numeric.toLocaleString(undefined, { maximumFractionDigits: 6 })
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

function formatFactUnit(fact: FundamentalCanonicalFact): string {
    const unit = fact.currency && fact.currency !== fact.unit
        ? `${fact.currency} · ${fact.unit}`
        : fact.unit;
    return fact.scale === 0 ? unit : `${unit} · 10^${fact.scale}`;
}

function qualityVariant(value: FundamentalCanonicalFact['quality'] | FundamentalFactsReadResult['quality_status']): 'success' | 'warning' | 'destructive' | 'secondary' {
    if (value === 'verified') return 'success';
    if (value === 'error' || value === 'abstain') return 'destructive';
    if (value === 'unsupported') return 'secondary';
    return 'warning';
}

function qualityAlertTone(value: FundamentalFactsReadResult['quality_status']): 'success' | 'warning' | 'destructive' {
    const variant = qualityVariant(value);
    return variant === 'destructive' ? 'destructive' : variant === 'success' ? 'success' : 'warning';
}

export const FinancialTable = memo(FinancialTableComponent);
