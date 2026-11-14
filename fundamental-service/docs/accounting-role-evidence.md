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

Automatic policy `source-bound-us-gaap-v15` changes the identity used by the
five registered selectors (D&A, capex, investment assets, liability residuals
and noncontrolling equity). They require the registered CIK/accession,
integrity-validated parser-input SHA-256 and complete fact multiset digest.
Both the source's parser-input hash and the report's source-content hash must
match that registered parser input. This supersedes the raw-hash registration
described in the earlier policy checkpoints below; those checkpoints remain
historical evidence.

SEC can append response scripts outside the XBRL filing representation. The
existing SEC integrity policy must still reproduce the permitted normalization
from retained raw, archive, index and parser bytes before any mapping approval.
Changing only the raw hash without matching integrity evidence abstains. Raw
hashes remain in acquisition/integrity evidence, mapping lineage and accounting
rules; a new raw response never overwrites a previous artifact. Unregistered
parser inputs, altered facts, periods, scope or precision remain unsupported.

The retained parser inputs for these existing classifications are:

| CIK | Original accession | Parser-input SHA-256 |
| --- | --- | --- |
| `0001282637` | `0001282637-15-000004` | `d39dc0bc0bfe564d802422b7ece4d64845bd58e194208e2caccb0b7a9c72a2df` |
| `0001282637` | `0001282637-16-000028` | `90b1f0fddb61415dab858235894745b2c2808ee598ac0594b0a28010b808e14c` |
| `0001282637` | `0001282637-17-000005` | `baed1535c218e094d38daa1aca950bc29048a1935596d649a68d53348109a1b5` |
| `0000724910` | `0001376474-23-000283` | `fbab4403625d475d594960fc11a39ef1be6dd079a854647c11243dba9bdb3469` |
| `0000724910` | `0001376474-24-000214` | `9b08f22245c6dbe458fdc90ff1484e87af5e8900b41774be6f4d0d7d7bd8ae57` |

Re-evaluation binds a new mapping/signature to v15 and its executable policy
digest. Prior mappings and failures remain retained. This identity correction
does not expand accounting classifications, change the formal forecast formulas
or establish a supported history threshold.

Policy `source-bound-us-gaap-v17` applies the same identity rule to registered
option-compensation disclosure and the standard US GAAP option-outstanding
quantity and weighted-average exercise-price concepts. Direct mappings retain
the issuer, accession, original bytes, parser input and exact observation scope.
They do not establish a complete award inventory, classify other award types,
or assert that unsupported awards or claims are absent.

Policy `source-bound-us-gaap-v18` selects standard operating/finance lease
liabilities reported at exactly `BalanceSheetLocationAxis` with
`OtherCurrentLiabilitiesMember`. The existing accounting evaluator classifies
that observation as current; noncurrent requires the same concept's consolidated
total minus its current portion. Both original observations keep their dimensions,
scope, reported precision and hashes. The rule binds the complete parsed report,
issuer, accession, raw/parser inputs and optional security identity.

This rule is reusable across issuers and does not require individual mapping
approval or an accession allowlist. It requires numeric nonnegative USD amounts,
the SEC issuer identifier, supported US GAAP namespace, an aligned instant no
later than the original report end, and known reported precision. Conflicting
duplicates, mismatched namespaces, a current portion exceeding its reported
total, and disagreement with a directly reported current/noncurrent concept
abstain. A missing total cannot supply a noncurrent amount. Additional dimensions
and custom location members are outside this rule; missing observations never
prove zero. Existing registered zero-residual rules remain available when this
standard current-location representation is absent. This adds lease liability
mapping only; debt, capital claims, expense scope and award completeness still
require their own evidence.

The exact treasury-stock calculation refuses an exercise-price concept ending
in `WeightedAverageExercisePrice`, including retained accounting-role inputs,
with `DILUTION_AGGREGATE_STRIKE_UNRESOLVED`. Averaging strikes before applying
the per-instrument antidilution limit can hide dilutive awards: two options at
strikes 5/15 and a quote of 10 contribute 0.5 shares, while replacing both strikes
with their average of 10 incorrectly gives 0. A completeness assertion or signature
does not resolve that distribution. Aggregate facts remain retained. Grouping
exceptions or bounded estimates require separately versioned evidence and
policy; the current contract does not authorize them. This check identifies
known tagged averages and does not prove that every other price is homogeneous.

