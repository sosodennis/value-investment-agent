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

An optional `AccountingComponentV1.discontinued_depreciation_exclusion` retains
an original dimensional D&A observation as the negative component of a duration
`depreciation_and_amortization` rule. The rule permits exactly one positive
consolidated D&A base and one excluded D&A observation. Its exact dimensions
must identify discontinued income, with at most one business-segment axis;
an ordinary `AllOther` segment observation alone is insufficient. Other roles,
unrelated dimensions, overlapping components and a negative resulting amount
remain unsupported. A component cannot carry both swap and D&A scopes.

The same original report must supply the aligned issuer, duration and unit,
plus the exact original segment-reporting passage that identifies the target
year and discontinued D&A classification. The passage may describe an earlier
comparative period; it does not replace the duration on the numeric observation.
The evidence retains all original dimensions, classification text, source
digests and reported decimals. The derived candidate does not invent a new
decimal precision or substitute a more precise observation with another scope.
A rounded discontinued amount remains rounded. Independent semantic review
must establish coverage, inclusion in the consolidated base and continuing
business scope before approving any mapping. The representation supplies no
absence assertion, trusted release or verified forecast.

### Registered NEWMARKET continuing D&A policy

`registered_depreciation.py` proposes the bounded policy
`newmarket-original-continuing-depreciation-v1`, under automatic policy
`source-bound-us-gaap-v6`. This version also carries forward #408's historical
total `SalesRevenueNet` support and cross-concept conflict refusals, together
with #376's direct consolidated current-assets/current-liabilities totals and
the current security-bound stock-compensation policy. It registers CIK `0001282637` originals
`0001282637-15-000004`, `0001282637-16-000028` and
`0001282637-17-000005` by both retained source SHA-256 and the complete parsed
fact multiset digest. The registry pins classifications, never numeric amounts.
An unregistered original or changed observation, precision, dimension or passage
abstains. Existing source bytes, taxonomy, integrity, availability and optional
security-identity checks still apply before approval.

The original segment note says that segment PPE depreciation and intangible
amortization enter operating profit; its table reconciles petroleum additives,
All Other and corporate amounts to total D&A. The footnote explicitly assigns
Foundry Park I D&A in 2012/2013 to discontinued income. The 2014 original
contains both years; the 2015 original contains 2013. The exact consolidated
total minus the exact discontinued observation is a separate computed mapping.
It never substitutes the All Other observation: that category also contains TEL
and contract manufacturing. The later columns in those registered tables and
the 2016 original's 2014–2016 table supply the direct continuing periods. This
classification is specific to the complete pinned originals, not an inference
from a missing modern concept or a general aggregate-D&A alias.

Direct and computed mappings have disjoint periods. The direct proposal uses
`us-gaap:DepreciationDepletionAndAmortization`; the adjusted proposal uses
`registered:ContinuingDepreciationAndAmortization` and produces
`computed:depreciation_and_amortization`, anchored to that original QName.
Source text, numeric observations, dimensions and reported decimals survive
reconstruction. A derived amount using the reported USD 5 million exclusion
retains `decimals=-6`; it is a reported-value estimate, not unrounded truth.
Release canaries reproduce the mapping policy and arithmetic. The future
original remains label-only at the fixed 2016 origin.

