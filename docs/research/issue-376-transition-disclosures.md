# Conditional Transition operating disclosures (#376/#383)

The registered `transition_fcff_dcf-v2` requires a filed operating evidence
reference. Previously, the SEC mapper emitted numeric observations only, and
the conditional scenario path reused the released preparation gate requiring
verified evidence. Retaining an unreviewed filing did not satisfy that gate.

Fundamental Service now maps two explicitly scoped annual consolidated text
observations to `filed_operating_evidence`: `us-gaap:ConsolidationPolicyTextBlock`
and `us-gaap:SegmentReportingDisclosureTextBlock`. The exact parser value is
retained as text with its context, period, accession, availability, original and
parser hashes, observation digest and mapping identity. An explicit observation
scope is required. Text cannot map to a monetary role or become a numeric
forecast parameter. Other nonnumeric observations remain excluded.

## Research authority

The optional `fundamental.conditional-transition-disclosures.v1` nested contract
pins `unreviewed-filed-operating-disclosures-v1`, its complete policy digest and
two distinct fact IDs. Both observations must reproduce from the latest
eligible original, match the decision's current annual period and consolidated
issuer scope, and retain provisional quality and unreviewed mappings. Missing,
conflicting, substituted, future, dimensional or numeric observations refuse.
The proof is verified once for the immutable request, before scenario execution.

Only this explicit research opt-in permits conditional Transition execution.
Results retain `TRANSITION_DISCLOSURES_UNREVIEWED`,
`MODEL_SUITABILITY_UNESTABLISHED` and the existing unreviewed allocation and
history warnings. This verifies a source reference; it does not establish a
high-growth archetype, model suitability, accounting interpretation, trusted
release or approved forecast. The released `_transition_filing_evidence` gate
still requires verified evidence and refuses these provisional facts.

Omitting the nested contract preserves old request serialization and the prior
Transition refusal. No old artifact is rewritten. The source/mapping manifest
digest changes for the new request; all prior numeric facts and mapping records
remain verbatim. Original scope and capture gaps remain visible.

Both registered models currently use the same #352 assumption composer and
operating graph. Their conditional numeric results therefore agree for identical
inputs. This is two registered execution paths with different evidence gates,
not independent predictive methods or corroborating statistical samples. Source
reference IDs are added to Transition lineage without altering arithmetic.

## Fixed NEWMARKET source

The retained 2015 original is accession `0001282637-16-000028`, available at the
unchanged origin `2016-02-12T16:26:17Z`. Its consolidation policy identifies
Afton/petroleum additives, Ethyl/TEL, NewMarket Development and shared services.
The segment disclosure retains revenue, operating profit and consolidated
reconciliation. These are historical filed observations; no analyst, company
forecast, search result or LLM-derived value supplies an outcome.

The unchanged first subsequent original `0001282637-17-000005` stays label-only.
Existing working-capital and continuing-capex allocations still determine
conditional comparisons. A successful conditional run does not resolve their
unknown classifications. Independent issuers remain one, exact study cases
remain zero, and `supported_history_threshold` remains null.

## Compile and replay

Use the frozen longest-history comparison request and clean exact commit:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=fundamental-service/src:scripts \
  python -B scripts/compile_transition_disclosures.py \
  --seed /external/frozen-five-year-comparison.json \
  --exact-commit <full-clean-commit> \
  --output-directory /external/conditional-transition
```

The command reads existing originals only. It emits observation-scoped mapping
proposals, two provisional text facts, a new comparison request and source audit.
It records selected and rejected-concept candidate digests; retains every old
numeric fact, mapping, scenario, inventory and label; and grants no review.
Canonical digests identify every artifact. Publication uses the existing locked
temporary-file/fsync/atomic-rename publisher outside Git. Repeat returns
`wrote=false`, equal digests and unchanged bytes, sizes and modification times.

Pass the emitted comparison request to the existing fixed-window seed index,
`replay_history_study_windows.py`, `export_history_study_evidence.py` and
`analyze_history_study.py`. The existing exporter independently reproduces every
forecast/comparison before publishing the unchanged 100-issuer panel. All
other issuers, abstentions and missing original labels remain retained. The
exploratory #377 protocol does not approve promotion from this single case.