The signed release may retain award observations from several historical
instants. Inventory completeness compares all released award observations at
the inventory's own instant, while older observations retain their original
fact/mapping/source lineage without entering current dilution. An inventory
cannot predate a newer released award observation or omit a current class.
Award observations without a consistent instant refuse. A later explicitly
reviewed empty inventory can retain older awards; historical-only observations
do not themselves prove that the later inventory is empty. Coverage, source,
quote and exact released-fact checks still apply before the official composer.

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

### Registered NVE non-operating investment assets

Automatic policy `source-bound-us-gaap-v8` extends only the 2024 NVE original
above. Its marketable-securities note explicitly puts money-market funds in
cash, corporate bonds in current/noncurrent marketable securities and accrued
investment-interest receivables in prepaid/other assets. The complete balance
sheet separates those investments from trade receivables, inventory, operating
fixed assets, operating leases and deferred taxes. The registered classification
consumes these three consolidated instant components:

| Original's instant | Current corporate bonds | Noncurrent corporate bonds | Investment interest receivable | Non-operating assets |
| --- | --- | --- | --- | --- |
| 2023-03-31 | USD15,513,095 | USD36,125,047 | USD425,372 | USD52,063,514 |
| 2024-03-31 | USD11,917,779 | USD30,788,301 | USD460,627 | USD43,166,707 |

The first two source concepts are `us-gaap:MarketableSecuritiesCurrent` and
`us-gaap:MarketableSecuritiesNoncurrent`. The third is the original extension
`fil:MarketableSecuritiesAccruedInterestReceivable`, bound to namespace
`http://nve.com/20240331` by the complete parsed-fact digest. Amounts come from
original facts, never a hard-coded amount table. The existing `derived`
accounting-role contract retains every component, period, unit, namespace,
reported precision and source reference. Its ordinary component evaluator
computes the sum; the existing formal composer/calculator consumes the role.

The available-for-sale aggregate includes money-market funds already counted
in cash and cannot substitute for this role. Omitting the investment-interest
receivable would also omit a non-operating asset. Neither that aggregate nor
cash enters the component sum. The earlier 2023 original has no equivalent
complete tagged-interest scope and receives no registration from this change;
the comparative interest amount in the 2024 original is available only when
that original was available. No earlier decision can use it retroactively.

The selection requires the exact CIK/accession, raw hash, complete fact multiset
and registered instants. Missing, conflicting, nonfinite, negative, wrong-unit,
wrong-issuer or imprecise components refuse. Equivalent duplicates select the
same fact regardless of input order. Signed approval and release replay repeat
the classification. No source adapter, provider port, public schema, valuation
formula, absence/award claim or history threshold changes.

### Registered NVE cash and current-investment exclusion

Automatic policy `source-bound-us-gaap-v12` extends the same investment selector
(`registered_investment_assets.py`) to the existing
`cash_and_short_term_investments` working-capital exclusion role. The two exact
2023/2024 NVE originals above separately report cash and current corporate-bond
investments on their balance sheets. Only those registered original hashes,
complete parsed fact multisets and instant periods support the classification.

| Original | Instant | Cash and cash equivalents | Current corporate bonds | Combined current-asset exclusion |
| --- | --- | --- | --- | --- |
| 2023 | 2022-03-31 | USD10,449,510 | USD20,839,683 | USD31,289,193 |
| 2023 / 2024 | 2023-03-31 | USD1,669,896 | USD15,513,095 | USD17,182,991 |
| 2024 | 2024-03-31 | USD10,283,550 | USD11,917,779 | USD22,201,329 |

The source concepts are `us-gaap:CashAndCashEquivalentsAtCarryingValue` and
`us-gaap:MarketableSecuritiesCurrent`. Both must be nonnegative consolidated
USD instants at unit-or-finer precision in the same genuine US GAAP namespace.
The existing accounting component evaluator sums them and retains both original
observations, including namespace, precision, issuer/accession, period and
source hashes. Missing, conflicting, mixed-namespace, rounded, foreign or future
evidence refuses. Equivalent duplicates select deterministically.

The 2023 maturity analysis includes USD906,141 in money-market funds within its
USD16,419,236 short-duration total. Those funds are already cash equivalents;
using that total instead of balance-sheet current bonds would duplicate cash.
The all-maturity available-for-sale total, noncurrent bonds and investment
interest receivable therefore never enter this current-asset exclusion. The
separate `non_operating_assets` classification above still includes its three
registered components and remains available only for the 2024 original.

