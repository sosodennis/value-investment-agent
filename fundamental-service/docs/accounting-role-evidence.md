# Accounting role evidence

`CanonicalMappingV1.accounting_rules` binds an accounting classification to one
issuer/security, original accession, raw/parser input hashes, complete parsed
fact digest and policy version. `CanonicalFactV1.accounting_evidence` retains the
rule, its exact parsed observations and resulting value. Direct observed facts
and mappings omit these fields and preserve their existing canonical bytes.

New mappings use a supported deterministic automatic policy for semantic
approval. Unsupported classifications retain abstentions; this document does
not create a pending human approval step. Retained independent review records
remain an optional supported evidence path. Both paths must establish the full
role's meaning, currency, period, scope, completeness and lack of overlap;
structural source membership alone cannot approve a mapping.

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
survives in the observations; no unrounded amount is inferred. A supported policy
or retained independent review must establish the location member's meaning,
matching coverage of the noncurrent component, completeness and remaining
operating scope. This representation alone establishes a partial accounting
relation, not a complete operating role. Unset scope is omitted from existing
component bytes.

The lease and swap scopes are mutually exclusive on one component. Separate
lease exclusions, swap exclusions and dated disclosure components may share a
rule when each passes its existing source, period and scope checks. Supporting
classification passages remain in the source set and do not enter arithmetic
or component-overlap checks. Unknown reported precision remains unknown.

An optional `AccountingComponentV1.finance_lease_expense_location` supports
two exact statement-location classifications: `FinanceLeaseRightOfUseAssetAmortization`
at `OperatingExpenseMember`, and `FinanceLeaseInterestExpense` at
`InterestExpenseMember`, all in the `us-gaap` namespace. Each observation must
have only `IncomeStatementLocationAxis` and retain its original segmented scope.
Range, business, geographic and security dimensions are rejected.

A duration `finance_lease_cost` rule adds exactly those two observations. An
`operating_lease_cost` rule subtracts them from one consolidated `us-gaap:LeaseCost`
total. Components must share issuer, period and monetary unit; observations and
result must be nonnegative. Missing pairs, overlaps, other bases and conflicting
scope flags fail. The result retains the coarsest reported precision, or unknown
precision when any source has unknown precision. The same evaluator supports
issuer-only normalization and security-bound normalization. Unset fields preserve
existing canonical bytes. A supported policy or retained independent review must
establish that the original total and finance components provide complete,
nonoverlapping coverage for the requested role. This representation does not
approve that mapping.

A `disclosed` duration transcribes one finite decimal literal from an exact
nonnumeric parsed fact. `DisclosedAmountV1` retains Unicode code-point offsets
for the exact quote, amount token, unit quote and scale token, plus reported
precision, covered classes and the proposed complete-role scope. Supported
scales are units, thousands, millions and billions. Transcription requires the
same consolidated issuer and duration as the rule; comparative periods,
dimensional disclosures and partial-role amounts remain unsupported. Reported
precision survives candidate selection and canonical fact decoding. Existing
rules omit the unset transcription field and keep their canonical bytes.

The unscaled `$` token is also valid when it is the exact unit and scale marker
for a USD integer. Automatic policy `source-bound-us-gaap-v3` admits only the
bounded annual total stock-compensation sentence documented in the operations
runbook. It builds the existing issuer-bound `disclosed` rule, or a security-bound
rule when the optional input identity passes the existing exact original DEI
validator. The release canary reproduces the identity check, sentence selection
and amount. Source reconstruction still rejects an issuer-only rule used as
security evidence, and rejects a different security. No human reviewer is impersonated.
Other accounting/absence classifications still need a supported policy decision
or retained authentic review. This rule authorizes annual expense, not awards.

A derived instant may combine numeric components with a
`DatedDisclosureComponentV1`. This explicitly typed component transcribes one
partial-role amount from an original annual duration passage, using the same
amount/unit/scale/precision spans. It additionally retains exact quote-relative
month/day and year tokens, including separately listed comparative years, bound
to the target instant. That instant must fall within the annual source period
or on its opening comparative date (start minus one day); the annual source
period itself cannot be future evidence. Dimensional, foreign-issuer, quarterly,
undated and mismatched-date passages fail. Components cannot repeat source facts
or declared covered classes. Numeric observations still use the canonical XBRL
precision selector; the sum retains the coarsest known component precision, or
unknown precision when a numeric component has no reported precision. The full
narrative remains in canonical evidence and survives persistence/restore checks.

`complete_component=true` declares completeness only for the cited component;
it cannot claim `complete_role`. Token membership validates transcription and
date spelling, while a supported policy or retained independent review must
establish that the particular amount belongs to that date, currency and operating
class, and that the proposed components cover the role without overlap. A
comparative "respectively" passage requires that semantic decision; position
alone cannot approve it.

Source membership and deterministic scaling establish transcription only. The
supported policy or retained independent review must establish currency, period,
scope, completeness and overlap. For example, a rounded RSU-only cost cannot
automatically supply total stock-based compensation. A provisional transcription
stays provisional; it grants no release, caller approval, absence assertion or
numerical valuation.

A `confirmed_absent` period supplies zero only with exact cited original
nonnumeric disclosure for the same period. An exact quote establishes source
membership, not its financial meaning. A supported policy or retained independent
review must establish that the disclosure proves absence for this role, class and scope.
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
