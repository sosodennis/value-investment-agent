import { useMemo, useState } from 'react';
import { CircleAlert, Pencil, ShieldCheck } from 'lucide-react';
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
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

type Props = {
    preparation?: FundamentalAutomaticPreparation;
    pendingApproval?: Extract<WorkflowInteraction, { kind: 'valuation_approval' }> | null;
    onResumeInteraction?: (
        interaction: WorkflowInteraction,
        response: InteractionResponse
    ) => Promise<void>;
    isSubmitting?: boolean;
    onRecalculate?: (manualOverride: Record<string, unknown>) => void;
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
    const editableEvidence = effectivePreparation?.assumptions_evidence.filter(
        (item) => item.editable && item.method !== 'manual'
    ) ?? [];
    const [draftValues, setDraftValues] = useState<Record<string, string>>({});
    const [reason, setReason] = useState('');
    const [error, setError] = useState<string | null>(null);

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

                        {effectivePreparation.assumptions_evidence.length > 0 && (
                            <div className="grid gap-3">
                                <div>
                                    <h3 className="text-sm font-semibold">Assumptions and evidence</h3>
                                    <p className="text-xs text-muted-foreground">
                                        Values come from Fundamental Service. Overrides retain the automatic evidence and create a new input digest.
                                    </p>
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
