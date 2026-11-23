import type { FundamentalReportModel } from './fundamental-report-model';
import { InspectionValue, type EvidenceActionProps } from './report-value';

export function FundamentalReportSources({
    report,
    onSelectEvidence,
}: EvidenceActionProps & { report: FundamentalReportModel }) {
    const preparation = report.kind === 'valuation' || report.kind === 'preparation-outcome' ? report.preparationSummary : null;
    return (
        <details className="rounded-md border p-3 text-sm">
            <summary className="cursor-pointer font-semibold">Sources &amp; method</summary>
            <div className="mt-4 space-y-4">
                <dl className="grid gap-3 @min-[36rem]:grid-cols-2">
                    <Metadata label="Thread" value={report.identity.threadId} />
                    <Metadata label="Run" value={report.identity.runId} />
                    <Metadata label="Artifact" value={report.identity.artifactId} />
                    <Metadata label="Preparation digest" value={report.identity.preparationDigest} />
                </dl>
                {preparation && (
                    <dl className="grid gap-3 border-t pt-3 @min-[36rem]:grid-cols-2">
                        <Metadata label="Prepared model" value={`${preparation.modelId} · ${preparation.modelVersion}`} />
                        <Metadata label="Preparation policy" value={`${preparation.policyId} · ${preparation.policyVersion}`} />
                        <Metadata label="Preparation status" value={preparation.status} />
                    </dl>
                )}
                {report.kind === 'facts-only' && (
                    <dl className="grid gap-3 border-t pt-3 @min-[36rem]:grid-cols-2">
                        <Metadata label="Snapshot" value={report.snapshotId} />
                        <Metadata label="Valuation date" value={report.valuationDate} />
                    </dl>
                )}
                {report.kind === 'valuation' && (
                    <>
                        <dl className="grid gap-3 border-t pt-3 @min-[36rem]:grid-cols-2">
                            <Metadata label="Snapshot" value={report.snapshotId} />
                            <Metadata label="Snapshot digest" value={report.snapshotDigest} />
                            <Metadata label="Data release digest" value={report.releaseDigest} />
                            <Metadata label="Report input digest" value={report.reportBinding.inputDigest} />
                            <Metadata label="Report result hash" value={report.reportBinding.resultHash} />
                            <Metadata label="Base input digest" value={report.base.binding.inputDigest} />
                            <Metadata label="Base result hash" value={report.base.binding.resultHash} />
                            <Metadata label="Evaluated" value={report.base.evaluatedAt} />
                        </dl>
                        <div className="space-y-3 border-t pt-3">
                            <h3 className="text-sm font-semibold">
                                Calculation nodes · {report.calculationVersion}
                            </h3>
                            {report.base.nodes.length > 0 ? (
                                <dl className="divide-y">
                                    {report.base.nodes.map((node) => (
                                        <div
                                            key={node.evidence.id}
                                            className="grid gap-2 py-3 @min-[36rem]:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]"
                                        >
                                            <dt className="break-words text-xs font-medium">{node.id}</dt>
                                            <dd className="min-w-0 space-y-1 text-xs">
                                                <p>
                                                    <InspectionValue
                                                        evidence={node.evidence}
                                                        onSelectEvidence={onSelectEvidence}
                                                    />
                                                </p>
                                                <p className="break-words text-muted-foreground">
                                                    {node.formula}
                                                </p>
                                                <p className="break-words text-muted-foreground">
                                                    Inputs · {node.inputs.join(', ') || 'None supplied'}
                                                </p>
                                            </dd>
                                        </div>
                                    ))}
                                </dl>
                            ) : (
                                <p className="text-xs text-muted-foreground">
                                    No calculation nodes were supplied.
                                </p>
                            )}
                        </div>
                        <div className="space-y-2 border-t pt-3">
                            <h3 className="text-sm font-semibold">Service evidence references</h3>
                            {[
                                ...report.base.evidenceReferences,
                                ...(report.uncertainty.kind === 'provided'
                                    ? report.uncertainty.evidenceReferences
                                    : []),
                            ].map((item) => (
                                <p
                                    key={`${item.artifact_id}:${item.content_hash}`}
                                    className="break-all font-mono text-xs text-muted-foreground"
                                >
                                    {item.artifact_type} · {item.artifact_id} · {item.content_hash}
                                </p>
                            ))}
                        </div>
                    </>
                )}
            </div>
        </details>
    );
}

function Metadata({ label, value }: { label: string; value: string | null }) {
    return (
        <div className="min-w-0">
            <dt className="text-xs text-muted-foreground">{label}</dt>
            <dd className="mt-1 break-all font-mono text-xs">{value ?? 'Unavailable'}</dd>
        </div>
    );
}
