# Fixed-cohort operating forecast study proposal (#377)

Status: **proposal requiring review**, before any real study forecast/label error.
This records the proposal's original state. Subsequently inspected NEWMARKET
conditional outcomes are exploratory; see the
[v4 executable methods](issue-377-executable-methods.md). They do not retroactively
make v3 or v4 an approved prospective study.
The numerical choices below are proposed research claims, not approved policy.
The [machine-readable proposal](issue-377-protocol-proposal-v3.json) cannot enable
promotion. `supported_history_threshold` remains null. No complete real issuer
result, financial classification or trusted release is supplied by this document.

## Population and target claim

Retain all 100 selected issuers, 589 original filing targets and original 2016
decision dates. The fixed-manifest digest is
`448f496b10e51a2ed351a7a37deb36e0d4b9672c1fbc5ed3b0b845c8cd54da3a`;
original-source checkpoint
`066b9d02ee2d855dbc3ebf688c97b571ea709401f8dff4795d48023ea2147d4f`.
Nine missing first-original annual labels and one 731-day horizon mismatch leave
at most 90 eligible label pairs. Additional mapping or release failures can
reduce that number. Do not replace issuers, labels, dates or failing histories.

The proposed claim concerns next-annual revenue and undiscounted FCFF for
`fcff_dcf` and `transition_fcff_dcf`, using authenticated Fundamental releases
and the formal #352 composer. It does not measure intrinsic/per-share value,
investment returns, omitted accounting roles, all future issuers or optimal
history beyond five years. A supported threshold must identify model, target
scope, input-estimation policy, mapping/model/composer/policy versions and study
protocol digest. It must not promote all provisional valuations to verified.

Keep estimated accounting inputs and estimated FCFF labels visible. An estimated
label measures agreement under that estimation policy, not error against an
observed exact accounting target. Never pool exact and estimated FCFF labels as
one ground-truth population or use a signature to remove this distinction.
Unknown quantities remain unknown. Any new estimation scope requires a separate
reviewed version before it can change the study claim.

Freeze one primary input-estimation policy per model/target before viewing
outcomes. Other policy analyses remain secondary. Searching policies for a
favorable result would require a larger prespecified family; the 32-hypothesis
proposal does not authorize it.

## Common cases, labels and losses

Use the existing explicit-history-window operation for exactly three, four and
five complete trailing years. Compare arms on the same issuer, decision date,
model, original label and mapping/input policy. Retain the all-selected coverage
denominator of 100 separately from per-arm and common-pair error denominators.
Report each unavailable arm and why it abstained. The common-five-year comparison
does not establish performance in issuers having only three available years.

Select the first eligible subsequent original annual filing under the unchanged
frozen horizon policy. Do not use later restatements or subsequent originals to
fill an origin input. Preserve accession, availability, period, unit, scope,
amendment, fact ID, original hash, mapping and release identity on both sides.

Report signed/absolute/squared USD errors, MAE and RMSE. For comparison across
issuers, use MASE only when its training scale is positive. For each target,
compute the scale from mean absolute one-step naive differences over the same
three complete pre-origin annual target values for all history arms. The naive
forecast holds the latest observed pre-origin target constant. Use the existing
Fundamental accounting target construction for FCFF; the study runner must not
implement another FCFF formula. A target needing an earlier working-capital
boundary must have that evidence as well.

Zero/missing scales retain raw errors and coverage, with an explicit unscorable
scaled-loss reason. No epsilon, absolute-actual percentage, cross-issuer scale or
silent training-window substitution is permitted. MAPE is not a decision metric.
Give each independent issuer equal weight. Extra filings or additional origins
cannot increase the independent issuer count. Extra origins require a separate
prospectively frozen manifest and issuer-cluster aggregation.

## Proposed numerical criteria for review

These choices make the proposed claim reviewable. They are not dictated by
Hyndman, a regulator, the current software minimum or observed cohort errors.

| Proposed requirement | Limit and meaning |
| --- | --- |
| Absolute scaled accuracy | Simultaneous upper bound for mean MASE at most 1.00: average error below one unit of pre-origin naive target variability |
| OOS baseline improvement | Simultaneous upper bound for mean paired model-minus-naive scaled absolute error below 0.00 |
| Shorter vs five years | Simultaneous upper bound for mean paired shorter-minus-five scaled loss at most 0.10 MASE; assess three-vs-five and four-vs-five |
| Achieved precision | Simultaneous interval half-width at most 0.10 MASE for every required mean/contrast |
| Prospective planning power | 80% at a prespecified 0.10-MASE difference or separation from the noninferiority boundary, under a justified pre-outcome variance assumption |

