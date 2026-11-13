# Fixed-cohort conditional evidence adapter

`scripts/export_history_study_evidence.py` connects frozen Fundamental Service
requests and outputs to the #377 research panel. It verifies conditional
arithmetic by calling the formal scenario and label replay functions, which
use the #352 composer and shared metrics. It contains no FCFF formula.

The export does **not** authenticate a trusted release, reparse SEC originals,
approve accounting classifications, or make an exact label. Its evidence
authority is `recomputed_conditional_arithmetic_not_trusted_release`.
The independent review, primary policy and promotion requirements in
`issue-377-methods-v4.json` remain open. NEWMARKET outcomes were already seen;
this increment cannot become retrospective preregistration.

## Frozen input boundary

The CLI takes the unchanged external fixed-100 manifest, an external evidence
index and a clean exact commit. The index uses
`schema_version: history-study-evidence-index.v1`,
`fixed_manifest_digest`, `runtime`, and `entries`.
Each entry contains `request`, `forecast`, and `comparison` references, each
with a local `path` and raw-byte `sha256`. Relative paths resolve against the
index directory. `runtime` must equal `runtime_pins()` from the adapter:
Python/implementation/platform, installed Pydantic/Arelle/cryptography versions,
and the checkout's `fundamental-service/uv.lock` digest.

Every referenced file must exist, have the pinned raw digest and use canonical
serialization. Duplicate JSON fields fail. Request validation binds executable
model/policy versions and mapping manifests. The adapter binds issuer, decision
timestamp/accession/base period, first subsequent original and eligible horizon
to the fixed manifest. It refuses duplicate issuer/history arms. Shared
mapping, source-selection, label, scenario fractions, common capex assumptions,
model/spec, composer and numerical-policy identities cannot change between
history arms. Formal replay validates original reports and reproduces selected
facts from their mappings; supplied output bytes must exactly equal its results.

There is no network or acquisition fallback. Missing or obsolete frozen
evidence fails explicitly. A new runtime or model implementation requires a
new, deliberate verification; the adapter cannot silently repair old outputs.
Parsed original reports and declared source hashes remain distinct from
independently retrieved bytes and trusted review signatures.

## Retained results

The versioned export preserves complete typed requests, original reports,
fact IDs/scopes/units/periods/accessions, mapping manifests, assumptions,
forecasts, labels and comparisons in its conditional appendix. It also reports
per-model/arm counts and all issue codes. Scenario counts never multiply issuer
counts. An issuer with only abstentions counts as represented, with zero issuers
having a numerical conditional comparison.

The analyzer panel retains all 100 issuers and all 12 model/target/history cells.
It contains no scored exact losses. A conditional grid does not define a primary
point forecast, training scale or naive loss; the adapter does not choose these
after seeing results. Conditional FCFF cells remain abstained in the exact panel,
with every numerical scenario preserved separately. Revenue comparison is
explicitly unavailable at this boundary. Missing four/five-year inputs remain
missing; a three-year request cannot supply those arms. Frozen missing labels,
horizon mismatches and official Transition/source refusals remain visible.

`complete_exact_study_cases` is zero and `supported_history_threshold` is null.
Scenario dispersion is not an issuer sampling distribution or confidence
interval. This is the conditional arithmetic bridge; authenticated exact
releases/labels and the complete empirical study remain separate acceptance work.

## Run and repeat

Use the pinned Fundamental Python runtime, with `PYTHONPATH` pointing to this
checkout's `fundamental-service/src`, and bytecode writing disabled:

```sh
python -B scripts/export_history_study_evidence.py \
  --manifest /external/fixed-manifest.json \
  --evidence-index /external/frozen-evidence-index.json \
  --exact-commit <clean-HEAD-SHA> \
  --output-directory /external/research-export
```

The CLI publishes the panel as `<loss_panel_digest>.json` and the full report as
`<report_digest>.json`. Feed the panel file directly to
`scripts/analyze_history_study.py` with the pinned v4 methods and same manifest.
All generated inputs, SEC evidence and reports stay outside Git.

Input/report identities include the exact commit, runtime and content digests;
paths are locators, not identity. Output publication reuses the existing locked,
temporary-file/fsync/atomic-rename publisher. Matching artifacts return
`wrote=false`; corrupt destinations fail. A crash between panel and report
publication is resumable because each is immutable and addressed by content.
Acceptance repeats both fresh-process commands offline and compares digests,
file count, bytes, sizes and mtimes. It does not claim service/Docker acceptance
or approval of a supported history threshold.
