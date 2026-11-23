import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useArtifact } from '@/hooks/useArtifact';
import { parseFundamentalArtifact } from '@/types/agents/artifact-parsers';
import type { AgentStatus, ArtifactReference } from '@/types/agents';
import type { EvidenceSelection } from '../../workspace-evidence-inspector';
import { AgentLoadingState } from '../shared/AgentLoadingState';
import { ArtifactLoadError } from '../shared/ArtifactLoadError';
import { FinancialFactsTable } from './financial-facts-table';
import { projectFundamentalReport, type ExactAmount, type FundamentalReportModel } from './fundamental-report-model';

export type FundamentalAnalysisOutputProps = {
    reference: ArtifactReference | null;
    resolvedTicker: string | null | undefined;
    status: AgentStatus;
    threadId?: string | null;
    runId?: string | null;
    onSelectEvidence?: (item: EvidenceSelection) => void;
};

export function FundamentalAnalysisOutput({ reference, resolvedTicker, status, threadId, runId, onSelectEvidence }: FundamentalAnalysisOutputProps) {
    const artifact = useArtifact(reference, parseFundamentalArtifact, 'fundamental_output.artifact', 'financial_reports');
    if (artifact.isLoading) return <AgentLoadingState type="full" title="Loading Fundamental report" />;
    if (artifact.error && !artifact.data) return <ArtifactLoadError title="Fundamental report unavailable" error={artifact.error} retry={artifact.retry} isRetrying={artifact.isRetrying} retryable={artifact.retryable} />;
    const projection = artifact.data?.fundamental_service;
    if (!projection) {
        if (status === 'running' || status === 'attention') return <AgentLoadingState type="full" title="Processing financials…" />;
        return <Alert variant={status === 'error' ? 'destructive' : 'default'}><AlertTitle>{status === 'error' ? 'Financial analysis failed' : 'Fundamental report unavailable'}</AlertTitle><AlertDescription>This run has no canonical Fundamental Service report.</AlertDescription></Alert>;
    }
    const report = projectFundamentalReport({ artifact: projection, reference, threadId, ticker: artifact.data?.ticker ?? resolvedTicker ?? 'Company' });
    const previous = runId != null && report.identity.runId !== runId;
    return <div className="min-w-0 space-y-4">
        {previous && <Alert variant="warning"><AlertTitle>Previous result</AlertTitle><AlertDescription>This report belongs to run {report.identity.runId ?? 'unavailable'}. The current run has not supplied this result.</AlertDescription></Alert>}
        {artifact.error && <Alert variant="warning"><AlertTitle>Report refresh failed</AlertTitle><AlertDescription>The saved report is shown. {artifact.error instanceof Error ? artifact.error.message : 'Refresh unavailable.'}</AlertDescription></Alert>}
        <FundamentalReport report={report} onSelectEvidence={onSelectEvidence} />
    </div>;
}

function ExactValue({ amount }: { amount: ExactAmount | null }) {
    return amount ? <span className="break-all font-mono tabular-nums">{amount.raw} <span className="text-sm">{amount.currency}{amount.basis === 'per-share' ? ' / share' : ' total equity'}</span></span> : <span>Unavailable</span>;
}

function InspectionValue({ value, evidence, onSelectEvidence }: {
    value: string;
    evidence: EvidenceSelection;
    onSelectEvidence?: (item: EvidenceSelection) => void;
}) {
    return onSelectEvidence ? <button type="button" className="break-all rounded-sm text-left font-mono tabular-nums underline decoration-dashed underline-offset-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" onClick={() => onSelectEvidence(evidence)} aria-label={`Inspect ${evidence.title}`}>{value}</button> : <span className="break-all font-mono tabular-nums">{value}</span>;
}

