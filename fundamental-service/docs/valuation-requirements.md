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
trusted release, transition filing evidence when applicable and authentic caller
approval retain their existing gates. A missing finance-lease expense does not
imply zero finance-lease principal or authorize a complete issuer valuation.

V4 replaces the full V3 requirements contract. Old profile digests cannot
authorize new automatic acquisitions or release canaries; regenerate the plan
and verify its new requirements digest. Retained V3 artifacts are preserved.
This change supplies no accounting classification, source approval, verified
quality or history threshold. The existing typed provider ports and official
composer/calculator own acquisition and arithmetic respectively.
