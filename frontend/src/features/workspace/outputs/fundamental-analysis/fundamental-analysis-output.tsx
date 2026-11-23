import { useEffect, useId, useMemo, type ReactNode } from 'react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { useArtifact } from '@/hooks/useArtifact';
import { parseFundamentalArtifact } from '@/types/agents/artifact-parsers';
import type { AgentStatus, ArtifactReference } from '@/types/agents';
import type { EvidenceSelection } from '../../workspace-evidence-inspector';
import { ArtifactLoadError } from '../shared/ArtifactLoadError';
import { FinancialFactsTable } from './financial-facts-table';
import { FundamentalReportLoading } from './fundamental-report-loading';
import { FundamentalReportSources } from './fundamental-report-sources';
import {
    buildFundamentalEvidenceInventory,
    projectFundamentalReport,
    type FundamentalEvidenceInventory,
    type FundamentalReportModel,
} from './fundamental-report-model';
import { ValuationAssumptionsSection, ValuationKeyAssumptions } from './valuation-assumptions-section';
import { ValuationForecast, ValuationHistory } from './valuation-series';
import { ValuationSummary } from './valuation-summary';
import { ValuationUncertainty } from './valuation-uncertainty';
import { valuationRevisionAvailability, type FundamentalRevisionControl } from './valuation-revision';
import { ValuationRevisionPanel } from './valuation-revision-panel';

export type FundamentalAnalysisOutputProps = {
    reference: ArtifactReference | null;
    resolvedTicker: string | null | undefined;
    status: AgentStatus;
    threadId?: string | null;
    runId?: string | null;
    onSelectEvidence?: (item: EvidenceSelection) => void;
    onEvidenceInventory?: (inventory: FundamentalEvidenceInventory) => void;
    revisionControl?: FundamentalRevisionControl;
};

export function FundamentalAnalysisOutput({
    reference,
    resolvedTicker,
    status,
    threadId,
    runId,
    onSelectEvidence,
    onEvidenceInventory,
    revisionControl,
}: FundamentalAnalysisOutputProps) {
    const artifact = useArtifact(
        reference,
        parseFundamentalArtifact,
        'fundamental_output.artifact',
        'financial_reports',
    );
    const artifactId = reference?.artifact_id ?? null;
    const artifactUrl = reference?.download_url ?? null;
    const report = useMemo(
        () =>
            artifact.data?.fundamental_service
                ? projectFundamentalReport({
                      artifact: artifact.data.fundamental_service,
                      reference:
                          artifactId && artifactUrl
                              ? { artifact_id: artifactId, download_url: artifactUrl }
                              : null,
                      threadId,
                      ticker: artifact.data.ticker ?? resolvedTicker ?? 'Company',
                  })
                : null,
        [artifact.data, artifactId, artifactUrl, resolvedTicker, threadId],
    );
    useEffect(() => {
        if (report && onEvidenceInventory) onEvidenceInventory(buildFundamentalEvidenceInventory(report));
    }, [onEvidenceInventory, report]);
    if (artifact.isLoading) return <FundamentalReportLoading title="Loading Fundamental report" />;
    if (artifact.error && !artifact.data)
        return (
            <ArtifactLoadError
                title="Fundamental report unavailable"
                error={artifact.error}
                retry={artifact.retry}
                isRetrying={artifact.isRetrying}
                retryable={artifact.retryable}
            />
        );
    if (!report) {
        if (status === 'running' || status === 'attention')
            return <FundamentalReportLoading title="Processing financials…" />;
        return (
            <Alert variant={status === 'error' ? 'destructive' : 'default'}>
                <AlertTitle>
                    {status === 'error' ? 'Financial analysis failed' : 'Fundamental report unavailable'}
                </AlertTitle>
                <AlertDescription>This run has no canonical Fundamental Service report.</AlertDescription>
            </Alert>
        );
    }
    const pendingSource = revisionControl?.kind === 'available' ? revisionControl.pendingSource : null;
    const pendingThisSource =
        pendingSource?.thread_id === report.identity.threadId &&
        pendingSource?.run_id === report.identity.runId &&
        pendingSource?.artifact_id === report.identity.artifactId &&
        pendingSource?.preparation_digest === report.identity.preparationDigest;
    const previous = (runId != null && report.identity.runId !== runId) || pendingThisSource;
    const revision = valuationRevisionAvailability(report);
    const currentSource = report.identity.threadId === threadId && report.identity.runId === runId;
    const revisionPanel =
        revisionControl?.kind === 'read-only' ? (
            <p className="text-xs text-muted-foreground">{revisionControl.reason}</p>
        ) : revisionControl?.kind === 'available' ? (
            revision.kind === 'available' && currentSource ? (
                <ValuationRevisionPanel
                    key={revision.context.sourceKey}
                    context={revision.context}
                    isPending={revisionControl.isPending}
                    onRecalculate={revisionControl.onRecalculate}
                />
            ) : (
                <p className="text-xs text-muted-foreground">
                    {currentSource && revision.kind === 'read-only'
                        ? revision.reason
                        : 'Previous reports are read-only.'}
                </p>
            )
        ) : undefined;
    return (
        <div className="min-w-0 space-y-4">
            {previous && (
                <Alert variant="warning">
                    <AlertTitle>Previous result</AlertTitle>
                    <AlertDescription>
                        This report belongs to run {report.identity.runId ?? 'unavailable'}. The current run
                        has not supplied this result.
                    </AlertDescription>
                </Alert>
            )}
            {artifact.error && (
                <Alert variant="warning">
                    <AlertTitle>Report refresh failed</AlertTitle>
                    <AlertDescription>
                        The saved report is shown.{' '}
                        {artifact.error instanceof Error ? artifact.error.message : 'Refresh unavailable.'}
                    </AlertDescription>
                </Alert>
            )}
            <FundamentalReport
                report={report}
                onSelectEvidence={onSelectEvidence}
                revisionPanel={revisionPanel}
            />
        </div>
    );
}

