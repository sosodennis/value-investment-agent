# Fixed-100 history sufficiency study (#376)

[Issue #376](https://github.com/sosodennis/value-investment-agent/issues/376)
continues the empirical study removed from #361 / PR #370. It does not change
the persistent valuation delivery scope or authorize a history threshold.
Generated inputs, findings, forecasts, labels and reports belong outside Git.
Keep only code, small regression fixtures, protocols and digest references here.

## Immutable starting evidence

| Item | Pin |
| --- | --- |
| Archived baseline commit | `59830e161c9300e44b2b7b54eea3e43567835bff` |
| Evidence tar SHA-256 | `921937cbcf490aee8893fd343835d234eec1e48514108cf33ca88e6b11eea037` |
| Manifest SHA-256 | `e33675f8b19f46dbf8a742c8d8d037d261361140c2c447b46aff977ee2a17388` |
| Full-history bundle SHA-256 | `d27238c031cbbbd79b90c114e4fb46b8f199a3d9245d0685e33c0a7435eca11c` |
| Pre-cleanup detailed evidence commit | `32be2dafbbc7756bf185e228dc8fdcc280fe6cf3` |
| Fixed original-source checkpoint | `066b9d02ee2d855dbc3ebf688c97b571ea709401f8dff4795d48023ea2147d4f` |

The manifest lists 10,358 compressed files. Detailed results removed from the
final baseline tree remain in the full-history bundle. Restore that bundle into
a separate temporary Git repository; do not check out or reset the active #361
branch. The audit verifies 823 referenced documents, including chunked content,
589 original filing outcomes and their input/output digests. The sampling
protocol remains `docs/acceptance/issue-359-cohort-protocol-v1.json`.

## Reproduce the diagnostic audits

Use Python and the locked Fundamental dependencies. Record exact HEAD,
interpreter/library versions, commands and exit codes alongside external
receipts. These commands do not call SEC, publish snapshots or invoke forecasts.
Use the archive located by #361's research archive index as `STUDY_ARCHIVE`.
Every directory below must be outside the checkout.

```sh
uv run --frozen --project fundamental-service python scripts/verify_issue361_research_archive.py \
  --archive "$STUDY_ARCHIVE/research-evidence.tar.gz" \
  --manifest "$STUDY_ARCHIVE/manifest.json" \
  --destination "$STUDY_INPUTS" \
  --expected-archive-sha256 921937cbcf490aee8893fd343835d234eec1e48514108cf33ca88e6b11eea037 \
  --expected-manifest-sha256 e33675f8b19f46dbf8a742c8d8d037d261361140c2c447b46aff977ee2a17388 \
  --expected-source-commit 59830e161c9300e44b2b7b54eea3e43567835bff

uv run --frozen --project fundamental-service python scripts/audit_history_dqc_applicability.py \
  --evidence-root "$STUDY_INPUTS" \
  --archive-repository "$STUDY_BUNDLE_READER" \
  --archive-commit 32be2dafbbc7756bf185e228dc8fdcc280fe6cf3 \
  --guidance-html "$STUDY_GUIDANCE" \
  --guidance-sha256 db05fc014b19be8d70a84ceb95730c6d55bc319c5f3b5f7bd4bbad60902e0553 \
  --output-directory "$STUDY_DQC_OUTPUT"

uv run --frozen --project fundamental-service python scripts/audit_history_source_integrity.py \
  --failure-report "$STUDY_FAILURE_REPORT" \
  --failure-report-sha256 "$STUDY_FAILURE_DIGEST" \
  --content-root "$STUDY_SOURCE_CONTENT" \
  --c14n-reference "$STUDY_C14N_REFERENCE" \
  --output-directory "$STUDY_SOURCE_OUTPUT"
```

The failure report is the preceding DQC audit's canonical JSON output. The
source-content directory contains the retained SEC objects, addressed by SHA-256.
Read-only access to existing objects is sufficient; no database or running
container is required. Missing or corrupt objects remain unresolved. Do not
redownload unchanged sources to run these audits.

The dated official guidance snapshot has SHA-256
`db05fc014b19be8d70a84ceb95730c6d55bc319c5f3b5f7bd4bbad60902e0553`.
The W3C C14N reference has SHA-256
`09c02ef3bc0f8364b00b16fb06092637c08e8f38cf223d47a5862eacc2956bc0`.
Retain those exact downloaded bytes externally; a changed live page requires a
new input digest. The report writers use canonical JSON, content addresses and
temporary files with atomic rename. Identical existing reports return
`wrote=false` without replacing the file. A corrupt existing report fails.
Archive restoration likewise reuses an identical destination and rejects a
changed, incomplete or unrelated destination.

## What the retained failures establish

The audit preserves all 100 issuers and all 589 filing outcomes: 74 passed source
validation without publication; 230 parser refusals; 187 source size refusals;
59 unsupported taxonomies; 37 unresolved entrypoints; one unavailable DQC
validation; and one invalid payload.

Of the 230 parser refusals, 95 have only pre-effective blocking DQC findings:
84 history filings, nine decisions and two labels. The official
[DQC guidance](https://xbrl.us/data-quality/rules-guidance/) says to use rules
informationally before their effective dates and not assess DQC compliance for
earlier filings. This supports historical applicability review. Family dates
alone do not certify the exact pinned revision. Every finding retains its
original severity and blocking flag; financial materiality remains unadjudicated.

Among the 187 source size refusals, 55 have equal inclusive Canonical XML 1.0
without comments; 132 differ. The
[W3C recommendation](https://www.w3.org/TR/2001/REC-xml-c14n-20010315)
normalizes XML representation while retaining character content and whitespace.
The probe rejects DTDs, non-XML-1.0 documents and non-XBRL roots. It does not
approve differing documents, regulatory validation, mappings or releases.
An archive-first source profile is a design candidate requiring its own
provenance and validation contract; this audit does not implement or authorize it.

## Research protocol gap (#377)

There are nine missing first-original labels and one 731-day horizon mismatch.
Consequently, the fixed cohort has at most 90 complete eligible label pairs.
The archived replay's `HistoryEvidenceProtocolV1` requires 100 complete
independent issuers, groups by observed history length, and has no approved
promotion policy. Its descriptive output cannot choose a supported history
length. [Blocker #377](https://github.com/sosodennis/value-investment-agent/issues/377)
owns this design gap. The original Wilson design concerned coverage across the 100 selected
issuers; it does not establish precision for forecast error among usable pairs.

The next version must preserve the original sample and dates, report coverage
against all selected issuers, and distinguish this from the paired-error
denominator. Compare trailing three-, four- and five-period inputs within the
same issuer/date using the formal #352 composer. Preserve any composer refusal
of a shorter history; do not change its formula or minimum to obtain a score.
Apply identical mappings, model/policy versions, labels and training-only error
scales across the comparison. Any additional rolling origins require an
explicit frozen manifest; one origin per issuer is not a longitudinal study.

Hyndman's pinned teaching sources describe
[rolling forecasting origins](https://github.com/robjhyndman/fpp3_slides/blob/5db37d7198d34267bd098d65179390cae75e0d80/5-10-tscv.Rmd)
and [out-of-sample accuracy](https://github.com/robjhyndman/fpp3_slides/blob/5db37d7198d34267bd098d65179390cae75e0d80/5-8-evaluating_point.Rmd).
The latter warns against MAPE when outcomes are not well above zero. For FCFF,
retain MAE/RMSE in original units and use a declared training-only scaled loss;
retain zero-scale cases as unscorable rather than dropping them silently.
Aggregate uncertainty by independent issuer, not filing count. Exact interval,
accuracy tolerance, selection/multiplicity and power criteria must be reviewed
and frozen before forecast outcomes are used for threshold selection. This
document proposes the design; it does not invent an approved numerical tolerance.

## Completion boundary

These diagnostics establish actionable compatibility and protocol gaps. They
are not empirical forecast-error results. #369 historical market evidence,
#371 historical validation, issuer/period/accounting-era mapping review and
trusted release creation still precede the formal forecast/label replay.
Project signatures prove document integrity; they do not supply semantic review.
Do not approve a threshold, label a valuation verified, close #376 or present
zero executed forecasts as a completed history-sufficiency study.
