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

## Automatic mapping approval increment (2026-11-12)

The owner replaced the pending manual mapping gate with automatic policy
approval. The new machine evidence is distinct from `MappingReviewEvidenceV1`.
It binds a trusted evaluator and executable policy digest to exact retained
inputs and decisions. The read-only release canary repeats evaluation and
reconstructs the declared facts; a valid signature with a forged decision fails.
Approved mappings are limited to issuer/accession/raw/parser/report/observation
scope. They cannot authorize a dimensional context or another original.

The service command `fundamental-approve-mapping` uses existing PostgreSQL and
immutable content persistence. Source bytes are retained without JSON encoding.
Inputs, approved decisions and abstentions are content-addressed. Identical
repeats return `wrote=false`; synthetic service tests cover process restart and
backup/empty-store restore. Existing human review signatures and canonical JSON
publication remain unchanged. The three agent architecture skills were checked;
no agent topology, workflow contract or guidance changed.

This increment does not resolve missing accounting/capital/award roles, admitted
market policy, the real numerical flow or final service/review/CI gates. The
complete goal remains open and draft. AI verification is future scope and the
history threshold remains null. Exact commit checks and real original results
are recorded in the appended checkpoint when available.

Real-source execution exposed [#407](https://github.com/sosodennis/value-investment-agent/issues/407):
the parser pins an ordered taxonomy directory digest, whereas the release had
required a single artifact blob with that digest. The owning evidence layer now
retains a deterministic taxonomy-cache archive and reproduces the original tree
digest from exact member paths and bytes. Blob/tree identities remain distinct.
Tests exercise real directory hashing, release acceptance and unsafe, duplicate,
unordered, symbolic-link, corrupt and mismatched evidence refusals.

## Current implementation and verification

The latest implementation commit is `e30d2e5068f49709c68e794dbb0be1d2c1d11a96`.
It follows script-only integrity fix `5e45f306` and type correction `60ab6278`;
all earlier WIP and checkpoint commits remain intact.
Fetched `origin/main`, `52e84dfe5a0dae0c11d2e62fd9a58e885b6eadc9`, is already an
ancestor. A normal `git merge --no-edit origin/main` reports `Already up to date.`
The WIP and checkpoint chain remains intact.

At prior implementation `01b091f8`, 1,118 service and PostgreSQL tests, 52 Agent
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
Later implementation and metadata CI runs pass; that old failure remains retained.

Prior implementation `ed733e4e` retains annual-history conflicts as explicit
abstention in the formal composer. Ten regressions fail before the correction,
including a released cross-field period mismatch returning HTTP 500. They pass
afterward. Exact-commit checks pass 1,128 Service/PostgreSQL tests, 52 Agent tests,
17 acceptance-tool tests, Ruff, formatting, types, architecture, and diff checks;
11 optional runtime checks skip. [Metadata CI](https://github.com/sosodennis/value-investment-agent/actions/runs/43099749410)
passes all 12 executed jobs; the release job skips.

An isolated synthetic service project, `value-investment-agent-361-history-conflict`
(ports 18672/18673), passes six installed HTTP checks across repeat, restart,
and empty-store restore. The runner preserves the blocked artifact. Two further
complete runner/HTTP/export/restore repeats retain the same digests, 34 file
hashes/mtimes, and database rows; runner, backup, and restore report `wrote=false`.
Repeating the verifier itself also reports `wrote=false`. Its input digest is
`08ccec1bd33dd1c947d48581e376028cd7ac65f2cb4a76582902e31c3f86a20e`;
output is `9f660b4e602770349f233d768d0f2f40952018de8ea725e683cd441fcabaf717`.
A verified backup remains outside Git. Only this temporary project was removed;
all 63 baseline containers retain their IDs, images, and start times. Synthetic
fixture signatures establish no actual financial review or caller approval.
The checkpoint entry `history_conflict_abstention_increment` records exact
commands, digests, runtime pins, retained harness failures, and source refusals.

At exact `e30d2e50`, 1,149 Service/PostgreSQL tests, 52 Agent boundary tests,
and 17 acceptance-tool tests pass. Eleven optional resource checks skip. Ruff,
formatting, 43-source mypy, architecture, and diff checks pass.
[Implementation CI](https://github.com/sosodennis/value-investment-agent/actions/runs/43104857470)
passes all 12 executed jobs; the release job skips. Check input is
`2ebf2ae905b9e795b613cc947747947bfe6471e56476e29825af26ad06a847e9`;
output is `ba8950fea532f881b748faa41c08c8b37c7c98358a0d89bdf8c994c559750185`.

The script-only integrity relation preserves the original LF when removal of
the exact terminal Akamai script reproduces every archive byte (#405). An
additional fresh-parser probe exposed official EDGAR's stale context/unit in
DQC lease warning parameters (#406). A bounded supported logging hook now uses
the warning's actual referenced sum fact. Numeric parameters, warning severity,
official rule execution and source facts remain unchanged. The adapter hash
participates in validation evidence and replay digests. Eleven new regression
cases fail before correction; focused and full suites pass after correction.

Both real NVE originals pass strict parsing, then two independent full fresh
parser repeats reproduce replay, fact, snapshot, integrity and identity evidence
digests with zero provider calls and `wrote=false`. Two retained-parser/mapping
command repeats preserve all 93 evidence files' hashes and mtimes, create no
new artifacts and make zero provider calls. The repeat verifier itself also
returns `wrote=false`. Repeat input is
`fd6d1d7429a0a8a9e6809512c68a1db3135e205179c357f3c70bb7e2564c4ce0`;
output is `79d5c5524baf36be6e92e2ba8486a76cce66dd0601cbff77a4a8234c86f9f6b4`.
These source checks use the existing regression PostgreSQL for engineering
tests, start no new Compose resources, and do not establish numerical acceptance.

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

Formal ingestion separately refuses both United-Guardian originals. The 2023
original retains 22 blocking `EFM.6.08.05.firstLetter` findings. The 2024 original
retains the same 22 naming findings plus one `IOerror` and 15 missing-reference
findings; its 498 archive facts remain diagnostic. An earlier stdin/spawn launch
failure is recorded separately as a harness error. No validation gate is waived
and neither rejection publishes canonical facts.

### NVE original-filing case

CIK `0000724910`, cutoff `2025-04-01T00:00:00Z`. Originals
`0001376474-23-000283` and `0001376474-24-000214` pass formal strict parsing
with 499 and 519 facts. This additional service case replaces no #376 issuer.
Its 36 accession-bound mapping proposals retain 75 provisional facts across
18 of 31 required scalar roles. None is approved. Audit input is
`e15f3a71a11215aea97a455f2ee703cb951be566c746f77475dd51c03beaca10`;
output is `470c236d4c08f9bcaa46cfbffe830a13b35c9c37c1893c6afea098904f45dfdd`.

The issuer's `RevenueFromContractWithCustomerIncludingAssessedTax` represents
contract R&D revenue, not total revenue. FY2024 total `Revenues` is 29,804,179,
comprising 586,116 contract R&D plus 29,218,063 product revenue. The audit
retains this reconciliation and rejects the partial tag as a total mapping.
The disclosure says no **material** contract assets/liabilities; it does not
establish zero. Accrual/tax partition, remaining claims and complete award scope
remain unresolved. The 4,181 unrecognized-compensation duration tag conflicts
with its point-in-time narrative, and a 36,000 non-option tag appears in an
option table; neither is silently relabeled.

The original also separates 42,706,080 corporate bonds from cash. Its 9,842,796
money funds are already included in cash. The current FCFF bridge lacks a
non-operating-asset role required by the canonical target; this is recorded in
[#381](https://github.com/sosodennis/value-investment-agent/issues/381#issuecomment-6807438390).
Omitting the bonds or counting money funds twice cannot produce an acceptable
NVE valuation. All source gaps remain retained; no numerical result is claimed.

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
   facts/snapshot persistence, deterministic automatic mapping approval, trusted
   release, formal #352 prepare, authentic exact-input caller approval,
   numerical calculation, and API artifact retrieval.
2. The complete flow repeats without new downloads, snapshots, artifacts, or
   domain rows and with identical input/output digests. Concurrent deduplication
   passes. Operational access audits remain distinct from domain identity.
3. The same store survives restart. Export and restore into a separate empty
   store preserve evidence, results, provenance, and repeat digests.
4. Failure retention covers missing/conflicting/future facts, unknown amendments,
   invalid mappings/sources, corruption, missing or invalid machine evidence, and invalid caller approval.
5. Exact-commit mapping, forecast, label/history where applicable, preparation,
   calculation, persistence, deterministic replay, and refusal tests pass with
   architecture, Ruff, type checks, contracts, and `git diff --check`.
6. The isolated `persistent-valuation-flow-v1` service tuple passes all 19 gates
   with exact image/source/runtime pins, commands, exit codes, and digests.
7. Independent PR review and required CI pass. Merge PR #370, verify its merge
   commit on main, close #361 and completed dependencies, then clean only
   issue-owned resources with retained backups.

The owner replaced mandatory human mapping review with automatic approval on
2026-11-12. Fundamental Service owns the versioned direct-US-GAAP policy, trusted
machine identity, source/observation scope, retained decisions and abstentions.
The release canary re-evaluates the exact retained input and rejects a signed
certificate that does not reproduce the mapping or released facts. Existing
human review records are preserved. AI verification is future scope. This does
not supply missing facts, computed accounting partitions, financial policy,
threshold evidence or exact-input caller approval. The old pending Dennis
packet is proposal history and is no longer an outstanding human gate.

## Evidence, runtime, and preserved history

[The accounting checkpoint](issue-361-accounting-checkpoint.json) preserves every
previous top-level entry. Its source-review entry,
`dated_market_source_review_increment`, records source hashes, proposal and
repeat digests, exact commands, retained failures, unverified gates, and next
steps. The preceding implementation entry is
`explicit_empty_award_inventory_increment`. The latest
`sec_original_determinism_increment` appends exact #405/#406 implementation,
fresh-parser failures and corrections, full checks, CI, source review and repeat
evidence while preserving all 40 prior entries.

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
earlier source-review increment started or cleaned no Docker resource. The
focused conflict validation above used and removed its own project and does not
establish the full numerical acceptance profile. Re-read the canonical runtime tuple
before the next service acceptance run.

Generated sources, mappings, proposals, diagnostics, and backups remain in ignored
`.audit`. Do not reset, rebase, force-push, or discard the checkpoint chain. Do not
restore `.tmp-issue355-sec-useragent-compose.yml` or clean another project.
#361, unresolved blockers #369/#381/#394, and PR #370 remain open. Implemented
normalization blockers #404/#405/#406 still need delivery and main verification. Complete
source scope and actual review precede numerical acceptance; thresholds stay null.