Source review inventory: external report
`448d5edbfc814aba8aa7475b51c4b18d86c6dedd5920ca84d7c87c60d491a223`;
earlier rounded-D&A relation implementation
`ecb09fa8fec47dffc762ce51fb4dd951468c17dd` (PR #400). This increment preserves
that checkpoint and integrates its exclusion guard with the current lease and
dated-disclosure guards. Independent PR review remains pending. Machine
certificates demonstrate execution of the proposed versioned policy; they do
not establish complete working-capital/capex coverage, a full issuer release,
forecast accuracy or a supported history threshold.


### Registered continuing cash-capex scope

Under automatic policy `source-bound-us-gaap-v6`, cash purchases of PPE require
an original-specific continuing-operations classification in
`registered_capital_expenditure.py`. A consolidated annual QName establishes
cash-purchase shape; it does not establish that discontinued operations are
excluded. This closes the automatic-mapping gap recorded in #415.

The three NEWMARKET originals above are pinned by raw source hash and complete
parsed fact multiset. The original discontinued-operations note states that
cash flows combine continuing and discontinued activity. The disposal occurred
in 2013. Only the post-disposal periods (2014 in the 2014 original; 2014/2015 in
the 2015 original; 2014/2015/2016 in the label original) are classified here.
2012/2013 aggregate purchases retain
`MAPPING_CAPEX_CONTINUING_SCOPE_UNRESOLVED` and cannot enter the approved
observation scope. No amount is replaced, and no precise continuing capex is
inferred from the equality of segment asset additions and cash purchases.

Unregistered originals abstain with `MAPPING_CAPEX_SCOPE_UNREVIEWED`; a changed
fact set abstains with `MAPPING_CAPEX_SOURCE_MISMATCH`. Existing issuer, unit,
annual period, precision, consolidation, original integrity and availability
checks still apply. Other issuers need their own supported scope classification;
a source-shaped tag or missing discontinued tag cannot inherit this one.
The existing signed mapping replay reproduces the selection after restart.
This guards the release boundary; NEWMARKET 2013 continuing capex and the first
complete empirical forecast/label/error case remain unresolved.

### Registered NVE operating D&A and cash capex

Automatic policy `source-bound-us-gaap-v7` adds only CIK `0000724910` originals
[`0001376474-23-000283`](https://www.sec.gov/Archives/edgar/data/724910/000137647423000283/nvec-20230331.htm)
and
[`0001376474-24-000214`](https://www.sec.gov/Archives/edgar/data/724910/000137647424000214/nvec-20240331.htm).
Both selectors bind the raw source hash and complete parsed fact multiset.
This is a module edit to the existing accounting policy; provider acquisition,
storage, financial formulas and public contracts retain their existing owners.

The fixed-assets policy explicitly covers machinery/equipment depreciation and
leasehold-improvement amortization. The complete statements and operating note
classify those fixed assets within NVE's single operating business. The registered
operating D&A source is `us-gaap:Depreciation`, rather than a general alias for
the cash-flow `DepreciationDepletionAndAmortization` aggregate:

| Original | Annual periods | Operating fixed-asset D&A | Cash-flow D&A aggregate |
| --- | --- | --- | --- |
| 2023 | FY2022 / FY2023 | USD214,877 / USD196,738 | USD424,981 / USD257,606 |
| 2024 | FY2023 / FY2024 | USD196,738 / USD308,147 | USD196,738 / USD308,147 |

The 2024 cash-flow statement separately reports securities premium/discount
amortization, including USD60,868 in FY2023. The earlier original included that
amount in its FY2023 aggregate. This explains the comparative classification
difference; the evaluator uses the contemporaneous fixed-asset note directly.
It never derives an earlier amount from a future filing or infers an unreported
FY2022 component from the aggregate difference. Every original aggregate remains
in the report and the ordered rejection evidence. Matching numbers in a later
column do not make the concepts interchangeable. An aggregate proposal for
these registered originals abstains with `MAPPING_DA_CONCEPT_SCOPE_UNREVIEWED`.

The same complete originals classify the cash-flow PPE purchases as operating
fixed-asset investment: FY2022/FY2023 in the 2023 original and FY2023/FY2024 in
the 2024 original. This scope is specific to these original statements, fixed
assets policy and business disclosure; a single-segment tag or lack of a
discontinued-operations tag cannot authorize another original. Amounts, units,
periods and original reported precision are always read from source facts.

Automatic batch proposals now receive the original so they can choose its
registered direct concept. The existing signed mapping replay rechecks the same
registration. Unregistered or changed sources still abstain. These partial
classifications assert no missing balance, claim/award absence, complete release,
market policy, numerical valuation or history sufficiency. NVE remains an
additional service case; it does not replace a fixed replay-cohort member.

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
