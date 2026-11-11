# #361 persistent source preparation and valuation flow

## Accepted outcome

[#361](https://github.com/sosodennis/value-investment-agent/issues/361) owns the
Fundamental Service flow from company and valuation timestamp to a persisted,
retrievable numerical valuation. [PR #370](https://github.com/sosodennis/value-investment-agent/pull/370)
remains open and draft. No complete real numerical acceptance is claimed.

The flow reuses eligible evidence, acquires missing SEC originals, persists facts
and snapshots, prepares through the formal #352 composer, accepts authentic
caller approval of the exact input digest, and invokes the existing calculator.
PostgreSQL stores metadata. The service content volume stores immutable bytes.

The owner revised this scope on 2026-11-11. The fixed 100-issuer threshold study
belongs to #376 and draft PR #378. Its generated corpus is outside this PR and
is not a hidden runtime dependency. `supported_history_threshold` remains null.
Eligible candidate-history valuations can be provisional. Missing, conflicting,
unreviewed, future, or unsupported evidence must retain reasons and abstain.
No completed #351 through #355 acceptance is changed. #350 is outside scope.

## Current implementation and verification

The implementation commit is `01b091f82096711cb6c07a6f59fe9f8e847082e1`.
The previous acceptance checkpoint is `a179e4c6c989fdaccd2774b49d39b0ea16a7a88b`.
Fetched `origin/main`, `52e84dfe5a0dae0c11d2e62fd9a58e885b6eadc9`, is already an
ancestor. A normal `git merge --no-edit origin/main` reports `Already up to date.`
The WIP and checkpoint chain remains intact.

At the exact implementation commit, 1,118 service and PostgreSQL tests, 52 Agent
boundary tests, and 17 acceptance-tool tests pass. Eleven optional runtime tests
skip. Ruff, formatting, mypy, architecture, and diff checks pass.
[Implementation CI](https://github.com/sosodennis/value-investment-agent/actions/runs/43088113783)
and [checkpoint CI](https://github.com/sosodennis/value-investment-agent/actions/runs/43089498737)
each pass all 12 executed jobs. The release job skips.

The implementation provides retained SEC acquisition, original-bound parser and
archive integrity, multi-original history composition, accounting-role evidence,
source preparation, exact-input approval checks, immutable result retrieval,
concurrent deduplication, and digest-checked export and restore. Synthetic
populated and explicit empty award inventories pass signed canary, formal
preparation, numerical calculation, unchanged repeats, PostgreSQL restart, and
restore into an empty store. An explicit empty inventory still needs complete
original coverage and cannot hide released award observations.

Exact documentation commit `d29d1298ac4018a8cf891b391241c0fda0d1565f` passes
17 acceptance-tool tests, architecture, diff, and prior-checkpoint preservation.
Its CI `contract-policy` job detects a negated closing-keyword sentence in the
old PR body. The current body states that #361 remains OPEN. The actual policy
reproduces the old failure and passes with the corrected body. No validator,
WIP/draft status, runtime manifest, or financial gate is changed. The checkpoint
entry `source_review_ci_description_correction` retains both command results.
The new head still requires CI verification.

These engineering results do not establish a reviewed real issuer valuation.
The [runtime manifest](issue-361-runtime.json) remains WIP, stopped, not ready,
and requires revalidation. Its 19 full-flow checks remain unverified. Earlier
installed-service evidence belongs to the exact commits in its checkpoints.
It must not be presented as current complete numerical acceptance.

## Real evidence and remaining source decisions

### Tandy original-filing case

CIK `0000909724`, security TLF, cutoff `2025-04-01T00:00:00Z`.
Originals `0001140361-24-014799` and `0001140361-25-006103` retain 722 and 714
formally parsed facts. The source audit has 21 of 31 scalar roles with candidate
mappings and 86 provisional facts. No actual mapping has been approved.

The following gaps remain capable of changing the result:

- The accrued-liability table and rounded deferred-order disclosure do not
  establish a complete nonoverlapping accrued/deferred partition. The property
  earnest-money deposit is not automatically an operating liability. Vendor
  payables must not also enter accrued operating liabilities.
- The 409,000 combined restricted-stock/RSU quantity and 322,000 unrecognized
  compensation use different original award members. Already-issued restricted
  stock cannot be counted again as unissued units. Seven supplemental original
  contracts preserve the stock/RSU distinction and a conflicting incorporation
  description; they do not supply a complete period-end inventory.
- Contract assets, complete debt/claim scope, preferred claims, NCI, convertibles,
  and other share classes still need source-supported classification or actual
  confirmed absence. Missing tags cannot establish zero.
- The retained Yahoo daily close is an unreviewed observation. Identity,
  currency, publication time, freshness, source rights, and quote policy remain
  unresolved. No current quote metadata or adjusted close is selected.

The earlier real provisional evidence passes the persistence and recovery checks
recorded under `history_archive_integrity_increment` and
`lease_expense_classification_increment`. Their complete repeat bundles preserve
source bytes, provenance, hashes, and mtimes. They do not satisfy numerical flow
acceptance or financial approval.

### Additional source sufficiency check

At exact source-review commit `a179e4c6c989fdaccd2774b49d39b0ea16a7a88b`, a separate
United-Guardian case retains originals `0001171843-24-001526` and
`0001171843-25-001611`, accepted before the same cutoff. This is an additional
service case, not a replacement for any #376 issuer.

Both originals disclose unconverted Guardian Chemical shares that could convert
to approximately 447 common shares, with dividends accruing on those shares.
A short balance sheet without a convertible-debt row does not prove absence of
other conversion claims. Their inclusion in reported common shares and their
classification remain unresolved. Raw HTML discovery is not a formal parser
report, canonical mapping, zero claim, complete empty award inventory, or
numerical acceptance. This case remains retained and unresolved.

### Dated market-input proposal

The source-review packet follows the publisher's retained archive index. Its
`1/25` links point to `betas24.xls` and `ctryprem24.xlsx`. Guessed year-based
filenames returned 404; those failed responses remain retained.

| Role | Candidate source value | Evidence and unresolved decision |
| --- | --- | --- |
| Risk-free rate | 4.23% | Treasury `BC_10YEAR`, 2025-03-31. Publication, revisions, and freshness need review. Future rows in the downloaded annual feed are not selected. |
| Industry beta | 1.0024856714394297 | January 2025 U.S. workbook, `Industry Averages!F86`, Retail (Special Lines). The issuer-aware industry selection and definition need review. |
| U.S. ERP | 4.33% | January 2025 workbook, `ERPs by country!E159`. Raw XML decimal, cached double, and display format are retained. |
| Normalized tax | 25% proposal | `Country Tax Rates!B154` is a U.S. reference assumption. It does not establish Tandy's international normalized tax mix. |
| Marginal debt cost | unresolved | Original facility specifies CME term SOFR plus 210 bp. No tenor, benchmark value, or fixed borrowing rate is invented. |
| Market capitalization | unresolved | Requires admitted dated quote and reviewed point-in-time shares. The formal service retains the calculation. |
| Terminal growth | unresolved | The ALFRED GDP vintage request timed out. No current-vintage substitute or unbounded terminal assumption is admitted. |

Workbook update dates, archive labels, and retrieval timestamps remain separate.
The proposal does not invent exact historical availability or legal-use approval.
It creates no `ApprovedMarketPolicyInputsV1`, release, signature, caller approval,
or duplicate WACC/forecast formula. Source transcription is evidence for review.

Two independent complete repeats of the five source-review commands preserve all
46 files' hashes and mtimes, with zero provider or parser calls and no new source
artifacts. Each command reports `wrote=false`; input/output digests and ordering
match. Running the repeat verifier again also reuses its report. Source-repeat
input is `2a9919f800d4c19a3715f259ad23f3c1ea87131d688fbcc93258b058549de36f`;
output is `e4294189f10c8b3bed895eaa1da400493b1de2fb85cb74373bb01ad0e30c2034`.
This verifies source-review reuse, not the complete valuation flow.

## Completion gates

All of the following remain required before #361 is complete:

1. One supported real original-filing case completes acquisition and reuse,
   facts/snapshot persistence, actual independent semantic review, trusted
   release, formal #352 prepare, authentic exact-input caller approval,
   numerical calculation, and API artifact retrieval.
2. The complete flow repeats without new downloads, snapshots, artifacts, or
   domain rows and with identical input/output digests. Concurrent deduplication
   passes. Operational access audits remain distinct from domain identity.
3. The same store survives restart. Export and restore into a separate empty
   store preserve evidence, results, provenance, and repeat digests.
4. Failure retention covers missing/conflicting/future facts, unknown amendments,
   invalid mappings/sources, corruption, missing review, and invalid approval.
5. Exact-commit mapping, forecast, label/history where applicable, preparation,
   calculation, persistence, deterministic replay, and refusal tests pass with
   architecture, Ruff, type checks, contracts, and `git diff --check`.
6. The isolated `persistent-valuation-flow-v1` service tuple passes all 19 gates
   with exact image/source/runtime pins, commands, exit codes, and digests.
7. Independent PR review and required CI pass. Merge PR #370, verify its merge
   commit on main, close #361 and completed dependencies, then clean only
   issue-owned resources with retained backups.

The reviewer must differ from the mapping author under the
[canonical review contract](../../fundamental-service/docs/fundamental-enterprise-grade-target-state.md#259-assumptions-and-open-decisions).
The [project signer](../../fundamental-service/docs/operations-runbook.md) signs an
actual supplied review using an existing trusted key. It cannot supply semantic
review, missing facts, financial policy, or caller approval.

## Evidence, runtime, and preserved history

[The accounting checkpoint](issue-361-accounting-checkpoint.json) preserves every
previous top-level entry. Its newest entry,
`dated_market_source_review_increment`, records source hashes, proposal and
repeat digests, exact commands, retained failures, unverified gates, and next
steps. The preceding implementation entry is
`explicit_empty_award_inventory_increment`.

Earlier evidence remains in the
[scope](issue-361-scope-checkpoint.json),
[preparation](issue-361-preparation-checkpoint.json),
[history](issue-361-history-checkpoint.json),
[source-plan](issue-361-source-plan-checkpoint.json), and
[recovery](issue-361-recovery-checkpoint.json) checkpoints. The previous cumulative
acceptance narrative remains in
[Git at a179e4c6](https://github.com/sosodennis/value-investment-agent/blob/a179e4c6c989fdaccd2774b49d39b0ea16a7a88b/docs/acceptance/issue-361-acceptance.md).
This document consolidates current status without deleting that evidence.
The [research archive reference](issue-361-research-archive.json) preserves the
removed corpus and pre-squash Git bundle outside the runtime and PR.

The worktree is
`/Users/denniswong/Desktop/Project/value-investment-agent-issue-361-replay-evidence`
on `codex/issue-361-replay-evidence`. The existing regression PostgreSQL project
is `value-investment-agent-361-flow-tests`, port 18665. Earlier dedicated service
projects were backed up and removed under their recorded checkpoints. This
source-review increment starts or cleans no Docker resource and claims no new
installed HTTP acceptance. Re-read and revalidate the canonical runtime tuple
before the next service acceptance run.

Generated sources, mappings, proposals, diagnostics, and backups remain in ignored
`.audit`. Do not reset, rebase, force-push, or discard the checkpoint chain. Do not
restore `.tmp-issue355-sec-useragent-compose.yml` or clean another project.
#361, unresolved blockers #369/#381/#394, and PR #370 remain open. Implemented
normalization blocker #404 still needs delivery and final verification. Complete
source scope and actual review precede numerical acceptance; thresholds stay null.
