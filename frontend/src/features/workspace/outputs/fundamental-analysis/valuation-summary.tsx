import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import type { FundamentalValuationModel } from './fundamental-report-model';
import { ExactValue } from './report-value';

export function ValuationSummary({ report }: { report: FundamentalValuationModel }) {
    return (
        <section aria-label="Valuation result" className="space-y-4 border-b pb-5">
            <div className="grid gap-4 @min-[36rem]:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
                <div className="min-w-0 rounded-md border bg-card p-4">
                    <h3 className="text-sm text-muted-foreground">Deterministic base per share</h3>
                    <p className="mt-2 text-xl font-semibold @min-[36rem]:text-2xl">
                        <ExactValue amount={report.base.perShare} />
                    </p>
                    <p className="mt-3 text-xs text-muted-foreground">As of {report.base.valuationDate}</p>
                </div>
                <div className="min-w-0 space-y-3 py-1">
                    <div>
                        <h3 className="text-sm text-muted-foreground">Total equity value</h3>
                        <p className="mt-1 text-base font-semibold">
                            <ExactValue amount={report.base.equity} />
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
