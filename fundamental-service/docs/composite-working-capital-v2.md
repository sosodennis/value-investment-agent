# Composite noncash working-capital input V2

This Fundamental Service input policy is implemented for evaluation. It does not approve an issuer classification, product release, verified valuation, or history threshold.

The exact six-component working-capital path remains available. The separate `composite-noncash-working-capital-v2` requirements profile uses reviewed gross current assets and liabilities, with explicit source-bound exclusions and residual operating-fraction assumptions. FCFF continues through the existing #352 composer and calculator.

Automatic mapping policy `source-bound-us-gaap-v6` supports direct original
`us-gaap:AssetsCurrent` and `us-gaap:LiabilitiesCurrent` observations. Each
approval binds the consolidated USD instant observations to the original issuer,
accession and parsed source. The machine authority must trust the new policy
digest; an earlier policy certificate cannot authorize it. These gross-total
approvals do not classify residual balances or supply exclusions or assumptions.

For each period, `CompositeWorkingCapitalInputV1` pins the policy digest, mapping version, issuer, period, original accession, source hash, gross-total fact IDs and exclusions. Required exclusions cover cash, short-term investments, current interest-bearing debt, and current operating- and finance-lease liabilities. Each exclusion identifies its gross parent, the actual mapped fact role, and the classes covered. The executable V2 policy binds each canonical exclusion role to its exact accounting classes and balance-sheet side. Direct roles cover only their named class. The supported combined role `cash_and_short_term_investments` covers exactly cash and short-term investments on the asset side and is subtracted once. Other combinations and issuer-specific role strings abstain until their source-bound classification is implemented and reviewed in a new policy version. Caller coverage lists, rationale and trusted signatures cannot establish this relation. Confirmed absence requires a mapped zero fact with confirmed-absence accounting evidence. Unknown required exclusions abstain; a missing tag never means zero.

```text
asset_residual = current_assets - explicit_asset_exclusions
liability_residual = current_liabilities - explicit_liability_exclusions
estimated_OWC = asset_residual * asset_fraction - liability_residual * liability_fraction
```

Both fractions require explicit low, central, high values and a rationale. At least one side must have nonzero sensitivity. One-at-a-time scenarios vary one fraction while holding the other at its central value. These are deterministic scenarios, not confidence intervals, statistical bounds, or evidence that the residual is entirely operating. Reviewers must judge the perimeter and assumptions against the retained filing evidence; signatures alone do not supply that judgment.

The assessment retains canonical facts including units, scale, original concepts, scopes, amendment metadata, mapping decisions and source hashes. Source/issuer/period mismatch, future availability, amendments, duplicate facts or observations, overlapping exclusions, invalid amounts and unsupported absences abstain. Canonical serialization binds input, policy and assessment digests. The signed issuer-release manifest includes the entire policy input and assumptions. The existing release canary revalidates each input against the release's pinned originals and mappings before publication, and serving rechecks the release after restart.

Call `prepare_operating_forecast(..., working_capital_inputs=inputs)` for either operating model, or `prepare_automatic_valuation(..., working_capital_inputs=inputs)` for full valuation. Omit these inputs to retain the exact profile. Full valuation still requires the existing market-policy, capital-bridge and dilution evidence; aggregate working capital does not replace those gates.

## Signed security releases

A full security release can declare `valuation_working_capital_policy` using
`ValuationWorkingCapitalPolicyV1`. It pins the supported model ID/version,
full valuation requirements-profile digest, mapping version and canonical
source-bound inputs. `required_fields` must exactly match
`composite_working_capital_requirements_profile(model_id, operating_only=False)`.
Include every input's gross and exclusion fact ID/digest in the corresponding
snapshot reference, with its approved mapping in `mapping_refs`.

The independent release canary assesses every declared input against those
facts and the original snapshot. Wrong model/profile/mapping pins, missing or
foreign facts, unbound inputs and unknown required exclusions refuse release.
Serving selects the same pinned profile and supporting facts and passes the
inputs to the official composer. Estimated inputs retain their source evidence,
residual assumptions, deterministic sensitivity and provisional quality.

An omitted policy preserves ordinary release serialization and digests. Issuer
operating releases continue to use their existing `working_capital_inputs` field
and cannot also declare the security policy.

## Source preparation

Both manual-mapping and automatic-mapping source plans can explicitly carry
the same `valuation_working_capital_policy`. The plan pins its model, mapping,
issuer and original accessions; a candidate or active release must contain the
identical policy. Omitting the policy retains ordinary plan bytes and digests.

`source_preparation_requirements_profile(model_id, composite_inputs=True)`
acquires gross totals, the full model requirements and optional exclusion roles.
Automatic mapping accepts only the exact service-owned ordinary or composite
source profile. Every unsupported optional role remains a retained refusal;
it does not automatically become a required zero balance. Composed history
must contain every declared supporting fact under the plan's source/mapping
pins. Unknown, missing, future or foreign-mapped exclusions block preparation.
The signed release still uses the full valuation profile, independently checks
those facts, and passes the same inputs to the official composer.

This plan contract takes already bound input facts and explicit residual
assumptions. It does not yet compile them from an automatic policy recipe or
establish complete real issuer evidence. Source providers remain replaceable
through the existing [provider ports](market-input-providers.md); source-plan
policy and the composer do not interpret provider-specific formats.

Estimated history and forecasts remain provisional. `supported_history_threshold` remains null. This increment does not resolve NEWMARKET 2013 continuing-capex scope or establish a trusted NEWMARKET release, first-subsequent label, forecast error, or complete fixed-cohort replay. Freeze the #377 evaluation protocol before using outcomes to select a history threshold; any estimated label must be identified as an estimate under this input-policy version.

V2 replaces the pre-integration V1 evaluation policy to resolve #416. Its digest includes the executable role/class/side relation. Existing V1 inputs and certificates cannot authorize V2; regenerate and review inputs under the new version. The original facts and retained evidence are not rewritten.
