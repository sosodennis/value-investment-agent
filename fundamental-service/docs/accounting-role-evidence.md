# Accounting role evidence

`CanonicalMappingV1.accounting_rules` binds an accounting classification to one
issuer/security, original accession, raw/parser input hashes, complete parsed
fact digest and policy version. `CanonicalFactV1.accounting_evidence` retains the
rule, its exact parsed observations and resulting value. Direct observed facts
and mappings omit these fields and preserve their existing canonical bytes.

A `derived` period adds or subtracts at least two distinct source observations.
Every component must match the same consolidated issuer, period and unit.
Repeated observations, repeated concepts, conflicting observations, nonfinite
values and foreign/future evidence fail. Classification runs under Decimal
precision 34 with half-even rounding. It performs accounting normalization;
forecast, tax, WACC, dilution and valuation formulas remain with the existing
Fundamental composer/calculator.

An optional `AccountingComponentV1.accrued_interest_swap_exclusion` can retain
an original dimensional interest-swap liability as a negative component of an
instant `accrued_operating_liabilities` rule. Its exact canonical dimension
tuple must contain balance-sheet location and interest-swap risk, with at most
one additional derivative-by-nature axis. Business, geographic and security
segments remain unsupported. The original fact stays dimensional and segmented
inside the evidence; it is never relabeled as a consolidated observation.

This exclusion requires a positive consolidated accrued-liability base and a
positive consolidated noncurrent derivative component from the same issuer,
instant, unit and original report. The exact original derivative classification
passage must include the applicable year and the accrued/noncurrent locations.
The evaluator permits one paired exclusion, rejects overlapping concepts, and
requires the resulting current portion to fit the nonnegative accrued balance.
All numeric and passage digests join the retained source set. Original precision
survives in the observations; no unrounded amount is inferred. Independent
semantic review must establish the location member's meaning, matching coverage
of the noncurrent component, completeness and remaining operating scope. This
representation alone establishes a partial accounting relation, not a complete
operating role. Unset scope is omitted from existing component bytes.

A `disclosed` duration transcribes one finite decimal literal from an exact
nonnumeric parsed fact. `DisclosedAmountV1` retains Unicode code-point offsets
for the exact quote, amount token, unit quote and scale token, plus reported
precision, covered classes and the proposed complete-role scope. Supported
scales are units, thousands, millions and billions. Transcription requires the
same consolidated issuer and duration as the rule; comparative periods,
dimensional disclosures and partial-role amounts remain unsupported. Reported
precision survives candidate selection and canonical fact decoding. Existing
rules omit the unset transcription field and keep their canonical bytes.

Source membership and deterministic scaling establish transcription only. The
independent mapping review must establish currency, period, scope, completeness
and overlap. For example, a rounded RSU-only cost cannot automatically supply
total stock-based compensation. A provisional transcription stays provisional;
it grants no release, caller approval, absence assertion or numerical valuation.

A `confirmed_absent` period supplies zero only with exact cited original
nonnumeric disclosure for the same period. An exact quote establishes source
membership, not its financial meaning. The mapping's independent semantic review
must establish that the disclosure proves absence for this role, class and scope.
Missing tags, silence, unquantified immateriality or generated signatures cannot
establish absence. `unknown` and `unsupported` produce no numeric candidate;
ingestion retains their period-specific reasons and missing evidence.

The ingestion boundary matches the full report, source, issuer and original
accession before evaluation. Computed facts use `computed:<role>` concepts and
retain original QNames/context IDs in their source observations. Canonical decode
rechecks values and identity/period/source correspondence. Release canary,
valuation serving and backup verification compare each computed role with its
mapping and independently validated original integrity evidence. Restoring a
computed fact also requires its retained mapping and original snapshot.

These rules do not approve a mapping, waive EFM/DQC, activate a release, or grant
caller approval. Existing trusted reviews cover the entire mapping digest,
including its accounting rules. Numerical valuation still requires the existing
#352 preparation and caller approval. `supported_history_threshold` remains null.

The Agent's fact projection preserves the JSON evidence as service-owned data;
it evaluates no accounting or valuation rules. No Agent/UI workflow changes are
part of this contract addition.
