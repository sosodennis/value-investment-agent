# Conditional bounds for a disclosed option pool

`option_pool_research.research_option_pool_bounds` quantifies what a disclosed
option count and average exercise price can establish when individual strikes
are unavailable. It is a pure Fundamental Service research method. The formal
composer and release canary continue to refuse unresolved aggregate strikes.
It supplies no valuation, security identity, complete inventory, release or
caller approval, and cannot establish a history threshold.

The request retains the complete `OriginalIssuerEvidenceV1` and the exact parsed
quantity and average-price fact digests. The method supports only the standard
US GAAP outstanding-option quantity and weighted-average exercise-price concepts
from one issuer, original, currency, namespace and consolidated instant. It
refuses dimensional/class mixtures, conflicting observations, unavailable
originals, wrong periods/units, negative/nonfinite values and quantities whose
whole-share count is not established. Identical repeat observations are not
summed. The output preserves selected observations and source/parser/accession
identities, including refused inputs through their request digest.

Every result is conditional on explicitly declared conventional options for
one underlying share each, nonnegative strikes and nonnegative compensation
allocation. This instrument assumption requires its rationale. There is no
inference about conversion ratios or cash-settled/exotic awards. Every scenario
price is hypothetical: it is neither a quote nor evidence of source permission.
An average-price reporting-error allowance is explicit and requires its
rationale; it must cover at least the declared XBRL rounding precision. An INF
precision attribute does not establish that an issuer's printed average has no
economic rounding error. The researcher must record the assumed allowance.

For N options and price P, the existing treasury-stock expression is
`D = sum(max(0, n_i - (n_i*k_i + c_i)/P))`.
For nonnegative strikes and compensation it follows that `0 <= D <= N`.
If an explicit assumption caps total pool compensation at C and the average
strike at K, the stronger lower bound is `max(0, N - (N*K + C)/P)`.
This follows from `sum(max(0, x_i)) >= max(0, sum(x_i))`.
The method uses the reported average plus its assumed error as K. It rounds
proceeds upward and the lower share bound downward in an isolated 50-digit
Decimal context, so numerical rounding does not narrow the envelope.
The upper bound N is conservative and need not be attainable. This is a
mathematical conditional envelope, with no probabilities or confidence level.

A finite compensation cap is an assumption with mandatory rationale. Source
transcription alone cannot prove that a compensation disclosure covers the same
pool. If no cap is supplied, compensation remains unknown and the lower bound
is zero. The report never creates a zero compensation fact. Missing other
awards, preferred shares, convertible instruments and share classes remain
unresolved. A small bound for this pool cannot establish that total issuer
dilution or senior claims are immaterial.

Requests sort distinct scenario IDs. Reports have canonical input/output
digests and a fixed policy/numerical version, with `complete_inventory=false`
and `supported_history_threshold=null`. Existing immutable artifact storage can
publish requests and reports using their digests; the method performs no I/O.
Original evidence must already have passed its source-integrity boundary;
retained parsed membership is not an independent reparse of the filing bytes or
accounting approval. The exact registered composer/model versions remain
unchanged. Behavioral tests compare bounds with the shared official
per-instrument dilution function, retain refusals, and check outward rounding,
source/period/scope conflicts and caller Decimal isolation.