export function FundamentalReport({
    report,
    onSelectEvidence,
    revisionPanel,
}: {
    report: FundamentalReportModel;
    onSelectEvidence?: (item: EvidenceSelection) => void;
    revisionPanel?: ReactNode;
}) {
    const sectionId = useId();
    const preparation =
        report.kind === 'valuation' || report.kind === 'preparation-outcome'
            ? report.preparationSummary
            : null;
    return (
        <article aria-label="Fundamental valuation report" className="@container min-w-0 space-y-5">
            <header className="flex flex-wrap items-start justify-between gap-3 border-b pb-4">
                <div className="min-w-0">
                    <p className="text-xs text-muted-foreground">Fundamental analysis</p>
                    <h2 className="mt-1 break-words text-lg font-semibold">{report.company}</h2>
                    <p className="mt-1 text-sm text-muted-foreground">{report.ticker} · {report.shareClass ?? 'Share class unavailable'} · {report.currency ?? 'Currency unavailable'}</p>
                    {report.kind === 'valuation' && <p className="mt-1 text-xs text-muted-foreground">Valuation date · {report.base.valuationDate}</p>}
                </div>
                <div className="space-y-1 text-right">
                    <p className="text-xs text-muted-foreground">Report quality</p>
                    <Badge variant={report.quality === 'verified' ? 'success' : 'warning'}>
                        {report.quality}
                    </Badge>
                </div>
            </header>
            <nav aria-label="Report sections" className="flex flex-wrap gap-x-4 gap-y-2 text-sm">
                {report.kind === 'valuation' && <a className="text-primary underline-offset-4 hover:underline" href={`#${sectionId}-valuation`}>Valuation</a>}
                {report.kind === 'valuation' && <a className="text-primary underline-offset-4 hover:underline" href={`#${sectionId}-forecast`}>Forecast</a>}
                {report.kind !== 'service-error' && <a className="text-primary underline-offset-4 hover:underline" href={`#${sectionId}-history`}>History</a>}
                {preparation && <a className="text-primary underline-offset-4 hover:underline" href={`#${sectionId}-assumptions`}>Assumptions</a>}
                {report.kind !== 'service-error' && <a className="text-primary underline-offset-4 hover:underline" href={`#${sectionId}-facts`}>Financial data</a>}
                <a className="text-primary underline-offset-4 hover:underline" href={`#${sectionId}-sources`}>Sources &amp; method</a>
            </nav>
            {report.kind === 'service-error' && (
                <Alert variant="destructive">
                    <AlertTitle>Automatic valuation degraded</AlertTitle>
                    <AlertDescription>
                        {report.code} · {report.message}
                    </AlertDescription>
                </Alert>
            )}
            {report.kind === 'preparation-outcome' && (
                <Alert variant="warning">
                    <AlertTitle>Preparation {report.outcome.replaceAll('_', ' ')}</AlertTitle>
                    <AlertDescription>
                        <span className="block">Calculation skipped.</span>
                        <span className="mt-1 block">
                            {report.reason ?? 'No additional reason was supplied.'}
                        </span>
                        {report.missingEvidence.length > 0 && (
                            <span className="mt-1 block break-words">
                                Missing evidence · {report.missingEvidence.join(', ')}
                            </span>
                        )}
                    </AlertDescription>
                </Alert>
            )}
            {report.kind === 'facts-only' && (
                <Alert>
                    <AlertTitle>Valuation not requested</AlertTitle>
                    <AlertDescription>
                        Facts selected for {report.valuationDate}. No calculation was requested.
                    </AlertDescription>
                </Alert>
            )}
            {report.kind === 'valuation' && (
                <div id={`${sectionId}-valuation`} tabIndex={-1} className="scroll-mt-4 space-y-5">
                    <ValuationSummary report={report} onSelectEvidence={onSelectEvidence} />
                    <ValuationKeyAssumptions report={report} onSelectEvidence={onSelectEvidence} />
                    <ReportLimitations report={report} compact />
                    <ValuationUncertainty report={report} onSelectEvidence={onSelectEvidence} />
                </div>
            )}
            {report.kind === 'valuation' && <div id={`${sectionId}-forecast`} tabIndex={-1} className="scroll-mt-4"><ValuationForecast report={report} onSelectEvidence={onSelectEvidence} /></div>}
            {report.kind !== 'service-error' && <div id={`${sectionId}-history`} tabIndex={-1} className="scroll-mt-4"><ValuationHistory report={report} onSelectEvidence={onSelectEvidence} /></div>}
            {report.kind !== 'valuation' && <ReportLimitations report={report} />}
            {preparation && (
                <div id={`${sectionId}-assumptions`} tabIndex={-1} className="scroll-mt-4">
                    <ValuationAssumptionsSection
                        preparation={preparation}
                        revisionPanel={revisionPanel}
                        onSelectEvidence={onSelectEvidence}
                    />
                </div>
            )}
            {report.kind === 'valuation' && <ReportLimitations report={report} />}
            {report.kind !== 'service-error' && (
                <div id={`${sectionId}-facts`} tabIndex={-1} className="scroll-mt-4">
                    <FinancialFactsTable facts={report.facts} onSelectEvidence={onSelectEvidence} />
                </div>
            )}
            <div id={`${sectionId}-sources`} tabIndex={-1} className="scroll-mt-4">
                <FundamentalReportSources report={report} onSelectEvidence={onSelectEvidence} />
            </div>
        </article>
    );
}

