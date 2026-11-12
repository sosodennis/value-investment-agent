# Composite noncash working-capital input V1

This Fundamental Service input policy is implemented for evaluation. It does not approve an issuer classification, product release, verified valuation, or history threshold.

The exact six-component working-capital path remains available. The separate `composite-noncash-working-capital-v1` requirements profile uses reviewed gross current assets and liabilities, with explicit source-bound exclusions and residual operating-fraction assumptions. FCFF continues through the existing #352 composer and calculator.

For each period, `CompositeWorkingCapitalInputV1` pins the policy digest, mapping version, issuer, period, original accession, source hash, gross-total fact IDs and exclusions. Required exclusions cover cash, short-term investments, current interest-bearing debt, and current operating- and finance-lease liabilities. Each exclusion identifies its gross parent, the actual mapped fact role, and the classes covered. A combined reported amount may cover several classes but is subtracted only once. Confirmed absence requires a mapped zero fact with confirmed-absence accounting evidence. Unknown required exclusions abstain; a missing tag never means zero.

```text
asset_residual = current_assets - explicit_asset_exclusions
liability_residual = current_liabilities - explicit_liability_exclusions
estimated_OWC = asset_residual * asset_fraction - liability_residual * liability_fraction
```

Both fractions require explicit low, central, high values and a rationale. At least one side must have nonzero sensitivity. One-at-a-time scenarios vary one fraction while holding the other at its central value. These are deterministic scenarios, not confidence intervals, statistical bounds, or evidence that the residual is entirely operating. Reviewers must judge the perimeter and assumptions against the retained filing evidence; signatures alone do not supply that judgment.

The assessment retains canonical facts including units, scale, original concepts, scopes, amendment metadata, mapping decisions and source hashes. Source/issuer/period mismatch, future availability, amendments, duplicate facts or observations, overlapping exclusions, invalid amounts and unsupported absences abstain. Canonical serialization binds input, policy and assessment digests. The signed issuer-release manifest includes the entire policy input and assumptions. The existing release canary revalidates each input against the release's pinned originals and mappings before publication, and serving rechecks the release after restart.

Call `prepare_operating_forecast(..., working_capital_inputs=inputs)` for either operating model, or `prepare_automatic_valuation(..., working_capital_inputs=inputs)` for full valuation. Omit these inputs to retain the exact profile. Full valuation still requires the existing market-policy, capital-bridge and dilution evidence; aggregate working capital does not replace those gates.

Estimated history and forecasts remain provisional. `supported_history_threshold` remains null. This increment does not resolve NEWMARKET 2013 continuing-capex scope or establish a trusted NEWMARKET release, first-subsequent label, forecast error, or complete fixed-cohort replay. Freeze the #377 evaluation protocol before using outcomes to select a history threshold; any estimated label must be identified as an estimate under this input-policy version.
