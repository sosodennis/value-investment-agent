import { useMemo, useState } from 'react';
import { CircleAlert, ExternalLink, Pencil, Search, ShieldCheck } from 'lucide-react';
import type {
    FundamentalAssumptionEvidence,
    FundamentalAutomaticPreparation,
} from '@/types/agents/fundamental-service-facts';
import { parseFundamentalAutomaticPreparation } from '@/types/agents/fundamental-service-facts';
import type { InteractionResponse, WorkflowInteraction } from '@/features/workflow';
import { Alert, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Combobox } from '@/components/ui/combobox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import type {
    ForwardEvidenceClaim,
    ForwardEvidenceManualOverride,
    ForwardEvidenceReview,
} from './forward-evidence-api';

type Props = {
    preparation?: FundamentalAutomaticPreparation;
    pendingApproval?: Extract<WorkflowInteraction, { kind: 'valuation_approval' }> | null;
    onResumeInteraction?: (
        interaction: WorkflowInteraction,
        response: InteractionResponse
    ) => Promise<void>;
    isSubmitting?: boolean;
    onRecalculate?: (manualOverride: Record<string, unknown>) => void;
    ticker?: string | null;
    forwardEvidence?: ForwardEvidenceReview | null;
    isResearchingForwardEvidence?: boolean;
    researchError?: string | null;
    onResearchForwardEvidence?: (question: string, assumptionPath: string) => Promise<void>;
    onApplyForwardEvidence?: (override: ForwardEvidenceManualOverride) => void;
};

const QUALITY_LABELS: Record<FundamentalAutomaticPreparation['quality_status'], string> = {
    verified: 'Verified',
    provisional: 'Provisional',
    degraded: 'Degraded',
    unsupported: 'Unsupported',
    abstain: 'Abstained',
    error: 'Error',
};

const formatValue = (value: string | number): string => String(value);

const formatMethod = (method: FundamentalAssumptionEvidence['method']): string => {
    switch (method) {
        case 'approved_source':
            return 'Approved source';
        case 'approved_policy':
            return 'Policy resolved';
        case 'derived':
            return 'Formula derived';
        case 'manual':
            return 'Manual override';
        default:
            return method;
    }
};

