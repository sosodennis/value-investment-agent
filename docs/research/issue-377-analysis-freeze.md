# Fixed100 analysis decision and freeze (#377)

The owner requested independent progress without waiting for the integration
chat. This records an author methods review and freezes an **exploratory
analysis**, with no claim of independent statistical/business approval. It does
not approve a supported history threshold. The v3 proposed numerical margins
are rejected as release authority; no new arbitrary margin replaces them.

## Decisions

| Question | Frozen decision and practical meaning |
| --- | --- |
| Population | Original 100 issuers, 589 targets, original decisions and first-original labels; no substitutions. |
| Target | Next annual revenue and undiscounted FCFF, separately for both formal models; no per-share valuation or investment-return claim. |
| History | Explicit 3/4/5 arms, common issuer/date/label/policy/scale comparisons; report unavailable arms and every refusal. |
| Loss | Signed/absolute/squared USD errors, MAE/RMSE; positive training-only common three-year naive scale for MASE, no epsilon or percentage fallback. |
| Baseline | Last pre-origin target; paired model-minus-naive loss, not the in-sample MASE denominator alone. |
| Accounting | Exact and conditional labels remain separate; scenarios never multiply independent issuers. Neither this analysis nor its hashes authenticate releases. |
| Uncertainty | Existing 100,000 paired issuer percentile resamples and 32-hypothesis nominal Bonferroni family; approximate, without guaranteed finite-sample coverage. |
| Precision | Report actual interval half-width and eligible counts. No prospective-power claim from achieved precision; degenerate/singleton samples do not supply zero-width precision evidence. |
| Missingness | Coverage denominator 100; actual error/common-case denominators. No MAR assumption. Unknown nonnegative losses leave an unbounded all-selected upper bound; paired contrasts are unidentified when cases are missing. |
| Prior inspection | NEWMARKET conditional outcomes were already seen. This is not retrospective preregistration. Subsequent method changes must disclose inspected outcomes and retain prior methods. |
| Promotion | Disabled. The legacy 100-complete-pair gate remains unchanged; at most 90 eligible labels makes it infeasible. No 3/4/5 threshold is approved. |

This completes the executable analysis-definition decision. It leaves the
confirmatory/business-policy part of #377 open. A narrow interval on usable
issuers cannot establish adequate accuracy for all selected issuers, historical
classifications or full valuation. Failure to execute forecasts because of
engineering/mapping gaps is not an empirical underpowered conclusion.

## Why the proposed limits are not approved

MASE 1 is interpretable relative to pre-origin target variation; it does not by
itself prove superiority to the OOS naive forecast. A 0.10-MASE difference is a
unit of training variability, not a 10% valuation or investor-loss tolerance.
No identified business decision or external standard establishes the proposed
0.10 noninferiority/precision margins. The known-SD planning grid is useful
sensitivity analysis, not evidence that the actual loss SD is a favorable row.

The retained percentile bootstrap is useful for descriptive calibration; its
extreme Bonferroni tails, heavy-tail sensitivity and sparse common sample make
it insufficient by itself for release authorization. Do not improve an apparent
result by clipping losses, changing the target, selecting an allocation scenario,
changing the hypothesis family or omitting missing cases after inspection.
Alternative inferential methods need a separately versioned protocol, simulation
calibration and an explicit claim; they cannot retrospectively certify this run.

Practical next use: acquire and adjudicate real source observations, execute all
fixed cases, publish raw/conditional/exact denominators and achieved precision.
That provides evidence for a future useful claim and a prospective validation
design, while `supported_history_threshold` stays null. A future promotion
contract must define the business loss tolerance, authenticated primary input
policy, independent authority, missingness/generalization scope and justified
sample/precision replacement for the impossible legacy gate. It cannot borrow
this research-only freeze as approval.

## External calibration

The references support methods, not numerical business tolerances:

- [Hyndman forecast accuracy](https://github.com/robjhyndman/fpp3_slides/blob/5db37d7198d34267bd098d65179390cae75e0d80/5-8-evaluating_point.Rmd): out-of-sample error, MAPE limitations and training-only scale.
- [Hyndman rolling origins](https://github.com/robjhyndman/fpp3_slides/blob/5db37d7198d34267bd098d65179390cae75e0d80/5-10-tscv.Rmd): time ordering and information availability.
- [NIST confidence limits for a mean](https://www.itl.nist.gov/div898/handbook/eda/section3/eda352.htm): interval width depends on sample size and variability; confidence is a repeated-sampling property of the method. Retrieved source SHA-256 `0050ef3a18803d08a1ae68a655e587372e1baf31fed020bb253fc7d053792291`.
- [SciPy bootstrap](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html): paired resampling, interval method choice and degenerate data limitations. Retrieved source SHA-256 `681a10622e6fa1520fea015ed884e53272ca26d8be1029ab536059d926a52477`.

Reference bytes are retained outside Git. The direct OTexts requests failed TLS
and SEC's generic accounting-release PDF returned HTTP 403; neither failed
request is evidence of a financial value or a reviewed margin. Pinned original
issuer filings remain the only accounting ground-truth candidates.

## Reproduce the freeze

`scripts/freeze_history_analysis.py` requires an exact clean commit and canonical
committed freeze bytes (canonical JSON plus one terminal LF). It checks every pinned v3/v4 method/tool dependency before
publishing an immutable report with commit/runtime/input/output identities.
Repetition reuses the same artifact with `wrote=false`. No network, trust change,
source acquisition, signing, model execution or financial arithmetic occurs.

```sh
python3 -B scripts/freeze_history_analysis.py \
  --freeze docs/research/issue-377-analysis-freeze-v1.json \
  --freeze-digest <sha256-of-canonical-freeze> \
  --exact-commit <full-tested-commit> \
  --output-directory /absolute/external/evidence/method-freeze
```

The JSON manifest freezes operational methods and their authority boundary.
Editing a dependency invalidates verification until a new version and reviewed
decision records the change. Earlier exploratory artifacts remain immutable.
