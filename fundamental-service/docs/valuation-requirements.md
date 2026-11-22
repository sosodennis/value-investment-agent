# FCFF evidence dependencies

The official #352 composer and calculator use requirements V4 for `fcff_dcf-v2`
and `transition_fcff_dcf-v2`. Model arithmetic stays unchanged. The versioned
requirements profile identifies data dependencies separately from supporting
diagnostics; its complete content digest binds source plans and releases.

Annual numerical dependencies are revenue, operating income, pretax income,
income tax expense, operating D&A and cash capex. The composer uses these to
derive growth, operating margin, tax, NOPAT and reinvestment. Opening/closing
working-capital evidence remains required under either the exact six-account
policy or the explicitly selected composite policy. Missing any dependency
retains its reason and abstains. History thresholds remain unvalidated and null.

Annual COGS, net income, operating/finance lease expense, stock compensation and
basic/diluted weighted-average shares remain supporting diagnostics. Existing
source acquisition, mapping reports and releases retain observations and all
unsupported/missing-role decisions. They are not operands of these executable
models, so their absence alone does not block a numerical preparation. No
missing amount is filled with zero or described as confirmed absent. Supplied
diagnostics stay in released evidence and input provenance; changing their
content can change evidence/input identity even when numerical results agree.
The independent release canary admits supporting roles from the pinned composite
profile or a complete compatible ordinary valuation profile. Each supplied fact
still requires its released mapping, original source and canonical digest.
Unknown supporting roles remain refused; optional never means unvalidated.

Capital-bridge claims remain separate required point-in-time facts: cash,
nonoperating assets, borrowing and lease principal, preferred/convertible claims,
noncontrolling interests, outstanding common shares and other share classes.
Instrument-level award inventory and an eligible dated quote still determine
dilution; historical average shares cannot replace them. Market/policy evidence,
trusted release and transition filing evidence when applicable retain their
existing gates. A missing finance-lease expense does not
imply zero finance-lease principal or authorize a complete issuer valuation.

V4 replaces the full V3 requirements contract. Old profile digests cannot
authorize new automatic acquisitions or release canaries; regenerate the plan
and verify its new requirements digest. Retained V3 artifacts are preserved.
This change supplies no accounting classification, source approval, verified
quality or history threshold. The existing typed provider ports and official
composer/calculator own acquisition and arithmetic respectively.

### Explicit hypotheses for unresolved capital balances

The optional `balance_hypotheses` in a conditional capital recipe/policy uses
`conditional-capital-balance-hypotheses-v1`. It can designate a nonempty subset of
`current_interest_bearing_debt`, `non_operating_assets` and
`noncontrolling_interests` as unknown hypothetical operands. It requires every
designated role in the ordered base/downside/upside scenarios, finite nonnegative
amounts, a separate explanation for each role, limitations and sensitivity for
each unknown. These are conditional what-if values, not observed amounts,
calibrated estimates, probability intervals or proven economic bounds.

Non-operating asset assumptions exclude cash and operating assets. Current debt
assumptions exclude noncurrent debt and the additional convertible exposure
declared elsewhere. Every amount represents the complete hypothetical role;
partial disclosed components do not establish its total. The extension does not
change financial formulas or grant source, mapping or release approval.

Without this extension the original ten observed balance requirements remain.
With it, source profiles keep designated roles as supporting evidence and the
bound policy keeps them in `unknowns`. Available verified observations at or after
the policy balance date cannot be replaced by hypotheses. Other observed roles,
source/snapshot/fact bindings and quote eligibility remain required. Composite
working-capital policies still need their observed exclusions; hypothetical
current debt cannot replace an exclusion fact. A joint forward reinvestment
policy can instead retain unknown historical reinvestment under its own explicit
what-if assumptions.

The recipe is bound into the source configuration/plan digests and the complete
policy is covered by trusted release signatures and assessment digests. The
formal composer retains these digests and all unknown roles, prepares provisional
scenario inputs for direct exact-input calculation after the existing evidence
and model-quality checks. No company-specific registration is needed
for this input representation. Real source/model sufficiency and end-to-end
acceptance must still be established separately.

### Supporting aggregate award disclosures

Conditional capital profiles include two optional roles for the standard FASB
2025 `AwardTypeAxis` / `RestrictedStockMember` disclosure: nonvested instrument
quantity excluding options, and aggregate unrecognized compensation cost. The
versioned `standard-restricted-stock-aggregate-disclosures-v1` rule retains the
original dimensions, instant, unit, precision and source identity in classified
accounting evidence. The parser also retains each axis/member namespace URI;
both must match the supported taxonomy. Prefix strings alone, including old
reports without this evidence, cannot authorize the new scope. Duplicate facts
must be consistent as a complete group;
selection uses the existing deterministic precision policy. Other dimensions,
taxonomy versions or units require their own supported rule and remain refused.

These roles are supporting observations. Restricted stock may include performance
conditions, and its aggregate cost may cover multiple economic instruments. The
roles do not establish RSU/PSU composition, settlement, issued-share inclusion,
maximum delivery, compensation allocation or complete inventory. They cannot be
used as exact instrument quantity, exercise price or allocated compensation.
The conditional policy binds every released supporting award observation while
retaining these unknowns and its explicit hypothetical dilution operands.

The added support changes conditional profile identities and automatic mapping
policy version/digest. Regenerate conditional source plans against the new
profiles; the ordinary exact V4 profiles and dilution contracts retain their
existing identities and evidence requirements. Real numerical acceptance still
requires the eligible quote, market policy, trusted release and exact-input
calculation checks.