function ReportLimitations({ report, compact = false }: { report: FundamentalReportModel; compact?: boolean }) {
    const preparation = report.kind === 'valuation' || report.kind === 'preparation-outcome' ? report.preparationSummary : null;
    const codes = [...new Set([...report.issueCodes, ...(preparation?.issueCodes ?? [])])];
    const missing = preparation?.missingEvidence ?? [];
    const capital = preparation?.capitalCompleteness;
    const incompleteCapital = capital?.kind === 'provided' && (capital.completeClaims !== true || capital.completeAwards !== true);
    if (codes.length === 0 && missing.length === 0 && !incompleteCapital) return null;
    if (compact) return <Alert variant="warning">
        <AlertTitle>Interpretation limits</AlertTitle>
        <AlertDescription className="space-y-1">
            {incompleteCapital && <p>Incomplete capital claims and award inventory. Capital values are conditional hypotheses.</p>}
            {codes.includes('CONDITIONAL_FORWARD_REINVESTMENT_HYPOTHESES') && <p>Forward reinvestment uses conditional hypotheses.</p>}
            {codes.some((code) => code.startsWith('HISTORY_')) && <p>Historical coverage is partial or not validated.</p>}
            <p>{codes.length} recorded limitations · {missing.length} missing inputs. Full details remain visible below.</p>
        </AlertDescription>
    </Alert>;
    return <Alert variant="warning">
        <AlertTitle>Data and model limitations</AlertTitle>
        <AlertDescription className="space-y-2 [overflow-wrap:anywhere]">
            {incompleteCapital && <p>Capital claims or award inventory are incomplete. Capital inputs are conditional hypotheses; a complete capital bridge is unavailable.</p>}
            {codes.length > 0 && <p>{codes.join(', ')}</p>}
            {missing.length > 0 && <p>Missing evidence · {missing.join(', ')}</p>}
            {incompleteCapital && capital.unknowns.length > 0 && <p>Unknown capital data · {capital.unknowns.join(', ')}</p>}
        </AlertDescription>
    </Alert>;
}
