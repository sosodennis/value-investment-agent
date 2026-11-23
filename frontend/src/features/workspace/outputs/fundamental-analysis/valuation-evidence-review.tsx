import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import type { ForwardEvidenceClaim, ForwardEvidenceReview } from './forward-evidence-api';
import type { ValuationRevisionContext } from './valuation-revision';
import { applyValuationClaim } from './valuation-revision-state';

export function ValuationEvidenceReview({
    context,
    review,
    disabled,
    onApply,
}: {
    context: ValuationRevisionContext;
    review: ForwardEvidenceReview;
    disabled: boolean;
    onApply: (claim: ForwardEvidenceClaim) => void;
}) {
    return (
        <section aria-label="External evidence review" className="space-y-3">
            <p className="text-xs text-muted-foreground">
                {review.label} · {review.status}
            </p>
            {review.issue_codes.length > 0 && (
                <p className="break-words text-xs text-warning">{review.issue_codes.join(', ')}</p>
            )}
            {review.claims.length === 0 && (
                <p className="text-sm text-muted-foreground">No claims were returned.</p>
            )}
            {review.claims.map((claim) => {
                const applicable = applyValuationClaim(context, review, claim);
                return (
                    <article key={claim.claim_id} className="min-w-0 space-y-2 rounded-md border p-3">
                        <div className="flex flex-wrap items-center gap-2">
                            <h5 className="text-sm font-medium">{claim.source.publisher}</h5>
                            <Badge variant={claim.status === 'accepted' ? 'outline' : 'warning'}>
                                {claim.status}
                            </Badge>
                        </div>
                        <p className="break-all font-mono text-sm tabular-nums">
                            {claim.value} {claim.unit}
                        </p>
                        <p className="break-words text-xs text-muted-foreground">
                            {claim.assumption_path ?? claim.metric} · {claim.fiscal_period} ·{' '}
                            {claim.period_end}
                        </p>
                        <blockquote className="border-l-2 pl-3 text-xs leading-5">
                            {claim.source.retained_passage}
                        </blockquote>
                        <a
                            href={claim.source.source_url}
                            target="_blank"
                            rel="noreferrer"
                            className="block break-all text-xs text-primary underline underline-offset-4"
                        >
                            {claim.source.source_url}
                        </a>
                        <p className="break-words text-xs text-muted-foreground">
                            License · {claim.source.license_status} ·{' '}
                            {claim.source.license_reference ?? 'No license reference supplied'}
                        </p>
                        {claim.exclusion_reasons.length > 0 && (
                            <p className="break-words text-xs text-warning">
                                {claim.exclusion_reasons.join(', ')}
                            </p>
                        )}
                        {applicable.kind === 'applied' ? (
                            <Button
                                type="button"
                                variant="outline"
                                size="sm"
                                disabled={disabled}
                                onClick={() => onApply(claim)}
                            >
                                Apply {claim.claim_id} to draft
                            </Button>
                        ) : (
                            <p className="text-xs text-muted-foreground">{applicable.message}</p>
                        )}
                    </article>
                );
            })}
        </section>
    );
}
