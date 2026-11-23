import type { ForwardEvidenceClaim, ForwardEvidenceReview } from './forward-evidence-api';
import {
    percentTextToRatio,
    ratioToPercentText,
    TERMINAL_GROWTH_FIELD,
    type FundamentalRevision,
    type ValuationRevisionContext,
} from './valuation-revision';

type ForwardReference = NonNullable<FundamentalRevision['forward_reference']>;
type Draft = { percentage: string; reason: string; forwardReference: ForwardReference | null };
type FieldErrors = { value: string | null; reason: string | null };
type ResearchState =
    | { kind: 'idle' }
    | { kind: 'pending'; operationId: string }
    | { kind: 'ready'; review: ForwardEvidenceReview }
    | { kind: 'error'; message: string };
type RecalculationState =
    | { kind: 'idle' }
    | { kind: 'pending'; operationId: string }
    | { kind: 'submitted' }
    | { kind: 'error'; message: string };
export type ValuationRevisionState = {
    sourceKey: string;
    draft: Draft;
    fieldErrors: FieldErrors;
    research: ResearchState;
    apply: { kind: 'idle' } | { kind: 'applied'; claimId: string } | { kind: 'error'; message: string };
    recalculation: RecalculationState;
};
type RevisionAction = { sourceKey: string } & (
    | { type: 'value-edited'; percentage: string }
    | { type: 'reason-edited'; reason: string }
    | { type: 'research-started'; operationId: string }
    | { type: 'research-ready'; operationId: string; review: ForwardEvidenceReview }
    | { type: 'research-failed'; operationId: string; message: string }
    | { type: 'claim-applied'; claimId: string; percentage: string; forwardReference: ForwardReference }
    | { type: 'claim-rejected'; message: string }
    | { type: 'draft-invalid'; errors: FieldErrors }
    | { type: 'recalculation-started'; operationId: string }
    | { type: 'recalculation-submitted'; operationId: string }
    | { type: 'recalculation-failed'; operationId: string; message: string }
);

export function createValuationRevisionState(context: ValuationRevisionContext): ValuationRevisionState {
    return {
        sourceKey: context.sourceKey,
        draft: { percentage: ratioToPercentText(context.savedValue), reason: '', forwardReference: null },
        fieldErrors: { value: null, reason: null },
        research: { kind: 'idle' },
        apply: { kind: 'idle' },
        recalculation: { kind: 'idle' },
    };
}

export function valuationRevisionReducer(
    state: ValuationRevisionState,
    action: RevisionAction,
): ValuationRevisionState {
    if (state.sourceKey !== action.sourceKey) return state;
    switch (action.type) {
        case 'value-edited':
            return {
                ...state,
                draft: { ...state.draft, percentage: action.percentage, forwardReference: null },
                fieldErrors: { ...state.fieldErrors, value: null },
                apply: { kind: 'idle' },
                recalculation: { kind: 'idle' },
            };
        case 'reason-edited':
            return {
                ...state,
                draft: { ...state.draft, reason: action.reason },
                fieldErrors: { ...state.fieldErrors, reason: null },
                recalculation: { kind: 'idle' },
            };
        case 'research-started':
            return {
                ...state,
                research: { kind: 'pending', operationId: action.operationId },
                apply: { kind: 'idle' },
            };
        case 'research-ready':
            return state.research.kind === 'pending' && state.research.operationId === action.operationId
                ? { ...state, research: { kind: 'ready', review: action.review } }
                : state;
        case 'research-failed':
            return state.research.kind === 'pending' && state.research.operationId === action.operationId
                ? { ...state, research: { kind: 'error', message: action.message } }
                : state;
        case 'claim-applied':
            return {
                ...state,
                draft: {
                    percentage: action.percentage,
                    reason: state.draft.reason || `Applied external evidence ${action.claimId}.`,
                    forwardReference: action.forwardReference,
                },
                fieldErrors: { value: null, reason: null },
                apply: { kind: 'applied', claimId: action.claimId },
                recalculation: { kind: 'idle' },
            };
        case 'claim-rejected':
            return { ...state, apply: { kind: 'error', message: action.message } };
        case 'draft-invalid':
            return { ...state, fieldErrors: action.errors };
        case 'recalculation-started':
            return {
                ...state,
                fieldErrors: { value: null, reason: null },
                research: state.research.kind === 'pending' ? { kind: 'idle' } : state.research,
                recalculation: { kind: 'pending', operationId: action.operationId },
            };
        case 'recalculation-submitted':
            return state.recalculation.kind === 'pending' &&
                state.recalculation.operationId === action.operationId
                ? { ...state, recalculation: { kind: 'submitted' } }
                : state;
        case 'recalculation-failed':
            return state.recalculation.kind === 'pending' &&
                state.recalculation.operationId === action.operationId
                ? { ...state, recalculation: { kind: 'error', message: action.message } }
                : state;
        default: {
            const exhaustive: never = action;
            return exhaustive;
        }
    }
}

export function validateValuationRevisionDraft(
    context: ValuationRevisionContext,
    draft: Draft,
): { kind: 'valid'; revision: FundamentalRevision } | { kind: 'invalid'; errors: FieldErrors } {
    let value: string | null = null;
    let valueError: string | null = null;
    try {
        value = percentTextToRatio(draft.percentage);
    } catch {
        valueError = 'Enter a finite decimal percentage.';
    }
    const reason = draft.reason.trim();
    if (value === null || !reason)
        return {
            kind: 'invalid',
            errors: {
                value: valueError,
                reason: reason ? null : 'Explain why you are changing this assumption.',
            },
        };
    return {
        kind: 'valid',
        revision: {
            source: context.source,
            path: TERMINAL_GROWTH_FIELD.path,
            value,
            reason,
            ...(draft.forwardReference ? { forward_reference: draft.forwardReference } : {}),
        },
    };
}

export function applyValuationClaim(
    context: ValuationRevisionContext,
    review: ForwardEvidenceReview,
    claim: ForwardEvidenceClaim,
):
    | { kind: 'applied'; percentage: string; forwardReference: ForwardReference }
    | { kind: 'error'; message: string } {
    if (
        review.automatic_preparation_digest !== context.source.preparation_digest ||
        claim.issuer_id !== context.issuerId ||
        claim.ticker !== context.ticker ||
        claim.model_id !== context.modelId
    )
        return { kind: 'error', message: 'This evidence belongs to a different valuation source.' };
    if (
        claim.status !== 'accepted' ||
        !review.accepted_claim_ids.includes(claim.claim_id) ||
        claim.assumption_path !== TERMINAL_GROWTH_FIELD.path ||
        claim.unit !== 'ratio'
    )
        return { kind: 'error', message: 'This claim is not accepted for the terminal growth assumption.' };
    if (
        claim.source.license_status !== 'approved' ||
        !claim.source.license_reference?.trim() ||
        !claim.source.retained_passage.trim()
    )
        return {
            kind: 'error',
            message: 'Applying a claim requires an approved license and a retained citation.',
        };
    try {
        return {
            kind: 'applied',
            percentage: ratioToPercentText(claim.value),
            forwardReference: {
                claim_id: claim.claim_id,
                source_url: claim.source.source_url,
                source_content_hash: claim.source.content_hash,
                citation: claim.source.retained_passage,
                license_reference: claim.source.license_reference,
            },
        };
    } catch {
        return { kind: 'error', message: 'The claim does not contain a finite decimal ratio.' };
    }
}
