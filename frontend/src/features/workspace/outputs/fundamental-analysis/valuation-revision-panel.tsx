import { useEffect, useId, useReducer, useRef, useState, type FormEvent } from 'react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { researchForwardEvidence, type ForwardEvidenceClaim } from './forward-evidence-api';
import {
    ratioToPercentText,
    TERMINAL_GROWTH_FIELD,
    type FundamentalRevision,
    type ValuationRevisionContext,
} from './valuation-revision';
import {
    applyValuationClaim,
    createValuationRevisionState,
    validateValuationRevisionDraft,
    valuationRevisionReducer,
} from './valuation-revision-state';
import { ValuationEvidenceReview } from './valuation-evidence-review';

export function ValuationRevisionPanel({
    context,
    isPending,
    onRecalculate,
}: {
    context: ValuationRevisionContext;
    isPending: boolean;
    onRecalculate: (revision: FundamentalRevision, sourceTicker: string) => Promise<void>;
}) {
    const [state, dispatch] = useReducer(valuationRevisionReducer, context, createValuationRevisionState);
    const [question, setQuestion] = useState(
        `What evidence supports the long-term terminal growth assumption for ${context.ticker}?`,
    );
    const researchOperation = useRef<AbortController | null>(null);
    const recalculationOperation = useRef<string | null>(null);
    const id = useId();
    const sourceKey = context.sourceKey;
    const recalculating = state.recalculation.kind === 'pending' || state.recalculation.kind === 'submitted';
    const disabled = isPending || recalculating;
    useEffect(
        () => () => {
            researchOperation.current?.abort();
            researchOperation.current = null;
            recalculationOperation.current = null;
        },
        [],
    );

    async function research() {
        if (disabled || researchOperation.current) return;
        const operation = new AbortController();
        researchOperation.current = operation;
        const operationId = crypto.randomUUID();
        dispatch({ type: 'research-started', sourceKey, operationId });
        try {
            if (question.trim().length < 8)
                throw new Error('Ask a research question with at least 8 characters.');
            const review = await researchForwardEvidence(
                {
                    opt_in: true,
                    ticker: context.ticker,
                    issuer_id: context.issuerId,
                    model_id: context.modelId,
                    assumption_path: TERMINAL_GROWTH_FIELD.path,
                    question: question.trim(),
                    valuation_timestamp: context.valuationTimestamp,
                    automatic_preparation_digest: context.source.preparation_digest,
                },
                { signal: operation.signal },
            );
            if (researchOperation.current !== operation || operation.signal.aborted) return;
            if (review.automatic_preparation_digest !== context.source.preparation_digest)
                throw new Error('The research response belongs to a different preparation.');
            dispatch({ type: 'research-ready', sourceKey, operationId, review });
        } catch (error) {
            if (researchOperation.current === operation && !operation.signal.aborted)
                dispatch({
                    type: 'research-failed',
                    sourceKey,
                    operationId,
                    message: error instanceof Error ? error.message : 'Research failed.',
                });
        } finally {
            if (researchOperation.current === operation) researchOperation.current = null;
        }
    }

    function apply(claim: ForwardEvidenceClaim) {
        if (disabled || state.research.kind !== 'ready') return;
        const applied = applyValuationClaim(context, state.research.review, claim);
        if (applied.kind === 'error')
            dispatch({ type: 'claim-rejected', sourceKey, message: applied.message });
        else
            dispatch({
                type: 'claim-applied',
                sourceKey,
                claimId: claim.claim_id,
                percentage: applied.percentage,
                evidence: applied.evidence,
            });
    }

    async function recalculate(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
        if (disabled || recalculationOperation.current) return;
        const checked = validateValuationRevisionDraft(context, state.draft);
        if (checked.kind === 'invalid') {
            dispatch({ type: 'draft-invalid', sourceKey, errors: checked.errors });
            return;
        }
        const operationId = crypto.randomUUID();
        recalculationOperation.current = operationId;
        researchOperation.current?.abort();
        researchOperation.current = null;
        dispatch({ type: 'recalculation-started', sourceKey, operationId });
        try {
            await onRecalculate(checked.revision, context.ticker);
            if (recalculationOperation.current === operationId)
                dispatch({ type: 'recalculation-submitted', sourceKey, operationId });
        } catch (error) {
            if (recalculationOperation.current === operationId)
                dispatch({
                    type: 'recalculation-failed',
                    sourceKey,
                    operationId,
                    message: error instanceof Error ? error.message : 'Recalculation failed.',
                });
        } finally {
            if (recalculationOperation.current === operationId) recalculationOperation.current = null;
        }
    }

    return (
        <div
            aria-label="Revise valuation"
            className="space-y-4 rounded-md border border-primary/30 bg-card p-3 @min-[36rem]:p-4"
        >
            <div>
                <h4 className="text-sm font-semibold">Revise one assumption</h4>
                <p className="mt-1 text-xs text-muted-foreground">
                    The saved report stays unchanged. Recalculate creates a new run from this exact source.
                </p>
            </div>
            <form onSubmit={(event) => void recalculate(event)} className="space-y-4">
                <Field
                    label={`${TERMINAL_GROWTH_FIELD.label} (${TERMINAL_GROWTH_FIELD.unit})`}
                    htmlFor={`${id}-value`}
                    description={`Saved value: ${ratioToPercentText(context.savedValue)}%. The service validates the allowed range and model constraints.`}
                    error={
                        state.fieldErrors.value && (
                            <span id={`${id}-value-error`}>{state.fieldErrors.value}</span>
                        )
                    }
                >
                    <Input
                        id={`${id}-value`}
                        inputMode="decimal"
                        autoComplete="off"
                        value={state.draft.percentage}
                        disabled={disabled}
                        aria-invalid={state.fieldErrors.value !== null}
                        aria-describedby={state.fieldErrors.value ? `${id}-value-error` : undefined}
                        onChange={(event) =>
                            dispatch({ type: 'value-edited', sourceKey, percentage: event.target.value })
                        }
                    />
                </Field>
                <Field
                    label="Reason for change"
                    htmlFor={`${id}-reason`}
                    error={
                        state.fieldErrors.reason && (
                            <span id={`${id}-reason-error`}>{state.fieldErrors.reason}</span>
                        )
                    }
                >
                    <Textarea
                        id={`${id}-reason`}
                        value={state.draft.reason}
                        disabled={disabled}
                        maxLength={2048}
                        aria-invalid={state.fieldErrors.reason !== null}
                        aria-describedby={state.fieldErrors.reason ? `${id}-reason-error` : undefined}
                        onChange={(event) =>
                            dispatch({ type: 'reason-edited', sourceKey, reason: event.target.value })
                        }
                    />
                </Field>
                {state.apply.kind === 'applied' && (
                    <p role="status" className="break-words text-xs text-muted-foreground">
                        Applied {state.apply.claimId} to the draft. Recalculate to run the valuation.
                    </p>
                )}
                {state.apply.kind === 'error' && (
                    <p role="alert" className="text-sm text-destructive">
                        {state.apply.message}
                    </p>
                )}
                {state.recalculation.kind === 'error' && (
                    <Alert variant="destructive" role="alert">
                        <AlertTitle>Recalculation failed</AlertTitle>
                        <AlertDescription>{state.recalculation.message}</AlertDescription>
                    </Alert>
                )}
                {recalculating && (
                    <p role="status" className="text-sm text-muted-foreground">
                        Starting a new valuation run. The saved result is shown until a new report is
                        available.
                    </p>
                )}
                <Button type="submit" disabled={disabled}>
                    {recalculating ? 'Recalculating…' : 'Recalculate'}
                </Button>
            </form>
            {context.canApplyResearch ? <details className="border-t pt-3 text-sm">
                <summary className="cursor-pointer font-medium">
                    Research external evidence (optional)
                </summary>
                <div className="mt-3 space-y-3">
                    <p className="text-xs text-muted-foreground">
                        Research sends this question to the configured search and model providers. It does not
                        change the draft. Review the citation and license before applying a claim.
                    </p>
                    <Field label="Research question" htmlFor={`${id}-question`}>
                        <Textarea
                            id={`${id}-question`}
                            value={question}
                            maxLength={512}
                            disabled={disabled || state.research.kind === 'pending'}
                            onChange={(event) => setQuestion(event.target.value)}
                        />
                    </Field>
                    <Button
                        type="button"
                        variant="outline"
                        disabled={disabled || state.research.kind === 'pending'}
                        onClick={() => void research()}
                    >
                        {state.research.kind === 'pending' ? 'Researching…' : 'Research external evidence'}
                    </Button>
                    {state.research.kind === 'error' && (
                        <p role="alert" className="text-sm text-destructive">
                            {state.research.message}
                        </p>
                    )}
                    {state.research.kind === 'ready' && (
                        <ValuationEvidenceReview
                            context={context}
                            review={state.research.review}
                            disabled={disabled}
                            onApply={apply}
                        />
                    )}
                </div>
            </details> : <p className="text-xs text-muted-foreground">Research cannot be applied to this report. You can enter a value and reason above.</p>}
        </div>
    );
}
