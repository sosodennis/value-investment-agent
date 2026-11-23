import type { ReactNode } from 'react';
import type { PreparationSummary } from './fundamental-report-model';
import { InspectionValue, type EvidenceActionProps } from './report-value';

export function ValuationAssumptionsSection({
    preparation,
    revisionPanel,
    onSelectEvidence,
}: EvidenceActionProps & {
    preparation: PreparationSummary;
    revisionPanel?: ReactNode;
}) {
    return (
        <section aria-label="Assumptions" className="space-y-3 border-b pb-5">
            <div>
                <h3 className="font-semibold">Assumptions</h3>
                <p className="mt-1 text-sm text-muted-foreground">Saved report assumptions are read-only.</p>
            </div>
            {revisionPanel}
            {preparation.assumptions.length > 0 ? (
                <dl className="divide-y rounded-md border px-3">
                    {preparation.assumptions.map((item) => (
                        <div
                            key={item.evidence.id}
                            className="grid min-w-0 gap-2 py-3 @min-[36rem]:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]"
                        >
                            <dt className="min-w-0">
                                <span className="block break-words text-sm font-medium">
                                    {item.path.replace(/^assumptions\./, '').replaceAll('_', ' ')}
                                </span>
                                <span className="mt-1 block break-all text-xs text-muted-foreground">
                                    {item.path}
                                </span>
                                {item.revisionLabel && <span className="mt-1 block text-xs font-medium">{item.revisionLabel}</span>}
                            </dt>
                            <dd className="min-w-0 space-y-1 text-sm">
                                <InspectionValue
                                    evidence={item.evidence}
                                    onSelectEvidence={onSelectEvidence}
                                />
                                <p className="break-words text-xs text-muted-foreground">
                                    {item.method.replaceAll('_', ' ')} · {item.formula}
                                </p>
                            </dd>
                        </div>
                    ))}
                </dl>
            ) : (
                <p className="text-sm text-muted-foreground">No assumption evidence was supplied.</p>
            )}
            {preparation.historicalMetrics.length > 0 && (
                <details className="text-sm">
                    <summary className="cursor-pointer font-medium">
                        Historical metrics used in preparation
                    </summary>
                    <dl className="mt-3 grid gap-3 @min-[36rem]:grid-cols-2">
                        {preparation.historicalMetrics.map((metric) => (
                            <div key={`${metric.id}:${metric.year}`} className="min-w-0 border-l pl-3">
                                <dt className="break-words text-xs text-muted-foreground">
                                    {metric.id} · {metric.year} · {metric.periodEnd}
                                </dt>
                                <dd className="mt-1 break-all font-mono text-sm tabular-nums">
                                    {metric.value.raw} {metric.unit}
                                </dd>
                                <dd className="mt-1 break-words text-xs text-muted-foreground">
                                    {metric.formula}
                                </dd>
                            </div>
                        ))}
                    </dl>
                </details>
            )}
        </section>
    );
}
