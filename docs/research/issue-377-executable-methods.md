# Executable history comparison methods (#377)

The [v4 methods](issue-377-methods-v4.json) pin the statistical implementation
missing from the [v3 design proposal](issue-377-operating-study-proposal.md).
They support **exploratory method validation** and cannot approve a threshold.
NEWMARKET conditional outcomes were inspected before v4. They are exploratory;
this change is not retrospective preregistration. Exact cohort accuracy remains
unmeasured. The original 100 issuers, 589 targets, decision dates, nine missing
labels and one horizon mismatch remain fixed.

## What the command does

`scripts/analyze_history_study.py` reads the hash-verified original manifest and
a loss panel containing all 100 issuers and all 12 model/target/history cells per
issuer. Each issuer/date appears once. Each cell declares its source evidence,
policy, label quality and a scored, missing or abstained disposition. Three,
four and five years are explicit arms; shortage cannot become a shorter forecast.

The tool reports raw errors and coverage per arm, positive training-scale counts,
and comparisons on the same complete three-arm issuer set. For every model and
target it reports three mean MASEs, three paired model-minus-naive losses and
two shorter-minus-five contrasts. Together these form the original 32-hypothesis
family. No financial calculation or FCFF formula is implemented here. The
upstream authenticated Fundamental path and #352 composer own forecast and
target construction.

An input comparison key binds issuer, origin, first-original label, source,
mapping, executable model/composer/numerical policy and input policy versions.
The common key excludes the history arm's forecast digest, which belongs in
that cell's separate `evidence_digests`. The three arms must have the same scale,
naive error and label quality. One input policy per model/target is allowed
across the panel; this prevents silently pooling policy searches. These are
structural checks of declarations. **Hashes and this offline tool do not
authenticate a release, review an accounting judgment or verify loss arithmetic.**
An authenticated panel generator and its source-level audit remain required.

The JSON contract requires these fields; no field is optional:

| Object | Fields |
| --- | --- |
| Panel | `schema_version=history-study-loss-panel.v1`, `analysis_scope=exploratory_method_validation`, `fixed_manifest_digest`, `cases` |
| Case | `issuer_id`, `decision_at`, `observations` |
| Observation | `model`, `target`, `years`, `status`, `label_kind`, `input_policy`, `comparison_key`, `signed_error`, `naive_absolute_error`, `scale`, `reasons`, `evidence_digests` |

Sort cases by issuer/origin and cells by model/target/year. Numeric observations
are decimal strings in USD; signed error is forecast minus target. Missing and
abstained cells have null numeric values and explicit reasons. Scored cells
require a nonnegative naive absolute error and a nonnegative or missing scale.
The scale uses only the same three pre-origin annual target values. Zero or
missing scale retains raw errors and becomes unscorable for scaled loss. An
unavailable or mismatched frozen first-original label cannot carry scored loss.
Conditional labels remain visible and are excluded from exact-study statistics.
There is no selected-scenario averaging or multiplication of independent samples.

## Pinned inference and its limits

Resample whole issuer vectors with equal weights, preserving all arm and naive
comparisons together. Use 100,000 replicates, CPython's integer-seeded
`random.Random`/`randrange`, `math.fsum`, and linear percentile interpolation at
`(B-1)*p`. The deterministic seed binds canonical protocol and complete panel
digests, model, target and ordered common issuer IDs. Runtime version,
implementation, architecture and OS are report inputs. Different runtime pins
are different executions.

Nominal two-sided Bonferroni tails are `0.05/(2*32)`. Report half-width as the
larger distance from the mean to either endpoint. Fewer than two independent
issuers produces no interval. A constant empirical component produces an
explicit degeneracy refusal, not a zero-width precision claim. No outcome or
user-controlled run seed can tune the resamples.

The percentile bootstrap is an approximate exploratory method. Bonferroni
correction cannot repair inaccurate marginal intervals. Heavy tails, small
samples, Monte Carlo tails and unverified exchangeability can invalidate nominal
coverage. These are not finite-sample guarantees or measured prospective power.
An independent review must establish interval adequacy for a confirmatory scope;
changing the algorithm creates a new version and cannot silently replace v4.
The independently enumerated four-sample unit test checks the implementation
against exact arithmetic, rather than calling the implementation twice.

Keep all-selected coverage denominator 100 separate from per-arm raw,
per-arm scaled and common-pair denominators. No missing-at-random assumption or
current survival data is used. With missing issuers and no defensible upper
bound on loss, the all-selected nonnegative mean has lower identification bound
`sum(observed common losses)/100` and unbounded upper side; paired contrasts have
both sides unbounded. These are identification bounds, not confidence intervals.
Complete-case bootstrap intervals do not solve this missingness problem or
establish adequacy for issuers having only three years available.

## Run and replay

Use a clean exact commit and the same pinned runtime for both commands:

```sh
python3 -B scripts/analyze_history_study.py \
  --protocol docs/research/issue-377-methods-v4.json \
  --manifest /absolute/external/fixed100-manifest.json \
  --panel /absolute/external/source-bound-loss-panel.json \
  --exact-commit <literal-full-implementation-SHA> \
  --output-directory /absolute/external/issue377-results
```

Missing inputs fail; frozen replay does not fetch replacement SEC data. Reports
bind commit, manifest, panel, protocol, analysis/publication source and runtime.
Canonical publication uses the existing external-only lock plus temporary file
and atomic rename. An identical report returns `wrote=false`, retaining bytes,
size and mtime; corrupt existing artifacts fail. Historical documents, panels,
downloaded methods sources and complete generated reports remain outside Git.

## Decision still required before a threshold study

The [cost-aware evidence calibration](issue-377-cost-aware-evidence.md) describes
practical acquisition alternatives and external method limits. Conditional
adapter delivery can proceed through independent review while exact accounting
evidence remains incomplete. It changes none of the v4 methods or gates.

The legacy 100-complete-issuer gate is infeasible with at most 90 original labels.
This implementation preserves it and reports underpowered. A concrete candidate
for independent review is a precision-based design limited to the fixed eligible
common subset: require the reviewed simultaneous half-width, accuracy, baseline
and history noninferiority gates instead of choosing an arbitrary smaller sample
count. It would make no all-100, three-year-only-issuer or prospective-power
claim. That would be a versioned replacement of the old gate, not a passing
result under the original acceptance. It has **not** been adopted here.

Review must justify the v3 business margins, primary accounting-input policies,
population scope, missingness treatment and finite-sample method. It must approve
any replacement for the legacy gate explicitly, bind approval to final digests,
and distinguish outcomes already seen from confirmatory evidence. Without that
review and real authenticated #352 outcomes, this tool always reports
`promotion_enabled=false` and `supported_history_threshold=null`. Neither a
signature nor successful synthetic tests can satisfy those requirements.

Method references: [SciPy bootstrap documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html)
supports paired resampling, percentile definitions and degeneracy limitations;
[Hyndman's accuracy slides](https://github.com/robjhyndman/fpp3_slides/blob/5db37d7198d34267bd098d65179390cae75e0d80/5-8-evaluating_point.Rmd)
support training-only scales and MAPE cautions. Their retained hashes are in v4.
They do not approve the project's numerical tolerances or guarantee coverage.