The existing composite recipe covers cash and short-term investments once with
this combined role. It still requires explicit current debt/lease exclusions,
source-bound gross parents and residual inclusion scenarios. No unknown amount
becomes zero, no expense/award/claim absence is inferred, and an exclusion alone
cannot establish a complete valuation. Signature/release replay verifies the
same executable policy. Provider contracts and #352 valuation formulas stay
with their existing owners; the history threshold remains null.

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

### Registered NVE noncontrolling equity

Automatic policy `source-bound-us-gaap-v9` registers the same complete NVE 2023
and 2024 originals for their reported noncontrolling-equity carrying amount.
The [2023](https://xbrl.fasb.org/us-gaap/2023/elts/us-gaap-doc-2023.xml) and
[2024](https://xbrl.fasb.org/us-gaap/2024/elts/us-gaap-doc-2024.xml) FASB taxonomy
definitions distinguish these consolidated instant concepts:

- `StockholdersEquity`: equity attributable to the parent, excluding temporary
  equity and equity attributable to noncontrolling interests.
- `StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest`:
  equity attributable to the parent and noncontrolling interests, excluding
  temporary equity.

The retained taxonomy-document digests are
`288ed00809b3f84f62ee82c93db6f063d4db09bdc4ee6d1654207a1865ded5e7` (2023) and
`96b321b294493af54253a45e3694e85d501857cb4029ba2529089ad9d7880872` (2024).
These documents explain accounting meaning; they supply no issuer amount or
history-threshold ground truth. Source originals remain outside Git.

The two complete audited statements present the equity components and total,
without a separate temporary-equity claim outside this pair. Registration pins
CIK/accession, raw original hash, full parsed-fact digest and the balance-sheet
instants. The 2023 original supports March31 2022/2023; the 2024 original supports
March31 2023/2024. Parent and inclusive total report USD64,565,129 / USD67,079,502 /
USD65,568,517 at the respective instants. The existing accounting evaluator
subtracts reported parent equity from reported inclusive equity. The result is
zero at the reported unit precision, with both source observations retained.
This is a derived carrying amount, not a `confirmed_absent` assertion or a
claim that a missing tag means zero.

This classification is limited to these full original scopes. The two taxonomy
concepts alone cannot resolve temporary/redeemable noncontrolling claims for
another issuer. A changed or unregistered original refuses. Matching requires
USD, the same US GAAP namespace, consolidated issuer scope, an eligible instant,
nonnegative finite values and unit-or-finer reported precision. Missing or
conflicting components, rounded thousands, a total below the parent amount, or
future periods refuse. Equivalent duplicates select deterministically.

Automatic proposal, signed approval and retained-input canary reconstruction use
the same rule through the existing provider-neutral parser/fact contracts. No
provider request, valuation formula, financial selector, public schema or agent
implementation changes. The remaining accounting/award/market gaps still block
complete numerical valuation; supported-history thresholds stay null.

### Registered NVE noncurrent liability partition

Automatic policy `source-bound-us-gaap-v10` also registers the same two complete
NVE originals for an exhaustive noncurrent liability reconciliation. At March31
2022/2023/2024, total liabilities are USD2,902,363 / USD2,175,668 / USD1,211,516;
current liabilities are USD2,456,345 / USD1,832,760 / USD1,035,741; noncurrent
operating lease liabilities are USD446,018 / USD342,908 / USD175,775. The full
statements present this partition without offsetting noncurrent liability
components. The original hashes and complete parsed-fact digests are pinned,
with the same original and comparative instants as the equity registration.

The existing accounting evaluator computes total liabilities minus current
liabilities minus noncurrent operating lease liabilities. Only an exactly zero
residual at unit-or-finer reported precision can supply both
`long_term_interest_bearing_debt` and `long_term_finance_lease_liabilities`.
These are nonnegative components of the registered residual; neither can carry
a positive balance when that exhaustive residual is zero. A positive or negative
residual refuses both classifications; the policy cannot allocate an unknown
aggregate between debt and finance leases. This does not authorize netting,
unreported liabilities, or this partition for another original.

Each derived fact retains all three source observations, their original
contexts, instants, units, reported precision and namespace, together with its
source/mapping/policy pins. Signed mapping approval and independent retained-input
reconstruction use this same source-neutral policy. Missing, conflicting,
rounded, mixed-currency, mixed-namespace, foreign-entity or future-period
components refuse. Equivalent duplicates and input order are deterministic.

These are reported carrying-amount zeros, not `confirmed_absent` assertions.
They prove neither current borrowing classifications nor annual finance lease
expense: a lease paid off during the year could have expense and no closing
balance. No award, market input, release, caller approval or verified valuation
is inferred. The remaining gaps stay visible and history thresholds remain null.

### Registered NVE current liability principal partition

Automatic policy `source-bound-us-gaap-v11` moves the shared residual evaluator
to `registered_liability_residuals.py` and registers a separate current partition
for those same two original NVE statements. It retains the noncurrent policy
above. New executable dependencies change the approval digest; prior policy
certificates cannot authorize this version.

The complete original balance sheets present current liabilities as three
nonoverlapping lines: accounts payable, accrued payroll and other, and operating
lease liabilities. This original-specific classification treats vendor goods/
services payables and accrued costs separately from borrowing and finance-lease
principal. The evaluator requires all four consolidated, nonnegative USD
observations at unit-or-finer precision and computes:

```text
current principal residual = LiabilitiesCurrent
                          - AccountsPayableCurrent
                          - AccruedLiabilitiesCurrent
                          - OperatingLeaseLiabilityCurrent
```

Only an exactly zero residual supplies `current_interest_bearing_debt` and
`current_finance_lease_liabilities`. Every derived fact retains all four original
observations, reported precision, namespace, issuer, instant, accession, source
hash and mapping/policy pins. Missing, nonzero, conflicting, rounded, foreign,
future or mixed-namespace evidence refuses. Equivalent duplicates select
deterministically; an equivalent amount in another namespace also refuses.
Another issuer or changed original cannot inherit this classification.

External calibration uses the [official FASB2024 definitions](https://xbrl.fasb.org/us-gaap/2024/elts/us-gaap-doc-2024.xml)
(retrieved SHA256
`96b321b294493af54253a45e3694e85d501857cb4029ba2529089ad9d7880872`).
`AccountsPayableCurrent` describes vendor obligations for goods and services;
`AccruedLiabilitiesCurrent` describes costs, including taxes, interest, rent and
utilities. `FinanceLeaseLiabilityCurrent` describes the discounted lease-payment
obligation. The definitions alone establish no issuer amount: the registered
complete statements and their unnetted reconciled partition supply this scope.

The mixed accrued-cost line is not classified as entirely operating. Its
operating fraction remains an explicit estimate under the existing composite
working-capital policy. This instant carrying-amount result is not a
`confirmed_absent` assertion, does not establish annual finance-lease expense,
and supplies no preferred/convertible/share-class or award absence. Those gaps,
market/release/caller-approval requirements and the null history threshold remain.

### Single dated disclosure balances

`DisclosedInstantAmountV1` represents one complete balance quoted inside annual
prose. It uses the same exact amount, currency, scale, precision and date-token
checks as dated disclosure components. Its explicit date must match the target
instant and fall within the original annual or opening comparative period.
The parsed text fact keeps its original duration; normalization produces a
separate instant candidate with all original facts and source spans attached.
Existing undated duration disclosures retain their canonical representation.

Automatic policy `source-bound-us-gaap-v13` registers the NVE originals
`0001376474-23-000283` and `0001376474-24-000214` by original hash and complete
parsed-fact digest, using the same two pins documented above. Their complete
option notes state total unrecognized compensation related to nonvested options
as of March 31, 2023 and March 31, 2024: USD2,173 and USD4,181, respectively.
The exact sentence and its date/amount offsets enter the existing accounting
rule evaluator; the registry supplies classification, never numeric amounts.
Changed originals, other dates, unknown classes, partial/ambiguous sentences
and changed parsed observations abstain. Automatic mapping signs only after
retained original/integrity/taxonomy and the executable policy checks pass.

Policy `source-bound-us-gaap-v14` anchors this computed balance to
`us-gaap:DisclosureOfCompensationRelatedCostsShareBasedPaymentsTextBlock`.
The v13 dispatcher incorrectly retained the D&A default anchor; #437 records
that audit-lineage defect. Existing v13 artifacts remain immutable evidence.
Re-evaluation under v14 creates a distinct mapping and signature, even when
the transcribed balance and explicit date remain the same.

This role is `equity_award_unrecognized_compensation`. Its approval does not
establish award quantities, exercise-price distributions, complete company-wide
inventory, performance conditions, a quote or a trusted complete data release.
The annual option aggregate and the proxy's named-executive statements cannot
alone establish all those claims. Treasury-stock arithmetic, forecasts and
valuation remain with the existing formal composer/calculator; unsupported
history thresholds remain null.