export function FundamentalReviewPanel({
    preparation,
    pendingApproval = null,
    onResumeInteraction,
    isSubmitting = false,
    onRecalculate,
    ticker = null,
    forwardEvidence = null,
    isResearchingForwardEvidence = false,
    researchError = null,
    onResearchForwardEvidence,
    onApplyForwardEvidence,
}: Props) {
    const preparationFromApproval = useMemo(() => {
        const candidate = pendingApproval?.request.parameters.automatic_preparation;
        if (candidate === undefined) return undefined;
        try {
            return parseFundamentalAutomaticPreparation(candidate);
        } catch {
            return undefined;
        }
    }, [pendingApproval]);
    const effectivePreparation = preparation ?? preparationFromApproval;
    const editableEvidence = useMemo(
        () => effectivePreparation?.assumptions_evidence.filter(
            (item) => item.editable && item.method !== 'manual'
        ) ?? [],
        [effectivePreparation]
    );
    const [draftValues, setDraftValues] = useState<Record<string, string>>({});
    const [reason, setReason] = useState('');
    const [error, setError] = useState<string | null>(null);
    const [researchQuestion, setResearchQuestion] = useState('');
    const [researchPath, setResearchPath] = useState('');

    const selectedResearchPath = editableEvidence.some((item) => item.path === researchPath)
        ? researchPath
        : editableEvidence[0]?.path ?? '';

    const respond = (decision: 'approve' | 'reject') => {
        if (!pendingApproval || !onResumeInteraction) return;
        void onResumeInteraction(pendingApproval, {
            type: 'valuation_approval',
            contract_version: pendingApproval.request.contract_version,
            decision,
        });
    };

    const submitOverride = (evidence: FundamentalAssumptionEvidence) => {
        if (!effectivePreparation || !onRecalculate) return;
        const value = (draftValues[evidence.path] ?? formatValue(evidence.value)).trim();
        if (!value) {
            setError(`Enter a value for ${evidence.path}.`);
            return;
        }
        if (!reason.trim()) {
            setError('Give a reason for the manual override before recalculating.');
            return;
        }
        setError(null);
        onRecalculate({
            contract_version: 'fundamental.v1',
            preparation: effectivePreparation,
            path: evidence.path,
            value,
            provenance: {
                author: 'workspace-user',
                modified_at: new Date().toISOString(),
                reason: reason.trim(),
                automatic_preparation_digest: effectivePreparation.preparation_digest,
            },
        });
    };

    const applyForwardEvidence = (claim: ForwardEvidenceClaim) => {
        if (!effectivePreparation || !claim.assumption_path || !onApplyForwardEvidence) return;
        const evidence = effectivePreparation.assumptions_evidence.find(
            (item) => item.path === claim.assumption_path && item.editable && item.method !== 'manual'
        );
        if (!evidence || claim.status !== 'accepted' || !claim.source.license_reference) return;
        onApplyForwardEvidence({
            contract_version: 'fundamental.v1',
            preparation: effectivePreparation,
            path: claim.assumption_path,
            value: claim.value,
            provenance: {
                author: 'workspace-user',
                modified_at: new Date().toISOString(),
                reason: `Applied cited forward evidence ${claim.claim_id}.`,
                automatic_preparation_digest: effectivePreparation.preparation_digest,
                forward_reference: {
                    claim_id: claim.claim_id,
                    source_url: claim.source.source_url,
                    source_content_hash: claim.source.content_hash,
                    citation: claim.source.retained_passage,
                    license_reference: claim.source.license_reference,
                },
            },
        });
    };

    return (
        <section className="grid gap-4" aria-label="Fundamental preparation review">
            {pendingApproval && (
                <Alert variant="warning" role="alert">
                    <CircleAlert className="size-4" />
                    <AlertTitle>{pendingApproval.request.title}</AlertTitle>
                    <div className="grid gap-3 text-sm opacity-90">
                        <p>{pendingApproval.request.description}</p>
                        <p className="font-medium text-foreground">
                            {pendingApproval.request.ticker} · {pendingApproval.request.model_type}
                        </p>
                        {pendingApproval.request.audit_messages.length > 0 && (
                            <ul className="grid gap-1 text-sm">
                                {pendingApproval.request.audit_messages.map((message, index) => (
                                    <li key={`${index}:${message}`}>{message}</li>
                                ))}
                            </ul>
                        )}
                        <div className="flex flex-wrap gap-2">
                            <Button
                                type="button"
                                disabled={isSubmitting || !onResumeInteraction}
                                onClick={() => respond('approve')}
                            >
                                Confirm and calculate
                            </Button>
                            <Button
                                type="button"
                                variant="outline"
                                disabled={isSubmitting || !onResumeInteraction}
                                onClick={() => respond('reject')}
                            >
                                Reject calculation
                            </Button>
                        </div>
                    </div>
                </Alert>
            )}

            {effectivePreparation && (
                <Card>
                    <CardHeader className="gap-2">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                            <CardTitle className="text-base">Automatic valuation preparation</CardTitle>
                            <Badge variant={effectivePreparation.quality_status === 'verified' ? 'success' : 'warning'}>
                                {QUALITY_LABELS[effectivePreparation.quality_status]}
                            </Badge>
                        </div>
                        <p className="text-sm text-muted-foreground">
                            {effectivePreparation.model_id} · {effectivePreparation.model_version} · policy {effectivePreparation.policy_version}
                        </p>
                    </CardHeader>
                    <CardContent className="grid gap-4">
                        <dl className="grid gap-2 text-xs sm:grid-cols-2">
                            <div>
                                <dt className="text-muted-foreground">Preparation digest</dt>
                                <dd className="break-all font-mono">{effectivePreparation.preparation_digest}</dd>
                            </div>
                            <div>
                                <dt className="text-muted-foreground">Evidence profile</dt>
                                <dd className="break-all font-mono">{effectivePreparation.profile_id}</dd>
                            </div>
                            <div>
                                <dt className="text-muted-foreground">Policy</dt>
                                <dd className="break-words">{effectivePreparation.policy_id}</dd>
                            </div>
                            <div>
                                <dt className="text-muted-foreground">Status</dt>
                                <dd>{effectivePreparation.status}</dd>
                            </div>
                        </dl>

                        {effectivePreparation.issue_codes.length > 0 && (
                            <Alert variant="warning">
                                <ShieldCheck className="size-4" />
                                <AlertTitle>Quality notes</AlertTitle>
                                <div className="text-sm opacity-90">
                                    <ul className="grid gap-1">
                                        {effectivePreparation.issue_codes.map((code) => <li key={code}>{code}</li>)}
                                    </ul>
                                </div>
                            </Alert>
                        )}

                        {effectivePreparation.missing_evidence.length > 0 && (
                            <p className="text-sm text-warning">
                                Missing evidence: {effectivePreparation.missing_evidence.join(', ')}
                            </p>
                        )}

                        {onResearchForwardEvidence && effectivePreparation.status === 'prepared' && ticker && (
                            <div className="grid gap-3 border-t pt-4" aria-label="Optional forward evidence">
                                <div className="flex flex-wrap items-center justify-between gap-2">
                                    <div>
                                        <h3 className="text-sm font-semibold">Advanced forward evidence</h3>
                                        <p className="text-xs text-muted-foreground">
                                            Optional forward-looking external evidence. It never changes this valuation until you apply a cited claim.
                                        </p>
                                    </div>
                                    <Badge variant="outline">Opt in</Badge>
                                </div>
                                <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
                                    <div className="grid gap-2">
                                        <Label htmlFor="forward-evidence-question">Evidence question</Label>
                                        <Input
                                            id="forward-evidence-question"
                                            value={researchQuestion}
                                            disabled={isResearchingForwardEvidence || isSubmitting}
                                            onChange={(event) => setResearchQuestion(event.target.value)}
                                            placeholder="e.g. What is the next annual revenue growth guidance?"
                                        />
                                    </div>
                                    <Button
                                        type="button"
                                        variant="outline"
                                        disabled={isResearchingForwardEvidence || isSubmitting || selectedResearchPath.length === 0 || researchQuestion.trim().length < 8}
                                        onClick={() => void onResearchForwardEvidence(researchQuestion.trim(), selectedResearchPath)}
                                    >
                                        <Search className={isResearchingForwardEvidence ? 'animate-pulse' : undefined} />
                                        {isResearchingForwardEvidence ? 'Researching…' : 'Research evidence'}
                                    </Button>
                                </div>
                                {editableEvidence.length > 0 && (
                                    <div className="grid gap-2">
                                        <Label htmlFor="forward-evidence-path">Assumption to research</Label>
                                        <Combobox
                                            ariaLabel="Assumption to research"
                                            value={selectedResearchPath}
                                            options={editableEvidence.map((item) => ({
                                                value: item.path,
                                                label: item.path,
                                            }))}
                                            onValueChange={setResearchPath}
                                            placeholder="Select an assumption"
                                            searchPlaceholder="Search assumptions"
                                            disabled={isResearchingForwardEvidence || isSubmitting}
                                        />
                                    </div>
                                )}
                                {researchError && <p role="alert" className="text-sm text-destructive">{researchError}</p>}
                                {forwardEvidence && <ForwardEvidenceResult review={forwardEvidence} onApply={applyForwardEvidence} />}
                            </div>
                        )}

                        {effectivePreparation.assumptions_evidence.length > 0 && (
                            <div className="grid gap-3">
                                <div>
                                    <h3 className="text-sm font-semibold">Assumptions and evidence</h3>
                                    <p className="text-xs text-muted-foreground">
                                        Values come from Fundamental Service. Overrides retain the automatic evidence and create a new input digest.
                                    </p>
                                    {effectivePreparation.assumptions_evidence_truncated !== undefined && (
                                        <p className="mt-1 text-xs text-muted-foreground">
                                            {effectivePreparation.assumptions_evidence_truncated} additional evidence entries are omitted from this compact review.
                                        </p>
                                    )}
                                </div>
                                <div className="grid gap-3">
                                    {effectivePreparation.assumptions_evidence.map((evidence) => {
                                        const currentValue = draftValues[evidence.path] ?? formatValue(evidence.value);
                                        return (
                                            <div key={`${evidence.path}:${evidence.method}`} className="grid gap-2 border p-3">
                                                <div className="flex flex-wrap items-start justify-between gap-2">
                                                    <div className="min-w-0">
                                                        <Label htmlFor={`assumption-${evidence.path}`}>{evidence.path}</Label>
                                                        <p className="mt-1 break-words text-xs text-muted-foreground">
                                                            {formatMethod(evidence.method)} · {evidence.formula}
                                                        </p>
                                                    </div>
                                                    <Badge variant={evidence.method === 'manual' ? 'warning' : 'outline'}>
                                                        {formatMethod(evidence.method)}
                                                    </Badge>
                                                </div>
                                                <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
                                                    <Input
                                                        id={`assumption-${evidence.path}`}
                                                        value={currentValue}
                                                        disabled={!evidence.editable || evidence.method === 'manual' || isSubmitting}
                                                        onChange={(event) => setDraftValues((current) => ({
                                                            ...current,
                                                            [evidence.path]: event.target.value,
                                                        }))}
                                                    />
                                                    <Button
                                                        type="button"
                                                        variant="outline"
                                                        disabled={!evidence.editable || evidence.method === 'manual' || isSubmitting || !onRecalculate}
                                                        onClick={() => submitOverride(evidence)}
                                                    >
                                                        <Pencil /> Recalculate
                                                    </Button>
                                                </div>
                                                <p className="break-words text-xs text-muted-foreground">
                                                    As of {evidence.as_of} · policy {evidence.policy_version}
                                                    {evidence.fact_ids.length > 0 ? ` · facts ${evidence.fact_ids.join(', ')}` : ''}
                                                    {evidence.source_refs.length > 0 ? ` · sources ${evidence.source_refs.join(', ')}` : ''}
                                                </p>
                                                {evidence.manual_provenance?.forward_reference && (
                                                    <p className="break-words text-xs text-primary">
                                                        Applied reference {evidence.manual_provenance.forward_reference.claim_id} · {evidence.manual_provenance.forward_reference.source_url}
                                                    </p>
                                                )}
                                            </div>
                                        );
                                    })}
                                </div>
                                <div className="grid gap-2">
                                    <Label htmlFor="manual-override-reason">Override reason</Label>
                                    <Input
                                        id="manual-override-reason"
                                        value={reason}
                                        disabled={isSubmitting || editableEvidence.length === 0}
                                        onChange={(event) => setReason(event.target.value)}
                                        placeholder="Explain why this assumption should change"
                                    />
                                </div>
                                {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
                            </div>
                        )}
                    </CardContent>
                </Card>
            )}
        </section>
    );
}

function ForwardEvidenceResult({
    review,
    onApply,
}: {
    review: ForwardEvidenceReview;
    onApply: (claim: ForwardEvidenceClaim) => void;
}) {
    return (
        <div className="grid gap-3 rounded-none border bg-muted/20 p-3" aria-label="Forward evidence result">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                    <p className="text-sm font-semibold">{review.label}</p>
                    <p className="text-xs text-muted-foreground">
                        {review.status === 'prepared' ? 'Claims are separately reviewed below.' : 'No claim is eligible to change the baseline.'}
                    </p>
                </div>
                <Badge variant={review.status === 'prepared' ? 'success' : 'warning'}>{review.status}</Badge>
            </div>
            {review.issue_codes.length > 0 && (
                <p className="text-xs text-warning">Review notes: {review.issue_codes.join(', ')}</p>
            )}
            <p className="text-xs text-muted-foreground">
                Usage: {review.usage.search_queries} search query · {review.usage.search_results} results · {review.usage.llm_calls} LLM call · {review.usage.elapsed_ms} ms
            </p>
            {review.claims.length === 0 ? (
                <p className="text-sm text-muted-foreground">No supported numeric evidence was returned.</p>
            ) : (
                <div className="grid gap-3">
                    {review.claims.map((claim) => (
                        <div key={claim.claim_id} className="grid gap-2 border bg-background p-3">
                            <div className="flex flex-wrap items-start justify-between gap-2">
                                <div className="min-w-0">
                                    <p className="text-sm font-medium">
                                        {claim.metric} · {claim.fiscal_period} · {claim.value} {claim.unit}
                                    </p>
                                    <p className="text-xs text-muted-foreground">
                                        {claim.status === 'accepted' ? 'Eligible reference' : `Excluded: ${claim.issue_codes.join(', ') || claim.exclusion_reasons.join(', ')}`}
                                    </p>
                                </div>
                                <Badge variant={claim.status === 'accepted' ? 'success' : 'destructive'}>{claim.status}</Badge>
                            </div>
                            <blockquote className="border-l-2 pl-3 text-xs text-muted-foreground">“{claim.source.retained_passage}”</blockquote>
                            <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                                <a
                                    className="inline-flex min-w-0 items-center gap-1 text-primary underline underline-offset-2"
                                    href={claim.source.source_url}
                                    target="_blank"
                                    rel="noreferrer"
                                >
                                    <span className="truncate">{claim.source.publisher}</span>
                                    <ExternalLink className="size-3 shrink-0" />
                                </a>
                                {claim.status === 'accepted' && claim.assumption_path && (
                                    <Button type="button" size="sm" variant="outline" onClick={() => onApply(claim)}>
                                        Apply to valuation
                                    </Button>
                                )}
                            </div>
                            <p className="break-all font-mono text-[11px] text-muted-foreground">
                                {claim.source.content_hash} · {claim.source.license_status} · retrieved {claim.source.retrieved_at}
                            </p>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}
