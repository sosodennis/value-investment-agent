import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import type { FundamentalValuationModel } from './fundamental-report-model';
import { ExactValue, InspectionValue, type EvidenceActionProps } from './report-value';

export function ValuationSummary({ report, onSelectEvidence }: EvidenceActionProps & { report: FundamentalValuationModel }) {
    return (
        <section aria-label="Valuation result" className="space-y-4 border-b pb-5">
            <div className="grid gap-4 @min-[36rem]:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
                <div className="min-w-0 rounded-md border bg-card p-4">
                    <h3 className="text-sm text-muted-foreground">Deterministic base per share</h3>
                    <p className="mt-2 text-xl font-semibold @min-[36rem]:text-2xl">
                        <ExactValue amount={report.base.perShare} onSelectEvidence={onSelectEvidence} />
                    </p>
                    <p className="mt-3 text-xs text-muted-foreground">As of {report.base.valuationDate}</p>
                </div>
                <div className="min-w-0 space-y-3 py-1">
                    <div>
                        <h3 className="text-sm text-muted-foreground">Total equity value</h3>
                        <p className="mt-1 text-base font-semibold">
                            <ExactValue amount={report.base.equity} onSelectEvidence={onSelectEvidence} />
                        </p>
                    </div>
                    <dl className="grid gap-2 text-xs">
                        <div className="flex flex-wrap items-center gap-2">
                            <dt className="text-muted-foreground">Calculation</dt>
                            <dd>
                                <Badge variant="outline">{report.base.status}</Badge>
                            </dd>
                        </div>
                        <div className="flex flex-wrap items-center gap-2">
                            <dt className="text-muted-foreground">Base quality</dt>
                            <dd>
                                <Badge variant={report.base.quality === 'verified' ? 'success' : 'warning'}>
                                    {report.base.quality}
                                </Badge>
                            </dd>
                        </div>
                        <div>
                            <dt className="text-muted-foreground">Model</dt>
                            <dd className="mt-0.5 break-words">
                                {report.modelId} · {report.modelVersion}
                            </dd>
                        </div>
                    </dl>
                </div>
            </div>
            {report.uncertainty.kind === 'provided' && report.uncertainty.quantiles.length > 0 && <dl aria-label="Model quantile summary" className="grid gap-3 @min-[26rem]:grid-cols-3">
                {report.uncertainty.quantiles.filter((item) => item.aliasOf === null).map((quantile) => <div key={quantile.label} className="min-w-0 border-l pl-3">
                    <dt className="text-xs text-muted-foreground">{quantile.label === 'p50' && report.uncertainty.kind === 'provided' && report.uncertainty.mode === 'sampled' ? 'Monte Carlo median · P50' : `Model quantile ${quantile.label.toUpperCase()}`}</dt>
                    <dd className="mt-1 text-sm"><InspectionValue evidence={quantile.evidence} onSelectEvidence={onSelectEvidence} /></dd>
                </div>)}
            </dl>}
            {(report.base.issueCodes.length > 0 || report.base.missingEvidence.length > 0) && (
                <Alert variant="warning">
                    <AlertTitle>Base calculation limitations</AlertTitle>
                    <AlertDescription>
                        {report.base.issueCodes.length > 0 && (
                            <span className="block break-words">{report.base.issueCodes.join(', ')}</span>
                        )}
                        {report.base.missingEvidence.length > 0 && (
                            <span className="block break-words">
                                Missing evidence · {report.base.missingEvidence.join(', ')}
                            </span>
                        )}
                    </AlertDescription>
                </Alert>
            )}
        </section>
    );
}