export function FundamentalReport({ report, onSelectEvidence }: {
    report: FundamentalReportModel;
    onSelectEvidence?: (item: EvidenceSelection) => void;
}) {
    const preparation = report.kind === 'valuation' || report.kind === 'preparation-outcome' ? report.preparationSummary : null;
    return <article aria-label="Fundamental valuation report" className="min-w-0 space-y-5">
        <header className="space-y-2">
            <h2 className="text-xl font-semibold">{report.company}{report.shareClass ? ` · ${report.shareClass}` : ''}</h2>
            <p className="text-sm">Report quality <Badge variant={report.quality === 'verified' ? 'outline' : 'warning'}>{report.quality}</Badge></p>
            {report.issueCodes.length > 0 && <Alert variant="warning"><AlertTitle>Data and model limitations</AlertTitle><AlertDescription>{report.issueCodes.join(', ')}</AlertDescription></Alert>}
        </header>
        {report.kind === 'service-error' && <Alert variant="destructive"><AlertTitle>Automatic valuation degraded</AlertTitle><AlertDescription>{report.code} · {report.message}</AlertDescription></Alert>}
        {report.kind === 'preparation-outcome' && <Alert variant="warning"><AlertTitle>Preparation {report.outcome.replaceAll('_', ' ')}</AlertTitle><AlertDescription><span className="block">Calculation skipped.</span><span className="block">{report.reason ?? 'No additional reason was supplied.'}</span>{report.missingEvidence.length > 0 && <span className="block">Missing evidence · {report.missingEvidence.join(', ')}</span>}</AlertDescription></Alert>}
        {report.kind === 'facts-only' && <Alert><AlertTitle>Valuation not requested</AlertTitle><AlertDescription>Facts selected for {report.valuationDate}. No calculation was requested.</AlertDescription></Alert>}
        {report.kind === 'valuation' && <>
            <Card><CardHeader><CardTitle>Valuation result</CardTitle><p className="text-sm text-muted-foreground">{report.modelId} · {report.modelVersion} · as of {report.base.valuationDate}</p></CardHeader><CardContent className="space-y-3">
                <p>Calculation <Badge variant="outline">{report.base.status}</Badge> · Base quality {report.base.quality}</p>
                <dl className="grid gap-3"><div><dt>Deterministic base per share</dt><dd><ExactValue amount={report.base.perShare} /></dd></div><div><dt>Total equity value</dt><dd><ExactValue amount={report.base.equity} /></dd></div></dl>
                <p className="text-xs text-muted-foreground">Evaluated {report.base.evaluatedAt}</p>
                {report.base.issueCodes.length > 0 && <p className="text-sm text-warning">Base limitations · {report.base.issueCodes.join(', ')}</p>}
                {report.base.missingEvidence.length > 0 && <p className="text-sm">Missing evidence · {report.base.missingEvidence.join(', ')}</p>}
            </CardContent></Card>
            <section aria-label="Model uncertainty" className="space-y-3"><h3 className="font-semibold">Model uncertainty</h3>
                {report.uncertainty.kind === 'not-requested' ? <p>No uncertainty report was supplied.</p> : <>
                    <p>{report.uncertainty.mode === 'sampled' ? 'Monte Carlo sampling' : 'Scenario and sensitivity results · no Monte Carlo samples requested in this result'}</p>
                    <p>Uncertainty quality · {report.uncertainty.quality}</p>
                    <p className="text-sm text-muted-foreground">Quantiles describe the valuation model under sampled assumptions. They do not estimate future stock prices or investment confidence.</p>
                    {report.uncertainty.quantiles.length ? <dl className="grid gap-2">{report.uncertainty.quantiles.map((quantile) => <div key={quantile.label}><dt>Model quantile {quantile.label}</dt><dd><ExactValue amount={quantile.value} /></dd></div>)}</dl> : <p>No quantiles were supplied. The base calculation is shown independently.</p>}
                    <p>Samples requested {report.uncertainty.requestedSamples} · valid {report.uncertainty.validSamples} · invalid {report.uncertainty.invalidSamples}</p>
                    <p>Converged · {report.uncertainty.convergence.converged == null ? 'Unavailable' : String(report.uncertainty.convergence.converged)} · minimum valid samples {report.uncertainty.convergence.minimumValidSamples ?? 'Unavailable'} · invalid ratio {report.uncertainty.convergence.invalidRatio?.raw ?? 'Unavailable'}</p>
                    <p>Seed {report.uncertainty.seed ?? 'Unavailable'} · sampler {report.uncertainty.samplerVersion ?? 'Unavailable'} · invalid draw policy {report.uncertainty.invalidDrawPolicy ?? 'Unavailable'}</p>
                    {report.uncertainty.invalidReasons.length > 0 && <ul>{report.uncertainty.invalidReasons.map((reason) => <li key={reason.code}>{reason.code} · {reason.count}</li>)}</ul>}
                    {report.uncertainty.sensitivity.length > 0 && <div><h4 className="font-medium">Sensitivity results per share</h4><p className="text-sm text-muted-foreground">Input coordinates were not supplied in this result. Values are listed in service order.</p><dl>{report.uncertainty.sensitivity.map((row) => <div key={row.path}><dt>{row.path}</dt><dd className="break-all font-mono">{row.values.map((value) => value.raw).join(', ')} {report.currency}</dd></div>)}</dl></div>}
                    {report.uncertainty.dominantDrivers.length > 0 && <p>Dominant drivers · {report.uncertainty.dominantDrivers.join(', ')}</p>}
                    {report.uncertainty.scenarios.map((scenario, index) => <div key={scenario.binding.resultHash}><p>Service scenario {index + 1} · {scenario.status} · {scenario.quality}</p><ExactValue amount={scenario.perShare} /></div>)}
                </>}
            </section>
        </>}
        {preparation && <section aria-label="Assumptions" className="space-y-3"><h3 className="font-semibold">Assumptions</h3><p className="text-sm text-muted-foreground">Saved report assumptions are read-only.</p>
            {preparation.assumptions.length ? <dl className="grid gap-3">{preparation.assumptions.map((item) => <div key={item.path}><dt className="font-medium">{item.path}</dt><dd><InspectionValue value={item.value.raw} evidence={item.evidence} onSelectEvidence={onSelectEvidence} /><p className="text-sm text-muted-foreground">{item.method} · {item.formula}</p></dd></div>)}</dl> : <p>No assumption evidence was supplied.</p>}
            {preparation.historicalMetrics.length > 0 && <details><summary>Historical metrics used in preparation</summary><dl className="mt-2 space-y-2">{preparation.historicalMetrics.map((metric) => <div key={`${metric.id}:${metric.year}`}><dt>{metric.id} · {metric.year} · {metric.periodEnd}</dt><dd className="break-all font-mono">{metric.value.raw} {metric.unit}</dd><dd className="text-sm">{metric.formula}</dd></div>)}</dl></details>}
        </section>}
        {report.kind !== 'service-error' && <FinancialFactsTable facts={report.facts} onSelectEvidence={onSelectEvidence} />}
        <details><summary className="cursor-pointer font-semibold">Sources &amp; method</summary><div className="mt-3 space-y-3 text-sm">
            <dl className="space-y-2"><Metadata label="Thread" value={report.identity.threadId} /><Metadata label="Run" value={report.identity.runId} /><Metadata label="Artifact" value={report.identity.artifactId} /><Metadata label="Preparation digest" value={report.identity.preparationDigest} /></dl>
            {report.kind === 'valuation' && <>
                <dl className="space-y-2"><Metadata label="Snapshot" value={report.snapshotId} /><Metadata label="Snapshot digest" value={report.snapshotDigest} /><Metadata label="Data release digest" value={report.releaseDigest} /><Metadata label="Report input digest" value={report.reportBinding.inputDigest} /><Metadata label="Report result hash" value={report.reportBinding.resultHash} /><Metadata label="Base input digest" value={report.base.binding.inputDigest} /><Metadata label="Base result hash" value={report.base.binding.resultHash} /></dl>
                <h3 className="font-medium">Calculation nodes · {report.calculationVersion}</h3>
                {report.base.nodes.length ? <dl className="space-y-3">{report.base.nodes.map((node) => <div key={node.id}><dt>{node.id}</dt><dd><InspectionValue value={node.value?.raw ?? 'Unavailable'} evidence={node.evidence} onSelectEvidence={onSelectEvidence} /> {node.unit}</dd><dd>{node.formula}</dd><dd>Inputs · {node.inputs.join(', ') || 'None supplied'}</dd></div>)}</dl> : <p>No calculation nodes were supplied.</p>}
                <h3 className="font-medium">Service evidence references</h3>
                {[...report.base.evidenceReferences, ...(report.uncertainty.kind === 'provided' ? report.uncertainty.evidenceReferences : [])].map((item) => <p key={`${item.artifact_id}:${item.content_hash}`} className="break-all font-mono">{item.artifact_type} · {item.artifact_id} · {item.content_hash}</p>)}
            </>}
        </div></details>
    </article>;
}

function Metadata({ label, value }: { label: string; value: string | null }) {
    return <div><dt className="text-muted-foreground">{label}</dt><dd className="break-all font-mono">{value ?? 'Unavailable'}</dd></div>;
}
