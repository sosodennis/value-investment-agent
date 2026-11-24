import { AnnualStatementsReader } from './annual-statements-reader';
import { AnnualStatementsTable } from './annual-statements-table';
import { projectAnnualStatements } from './annual-statements-model';
import { useCallback, useEffect, useId, useMemo, useState, type ReactNode } from 'react';
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
    fundamentalReportSourceKey,
    buildFundamentalEvidenceInventory,
    projectFundamentalReport,
    type FundamentalEvidenceInventory,
    type FundamentalReportModel,
} from './fundamental-report-model';
import { ValuationAssumptionsSection, ValuationKeyAssumptions } from './valuation-assumptions-section';
import { ValuationForecast, ValuationHistory } from './valuation-series';
import { ExactValue } from './report-value';
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
    onReportReady?: (report: FundamentalReportModel) => void;
    onEvidenceInventory?: (inventory: FundamentalEvidenceInventory) => void;
    revisionControl?: FundamentalRevisionControl;
};

export function FundamentalAnalysisOutput(props: FundamentalAnalysisOutputProps) {
    return <FundamentalOutputWithStatements key={props.threadId ?? 'unbound'} {...props} />;
}

function FundamentalOutputWithStatements(props: FundamentalAnalysisOutputProps) {
    const [valuationInventory, setValuationInventory] = useState<FundamentalEvidenceInventory | null>(null);
    const [statementItems, setStatementItems] = useState<EvidenceSelection[]>([]);
    const sourceKey = fundamentalReportSourceKey({ threadId: props.threadId, reference: props.reference });
    const reportStatementItems = useCallback((items: EvidenceSelection[]) => setStatementItems(items), []);
    const onInventory = props.onEvidenceInventory;
    useEffect(() => {
        onInventory?.({ sourceKey, items: [
            ...(valuationInventory?.sourceKey === sourceKey ? valuationInventory.items : []), ...statementItems,
        ] });
    }, [onInventory, sourceKey, statementItems, valuationInventory]);
    return <div className="min-w-0 space-y-5">
        <AnnualStatementsReader threadId={props.threadId ?? null} ticker={props.resolvedTicker} onSelectEvidence={props.onSelectEvidence} onEvidenceItems={reportStatementItems} />
        {(props.reference || props.status !== 'idle') && <FundamentalValuationOutput {...props} onEvidenceInventory={setValuationInventory} />}
    </div>;
}

function FundamentalValuationOutput({
    reference,
    resolvedTicker,
    status,
    threadId,
    runId,
    onSelectEvidence,
    onEvidenceInventory,
    onReportReady,
    revisionControl,
}: FundamentalAnalysisOutputProps) {
    const artifact = useArtifact(
        reference,
        parseFundamentalArtifact,
        'fundamental_output.artifact',
        'financial_reports',
    );
    const attempt = revisionControl?.kind === 'available' ? revisionControl.attempt : null;
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
    const annualReport = useMemo(() => artifact.data?.annual_statements ? projectAnnualStatements({
        response: artifact.data.annual_statements,
        reference, threadId,
        companyName: artifact.data.company_name, ticker: artifact.data.ticker,
    }) : null, [artifact.data, reference, threadId]);
    useEffect(() => { if (report) onReportReady?.(report); }, [onReportReady, report]);
    useEffect(() => {
        if (!onEvidenceInventory) return;
        const inventory = report ? buildFundamentalEvidenceInventory(report) : { sourceKey: fundamentalReportSourceKey({ threadId, reference }), items: [] };
        if (annualReport) inventory.items.push(...annualReport.evidence);
        if (attempt?.kind === 'accepted') inventory.items.push(...buildFundamentalEvidenceInventory(attempt.previousReport).items);
        onEvidenceInventory(inventory);
    }, [annualReport, attempt, onEvidenceInventory, reference, report, threadId]);
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
        if (annualReport) return <AnnualStatementsTable report={annualReport} onSelectEvidence={onSelectEvidence} />;
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
    const pendingSource = attempt && attempt.kind !== 'accepted' ? attempt.revision.source : null;
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
            revision.kind === 'available' && (currentSource || pendingThisSource) ? (
                <ValuationRevisionPanel
                    key={revision.context.sourceKey}
                    context={revision.context}
                    isPending={revisionControl.isPending}
                    readOnlyReason={!currentSource ? 'This retained source is read-only. The draft is preserved; start from an original current report to submit another revision.' : undefined}
                    failure={attempt?.kind === 'failed' ? { operationId: attempt.operationId, message: `${attempt.code} · ${attempt.message}` } : null}
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
            {attempt?.kind === 'accepted' && <RevisionComparison previous={attempt.previousReport} current={attempt.currentReport} onSelectEvidence={onSelectEvidence} />}
            {previous && (
                <Alert variant="warning">
                    <AlertTitle>Previous result</AlertTitle>
                    <AlertDescription>
                        This report belongs to run {report.identity.runId ?? 'unavailable'}. The current run
                        has not supplied this result. The saved valuation date is {report.kind === 'valuation' ? report.base.valuationDate : 'unavailable'}.
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
            {annualReport && <AnnualStatementsTable report={annualReport} onSelectEvidence={onSelectEvidence} />}
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

function RevisionComparison({ previous, current, onSelectEvidence }: { previous: Extract<FundamentalReportModel, { kind: 'valuation' }>; current: Extract<FundamentalReportModel, { kind: 'valuation' }>; onSelectEvidence?: (item: EvidenceSelection) => void }) {
    const median = (report: typeof current) => report.uncertainty.kind === 'provided' ? report.uncertainty.quantiles.find((item) => item.label === 'p50')?.value ?? null : null;
    return <section aria-label="Revision comparison" className="space-y-3 rounded-md border bg-muted/10 p-3">
        <h2 className="text-sm font-semibold">Recalculated result</h2>
        <p role="status" className="text-xs text-muted-foreground">A new report confirms the applied manual assumption. The previous result remains available for comparison and source inspection.</p>
        <div className="grid gap-3 @min-[36rem]:grid-cols-2">{[{ label: 'Previous result', report: previous }, { label: 'New result', report: current }].map(({ label, report }) => <div key={label} className="min-w-0">
            <h3 className="text-sm font-medium">{label}</h3>
            <p className="mt-1 text-xs text-muted-foreground">Evaluated · {report.base.evaluatedAt} · Quality · {report.quality}</p>
            <dl className="mt-2 space-y-2 text-sm"><div><dt className="text-xs text-muted-foreground">Deterministic base</dt><dd><ExactValue amount={report.base.perShare} onSelectEvidence={onSelectEvidence} /></dd></div>
            <div><dt className="text-xs text-muted-foreground">Monte Carlo median · P50</dt><dd><ExactValue amount={median(report)} onSelectEvidence={onSelectEvidence} /></dd></div></dl>
        </div>)}</div>
    </section>;
}
