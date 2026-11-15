# Source-bound forward reinvestment hypotheses

`conditional-forward-reinvestment-v1` binds deployment assumptions to verified
original-derived annual core observations. It does not reconstruct historical
capital expenditure, pure depreciation and amortization, working capital or
reinvestment. Those amounts remain unknown. It grants no mapping approval,
release signature, caller approval or valuation authority.

## Contract and ownership

`conditional_reinvestment_contracts.py` owns immutable recipes, bound policies
and assessment serialization. `conditional_reinvestment.py` binds and assesses
them using the existing annual-history resolver. No valuation formulas move out
of the formal composer or calculator.

A recipe requires the supported model/version, mapping version, an immutable
assumption document URI/digest, explicit base/downside/upside reinvestment rates,
a rationale for each rate and limitations. All three rates must differ and stay
inside the existing forecast input range [-1, 1]. Scenario names do not assert
probabilities, economic bounds or calibrated estimates. There are no default
rates. The recipe document is deployment evidence; its reference alone does not
prove that its bytes have been stored or verified.

The binder pins the installed executable policy, exact snapshot, issuer,
security, currency, valuation timestamp, history profile and selected fact
digests. It requires at least three consecutive complete annual periods of
revenue, operating income, pre-tax income and tax expense. Each period's four
flows must share one original. The shared history resolver handles period
alignment, concept conflicts and latest-available selection. Assessment rejects
stale fact references and invalid source, context, mapping, unit or date
bindings. Every supplied core candidate must be annual under the shared history
window, and its original must have an HTTP 200 receipt and be available on or
after its period-end. It cannot select away an invalid supplied core candidate. Canonical
ordering makes replay independent of input order. `supported_history_threshold`
stays null and assessments remain provisional.

The generic requirements contract permits duration-only history profiles.
Existing exact valuation profiles retain their roles and digests. The explicit
conditional release profile requires the four core annual flows and the existing
observed capital roles. Excluded historical reinvestment roles remain supporting
evidence, with their original mapping failures retained. This profile does not
register automatic source-plan compilation or authorize full valuation preparation.

`conditional_reinvestment_release.py` owns immutable release admission. Policies
cover every declared security snapshot exactly once in canonical order and pin
their core observations to exact released fact digests. Assessment requires the
entire released fact set, including supporting observations. It refuses mixed
model/mapping versions, a conflicting historical working-capital policy and any
weakening of the service-owned required field profile.

The assumption document must be retained under an exact `artifact://` identity
in the manifest with role `conditional-reinvestment-assumptions-v1` and media
type `application/json`. `reinvestment_assumption_document` produces its canonical
bytes from the recipe's model/version, mapping, interpretation, limitations and
three explicit scenarios, excluding the document's own URI/hash. Admission reads
the actual bytes, verifies their SHA256 and compares the complete document to the
bound recipe. A URI, a hash label, an unrelated JSON document or a candidate role
cannot substitute for this evidence.

The read-only release canary reproduces the bound policy and formal operating
forecasts, recording the resulting output digests in its content report and
signed-verification-bound canary digest. These checks grant no source entitlement,
mapping approval or caller approval. Existing manifests omit the new fields when
unused, preserving their canonical identity. Full composer and automatic-plan
integration must still put the same assumptions, limitations and sensitivity into
the exact caller input.

`valuation_preparation.compose_conditional_operating_forecasts` is the internal
operating forecast boundary. It reproduces the source-bound policy assessment,
uses the same core metric and forecast formulas as the existing composer, and
returns three forecast assumptions plus their assessment and historical core
metrics. Composition uses the assessment's canonical policy, including scenario
order. The result and input digest retain the shared composer version, numerical
policy version and executable identity of the composer and numerical policy.
The result retains unknown historical reinvestment roles. It emits no
historical reinvestment-rate or realized-FCFF metrics. Invalid core denominators
and the existing forecast growth bounds still refuse. Supplying only core
metrics to the existing historical forecast route still fails without an
explicit reinvestment hypothesis.

This operating result is neither a full valuation input nor an approved
policy/release. Capital claims, award dilution, market policy, entitled quote,
trusted release/canary, exact caller approval and calculator/result persistence
remain the full valuation's separate mandatory boundaries.

## Shared accounting rules and candidate evidence

The current gaps are semantic classes, not issuer exceptions:

| Problem | Reusable admission condition | Unsafe shortcut |
| --- | --- | --- |
| Taxonomy year | Pin definitions and type/period/balance equivalence for each supported namespace | Infer equivalence from the local tag name |
| Current debt | Prove a complete, disjoint perimeter excluding separately handled leases | Treat commercial paper as all short-term borrowing or missing as zero |
| Pure D&A | Prove the operating expense perimeter and exclude other adjustments | Rename a D&A-and-other cash-flow adjustment |
| Reinvestment | Account for all consumed cash/noncash and operating/nonoperating components | Treat PPE cash payments as total reinvestment |

FASB Meta Model Relationships are useful candidate evidence for class/subclass,
aggregate/other and accounting traits. The official 2026
[class/subclass linkbase](https://xbrl.fasb.org/us-gaap/2026/meta/us-gaap-classSubclass-2026.xsd)
links `DebtCurrent` to `LongTermDebtCurrent` and `ShortTermBorrowings`.
Its SHA256 is
`881a10eb75581ff9ce7005d799d5a37c570d5cf6e9e3f9c9561285ccb2865499`.
The corresponding
[aggregate/other linkbase](https://xbrl.fasb.org/us-gaap/2026/meta/us-gaap-aggregateOther-2026.xsd)
retains other short-term borrowing and other current long-term debt components.
These relationships do not establish that an issuer reported every component,
and 2026 relationships do not replace a filing's pinned older taxonomy.

[XBRL International's Calculations 1.1 guidance](https://www.xbrl.org/guidance/adopting-calc1-1/)
explicitly describes incomplete fact sets and calculation trees. A matching
sum or absence of validation errors does not establish completeness.
[EdgarTools' cross-company mappings](https://www.edgartools.io/i-learnt-xbrl-mappings-from-32-000-sec-filings/)
can inform candidate discovery and industry/year handling. Their coverage and
confidence scores do not establish trusted admission or valuation success.

The SEC API and FASB overview pages supplied for this research returned HTTP
403 in this environment. The official FASB linkbases above were retrieved
successfully; originals, retrieval failures and digests remain outside Git.
The SEC original remains the financial evidence source.

Before promoting new common mapping rules, evaluate an issuer that did not
participate in rule development without adding issuer/accession logic. Report
mapping correctness, retained refusals and complete numerical workflow success
separately. Synthetic two-issuer binding tests do not satisfy that acceptance.
