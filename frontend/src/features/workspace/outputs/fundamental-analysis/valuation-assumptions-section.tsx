import type { ReactNode } from 'react';
import type { FundamentalValuationModel, PreparationSummary } from './fundamental-report-model';
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
                <details className="rounded-md border px-3 py-2">
                <summary className="cursor-pointer text-sm font-medium">All assumptions ({preparation.assumptions.length})</summary>
                <dl className="mt-2 divide-y">
                    {preparation.assumptions.map((item) => (
                        <div
                            key={item.evidence.id}
                            className="grid min-w-0 gap-2 py-3 @min-[36rem]:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]"
                        >
                            <dt className="min-w-0">
                                <span className="block break-words text-sm font-medium">
                                    {item.path.replace(/^assumptions\./, '').replaceAll('_', ' ')}
                                </span>
                                <span className="mt-1 block [overflow-wrap:anywhere] text-xs text-muted-foreground">
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
                </details>
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
                                <dd className="mt-1 [overflow-wrap:anywhere] font-mono text-sm tabular-nums">
                                    <InspectionValue evidence={metric.evidence} onSelectEvidence={onSelectEvidence} />
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

export function ValuationKeyAssumptions({ report, onSelectEvidence }: EvidenceActionProps & { report: FundamentalValuationModel }) {
    const assumptions = report.preparationSummary?.assumptions ?? [];
    const terminalGrowth = assumptions.filter((item) => item.path === 'assumptions.terminal_growth');
    const waccNode = report.base.nodes.find((item) => item.id === 'wacc');
    const waccAssumption = assumptions.find((item) => item.path === 'assumptions.wacc');
    const revenueGrowth = assumptions.find((item) => item.path === 'assumptions.forecast.revenue_growth[0]');
    const beta = assumptions.find((item) => item.path === 'assumptions.wacc.beta');
    const reinvestment = assumptions.find((item) => item.path === 'assumptions.forecast.reinvestment_rate[0]');
    const rows = [
        ...(waccNode ? [{ label: 'WACC', evidence: waccNode.evidence }] : waccAssumption ? [{ label: 'WACC', evidence: waccAssumption.evidence }] : []),
        ...terminalGrowth.map((item) => ({ label: `Terminal growth · ${item.isManual ? 'manual' : 'automatic'}`, evidence: item.evidence })),
        ...(revenueGrowth ? [{ label: 'Revenue growth · Year 1', evidence: revenueGrowth.evidence }] : []),
        ...(beta ? [{ label: 'Beta', evidence: beta.evidence }] : []),
        ...(reinvestment ? [{ label: 'Reinvestment · Year 1', evidence: reinvestment.evidence }] : []),
    ];
    if (rows.length === 0) return null;
    return <section aria-label="Key assumptions" className="space-y-2">
        <h3 className="text-sm font-semibold">Key assumptions</h3>
        <dl className="grid grid-cols-1 gap-3 @min-[26rem]:grid-cols-2 @min-[48rem]:grid-cols-4">
            {rows.map((row) => <div key={row.evidence.id} className="min-w-0 border-l pl-3">
                <dt className="text-xs text-muted-foreground">{row.label}</dt>
                <dd className="mt-1 text-sm"><InspectionValue evidence={row.evidence} onSelectEvidence={onSelectEvidence} /></dd>
                <dd className="mt-1 text-xs text-muted-foreground">Method · {row.evidence.assumptionMethod?.replaceAll('_', ' ') ?? 'service calculation'}</dd>
            </div>)}
        </dl>
    </section>;
}