The 0.10 margin means one tenth of the issuer's training naive variability; it
does not mean 10% of enterprise value, revenue or investment loss. A reviewer
must decide whether that claim is useful. Failure to establish superiority to
the OOS naive forecast cannot be described as proof of adequate accuracy.

There are **32 hypotheses** in one joint family: 12 mean-MASE limits (two models,
two targets, three arms), 12 paired OOS naive comparisons and eight shorter-vs-five
contrasts. Propose familywise alpha 0.05 with two-sided Bonferroni intervals.
The final paired-by-issuer interval implementation, deterministic resampling
algorithm, runtime, finite-sample limitations and missingness sensitivity must
be pinned and reviewed before execution. A bootstrap seed must derive from the
approved protocol and sorted input digests, never a run ID or wall clock.

Choose a history only when every required gate for its declared scope passes.
If three years fails, four can qualify only on its own prespecified gates; five
still needs the accuracy, baseline and precision gates. No arm receives a
threshold because it is the longest available. Missingness/coverage review and
the independent sample gate remain separate requirements. Analysis conditional
on usable pairs cannot assume that missing issuers are missing at random or
claim a survival-free population effect from successful cases alone.

## What 90 pairs can support

The original hard requirement of 100 complete independent issuers is infeasible
with this inventory, regardless of forecast accuracy. This proposal does **not**
lower it. A reviewed replacement must tie its sample requirement to the intended
precision/power claim, preserving all 100 issuers in coverage. An observed narrow
interval is achieved precision, not retrospective evidence of prospective power.

`scripts/plan_history_study_precision.py` calculates a planning grid using known-SD
normal approximations. For family size `m`, critical value
`z = Phi^-1(1 - alpha/(2m))`, assumed SD `s`, half-width `h`, target difference
`d` and target power `p`, it reports:

```text
precision n = ceil((z * s / h)^2)
power n = ceil(((z + Phi^-1(p)) * s / d)^2)
```

These are per-hypothesis marginal-power planning approximations. They do not
guarantee 80% power for all 32 gates jointly, apply an unknown-SD t correction,
account for heavy tails, or prove a bootstrap's coverage. The simultaneous
intervals are conservative. A reviewed final design must address these limits.
The grid's SDs are hypothetical, with no selected or empirically estimated SD.

| Assumed SD in MASE units | Precision pairs | Power pairs | Maximum requirement | Within 90 under assumption? |
| --- | ---: | ---: | ---: | --- |
| 0.10 | 11 | 17 | 17 | Yes |
| 0.25 | 63 | 101 | 101 | No |
| 0.50 | 251 | 401 | 401 | No |
| 1.00 | 1,001 | 1,604 | 1,604 | No |
| 2.00 | 4,002 | 6,415 | 6,415 | No |

This demonstrates sensitivity to a design assumption. It does not establish
that actual errors have any of these SDs, that the study will be powered, or that
more historical periods or filings create more independent issuers. A justified
pre-outcome variance choice or an explicitly reviewed precision-based design
remains unresolved. Do not select a favorable row after viewing cohort outcomes.

## Reproduce and review

From a clean exact commit, run the following command twice, with the same locked
Python runtime and external report directory. Substitute the literal commit
being tested; generated results never belong in Git.

```sh
python3 -B scripts/plan_history_study_precision.py \
  --proposal docs/research/issue-377-protocol-proposal-v3.json \
  --exact-commit <full-implementation-commit> \
  --output-directory /absolute/external/evidence/issue377-precision
```

Reports bind exact commit, proposal bytes/canonical digest, script digest and
runtime. They retain input/output digests and contain no time/random identity.
Matching existing reports return `wrote=false` without replacing their bytes or
mtime. Scoped publication locking and temporary-file/atomic-rename writes protect
concurrent repeats; corrupt existing content fails. No network, SEC parsing,
mapping signing, snapshot publication or service resources are involved.

Before a real study may select a threshold, review the proposed tolerances,
replacement for the infeasible legacy gate, inference/missingness method and
exact execution versions. Bind that approval to the final protocol digest.
This author-produced proposal cannot approve itself. Complete NEWMARKET's
source-bound release and real forecast/label/error/repeat, then execute the
unchanged cohort with failures and exact-repeat evidence. #376/#377 remain open.

Methodology references: Hyndman's pinned
[point forecast accuracy](https://github.com/robjhyndman/fpp3_slides/blob/5db37d7198d34267bd098d65179390cae75e0d80/5-8-evaluating_point.Rmd)
and [rolling origins](https://github.com/robjhyndman/fpp3_slides/blob/5db37d7198d34267bd098d65179390cae75e0d80/5-10-tscv.Rmd).
The retained source hashes are in the JSON proposal. These sources support
training-only scales and out-of-sample design, not the proposed numerical limits.
