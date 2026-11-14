# Conditional enterprise value without a complete equity bridge

`enterprise_research.research_enterprise_value` asks a narrower question when
complete capital-claim, award or quote evidence is unavailable: what enterprise
value follows from the operating forecast under each declared discount scenario?
It produces no common-equity value or per-share price. Missing capital claims
remain unknown. Full valuation preparation retains all its existing gates.

The request pins complete canonical facts, snapshot/operating-source identity,
mapping and release references, model/policy versions, optional history window
and composite working-capital inputs. It calls the existing #352
`prepare_operating_forecast`, which selects eligible annual facts, derives
metrics and composes the forecast. Tax comes from that preparation; a scenario
cannot override it. Operating refusals remain in every requested scenario.

Each named scenario carries the existing market-policy input schema, rationale
and evidence digests. Evidence must declare both as-of and available-at times,
each no later than the valuation timestamp. These references preserve the researcher's assumptions and lineage;
they do not authenticate source bytes, source-use permission, mapping review,
market-policy approval or release authority. The schema's name
`ApprovedMarketPolicyInputsV1` is shared with the existing internal composer;
accepting it here grants no approval. Scenario rationale must explain the
assumption and source limits. Source admission and trusted release remain
separate responsibilities.

The full calculator and research use the same `project_enterprise_nodes`
function. It evaluates the existing operating graph, WACC, annual discounting,
terminal value and enterprise value in the released 50-digit Decimal context.
The extraction preserves the calculator's node ordering, operation ordering,
formulas and model/numerical versions. Research also retains the composer's
terminal-growth gate against cost of equity. It never supplies dummy zero
claims or a dummy diluted-share denominator to call the full calculator.

Successful rows are `provisional_conditional_enterprise_value`; unavailable
operating evidence, undated/future market evidence and invalid discount
scenarios retain `abstained` rows and stable reason codes beside successful
siblings. Negative enterprise values, if produced by valid assumptions, remain
negative. Scenario counts do not increase independent issuer count. Results
are sampled conditional conclusions, without confidence intervals or global
bounds. `supported_history_threshold` stays null.

Requests canonicalize facts, scenario order and evidence references. Reports
retain the complete operating preparation, discount scenarios, model-spec
digest and input/output digests. Existing immutable artifact storage can persist
requests/reports by digest, using its locks and temporary-file/atomic-rename
writer. The research functions perform no I/O, signing, release activation,
caller approval or HTTP orchestration. This is a callable research method;
it is not automatically substituted into production valuation preparation.
