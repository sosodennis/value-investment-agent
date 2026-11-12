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

## Authenticated caller approval checkpoint

Exact implementation `54ff789dd3a55c71284a15130596faef4221e3ee` resolves the
implementation gap in [#411](https://github.com/sosodennis/value-investment-agent/issues/411).
A supplied approval must match the authenticated subject and carry a timezone-aware
decision time no later than receipt. All three calculation endpoints enforce this
before application execution; the source runner checks before source access.
Direct calculation still permits absent approval. The #361 runner still requires
approval of its exact prepared input before calculation.

Exact checks pass **1,317 Service/PostgreSQL, 56 Agent boundary and 17
acceptance-tool tests**, Ruff/format, 51 Service-source and Agent producer mypy,
both architecture guards and diff checks. Eleven optional resource tests skip;
one duplicate-ZIP warning is intentional. [CI](https://github.com/sosodennis/value-investment-agent/actions/runs/43149977652)
passes all 12 executed jobs; release skips. Engineering input
`dd531d6ae7ba099cded85a49548dd81c2d6285d29bed025639a60503c6020a9f`;
output `c32ae961ce60f320494fc8e90937341cefbeab82178a0cbdd8e36a385a1738f8`.

The isolated installed project `value-investment-agent-361-caller-approval`
used ports 18674/18675. All 68 installed package files equal the exact commit.
Eighteen HTTP cases cover caller/future refusals and matching/absent approval
reaching the ordinary missing-snapshot response. The complete repeat after
PostgreSQL/service restart returns identical bytes with zero new rows/content
files. Installed input
`5440a07894dc7f96eba94ebe0f74e2f90534410af4fede4e22e2493dbc099a96`;
output `26cc6ed3accc6df98e53f1f78d627caad27093b5db1df45e7b4a46b1ace39a92`.
Only its disposable startup-seed containers/network/volumes were removed;
all 38 baseline containers retain identity/image/start time. The checkpoint
preserves all 47 preceding entries and initial regression/harness failures.

This verifies the approval boundary with synthetic requests and an empty source
store. Complete real numerical 19-gate acceptance remains outstanding. Keep
#361/#411 OPEN, PR #370 draft and `supported_history_threshold=null`.

## Automatic original-bound security checkpoint

Exact implementation `8ff612d63266be71e45f3ae6f5f488063c8129ac` adds optional
`security_identity` to the automatic mapping input. Policy
`source-bound-us-gaap-v3` checks the exact original's DEI issuer, annual period,
historical ticker and paired share class through the existing identity validator.
Only a successful check creates security-bound accounting disclosure rules.
Absent identity preserves issuer-only input bytes; missing/conflicting identity
abstains. No current ticker lookup, network call, formula or release gate changes.

Exact checks pass **1,302 Service/PostgreSQL, 56 Agent boundary and 17 acceptance
tests**, Ruff/format, 50 Service-source and Agent producer mypy, both architecture
guards and diff checks. Eleven optional resource tests skip; one duplicate-ZIP
warning is intentional. [CI](https://github.com/sosodennis/value-investment-agent/actions/runs/43140734078)
passes all 12 executed jobs; release skips. Engineering input
`aa41f11759f3e2b74da8828221eae4a5c43b0357fd9f8341b1d39adca80569f7`;
output `05a9fd504c5e45d39f749497d11a3b097e5343b147726e1fc97fe78b953e7f02`.

Both NVE originals retain **70 decisions: 36 approved and 34 abstained**, with
one independent issuer. SBC accounting rules bind original-derived `NVEC` and
reproduce USD 59,657 / 141,936 through the existing evaluator. The complete second
run creates zero publications, returns `wrote=false`, makes zero provider/parser
calls and preserves all 757 content-file hashes, sizes and mtimes. Mapping input
`9e7081e4bf9b968fc66fd0c7b9eee55ef6dfdec4deae41c75a4c0b34e219ce7a`;
output `0a281d2f508104596cbb572081524826c93a721d264e765ba372b315b486862f`.
Empty-store restore preserves 18 tables / 1,613 rows and all decisions; repeated
backup, restore, recomputation and reporting are unchanged.

Installed project `value-investment-agent-361-auto-security` used ports
18672/18673 and image
`sha256:0aa694f8e92bf3255f24bdee2871811736e931e3346baf81e38727233983ec42`.
All 68 installed package files equal the implementation; Python 3.12.16,
Arelle 2.47.4 and Pydantic 2.14.2 are pinned in the report. Formal CLI reuse and
authenticated HTTP metadata/content retrieval pass. PostgreSQL/service restarts
reproduce identical stdout bytes and zero publications. Installed input
`3d777606f80ddffb2ac128d557a67aea1c4ca27e9c05263eaf06a67d95d4d448`;
output `21ee684b0b1b779667fe3d1c6cab1b200a19fab00722e85dc8bb7129388f09f6`.

The 20 normal model/policy startup records match the formal inventory; the other
16 tables and all 757 objects equal the source backup. Repeated installed export
returns `wrote=false` with digest
`78be41963cce4244f9de23834f6d924c20ea535a93e56e52b0733b418a6e8e08`.
All 776 portable backup files (18 tables / 1,633 rows) were checked outside Docker
before removing only this disposable project's two containers, one network and
two volumes. All 38 baseline containers retain identity, image and start time.

`automatic_security_binding_increment` preserves all 45 prior checkpoint entries
and records the initial fixture and harness failures. The fixture now places
conflicting DEI titles in the same paired context. The harness verifies the
actual UID/GID 10001/10001 of `USER fundamental` and selects exact digest-named
logs. No production validator was relaxed. Generated evidence remains outside
Git. Complete accounting/award coverage, admitted market inputs, trusted release,
authentic caller approval and real numerical 19-gate acceptance remain pending.
Unknown evidence still abstains; candidate history remains provisional/abstained,
threshold remains null, #361 OPEN and PR #370 draft.

The subsequent `automatic_mapping_operations_correction` preserves all 46
preceding entries and aligns the runbook's policy name and accounting guidance
with automatic semantic approval. Unsupported classifications abstain; there
is no pending per-mapping human gate. Source and test bytes remain unchanged.

## Automatic annual disclosure checkpoint

Exact implementation `91f75bb8d6b0e8868bc200afe738c101c44f588d` extends automatic
policy `source-bound-us-gaap-v2` to one exact annual stock-compensation expense
sentence. Original issuer, annual period, consolidated scope, USD units, amount,
precision and source offsets remain bound to the accounting evidence. Unknown
scale, unsupported wording, conflicting amounts and comparative periods abstain.
The existing accounting evaluator and #352 formulas retain ownership. An
operating-only release rejects this additional expense role; no release profile
or forged-certificate check is relaxed.

Validation passes **1,284 Service/PostgreSQL, 56 Agent boundary and 17
acceptance-tool tests**, Ruff/format, 50 Service-source and Agent producer mypy,
both architecture guards and diff checks. Eleven optional resource tests skip;
one duplicate-ZIP warning is intentional.
[CI](https://github.com/sosodennis/value-investment-agent/actions/runs/43136454372)
passes all 12 executed jobs; release skips. Engineering input
`7b690088fa6405ea63b4a2584b1153015a5d8356a12e0fc1ef989d4740305975`;
output `fd988a2a1f3d8bef263a55f1bcbf9170909aee45d6991e35f52337ab69ef19d0`.

Two NVE originals retain **70 decisions: 36 approved and 34 abstained**. Each
original has 32 scalar and three supporting award roles. The newly admitted
annual expenses are USD 59,657 and USD 141,936. Independent issuer count is one.
The full second run creates zero publications, returns `wrote=false`, makes no
provider/parser calls and preserves all 645 content-file hashes, sizes and
mtimes. Mapping input
`869ca689b8f55ec9a4af4386f9470c41bf62ff65d286cb99009676adcddf460b`;
output `c6b26100249b48958783481809ee4dde4db0748e134a4824173b8548cec6fa66`.
Offline backup/empty-store restore preserves 18 tables/1,389 rows and all 70
decisions; its second backup/restore/recomputation/report are unchanged.

The isolated installed-service project `value-investment-agent-361-auto-mapping`
used ports 18670/18671 and image
`sha256:a905869c98ed19a2f34e8ffc875649e2dea3a318df1bcadf7a56e26dc2efc54b`.
All 68 installed package files equal this exact implementation. Python 3.12.16,
Arelle 2.47.4 and Pydantic 2.14.2 are recorded. The formal approval CLI reuses both
batches; authenticated HTTP metadata/content retrieval returns 200 with matching
digests. PostgreSQL and service restarts reproduce identical output bytes and
zero new publications. Installed input
`eb5e03217b8030f501188fd9ce71b4cfc51477ee4dc438ccf7d50a57632b92de`;
output `3ef1a345f949fb2f8fdcd134dc825695572929aadda656ddeae9a3221a2fdddb`.

The first export comparison failed because normal service startup adds ten
model and ten policy records to the offline store. Each added payload/digest
matches the exact startup inventory; all other 16 tables and 645 objects remain
identical. Subsequent restarts and exports preserve installed backup digest
`57758a79a845b8df01fad47a1b91af525969ab9c98cd00ede5c31622cdd6a529`.
The 18-table/1,409-row portable backup was copied outside Docker and all 664
files verified before removing only this disposable project's two containers,
one network and two volumes. All 38 baseline containers retain identity, image
and start time. The existing PostgreSQL project on 18665 remains available.

`automatic_disclosure_increment` preserves all 44 preceding checkpoint entries
and the initial harness failures. Generated source, mapping and backup bytes
remain outside Git. Mapping reuse/recovery is verified within the stated scope;
complete security-bound accounting/award coverage, admitted market policy/quote,
trusted release, exact-input caller approval and the real numerical 19-gate flow
remain incomplete. Unsupported decisions abstain; candidate history remains
provisional or abstained and underpowered threshold evidence leaves
`supported_history_threshold=null`. Independent PR review, merge and main
verification are outstanding. Keep #361 OPEN and PR #370 draft.

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

## Complete automatic mapping batch checkpoint

Exact implementation `7e3a24ce58f217f8e94285e5d8e7eaedd720f8fb` generates every
service-owned role without a caller-selected proposal list. Each NVE original
retains 32 scalar roles and three supporting award roles: 17 approvals and
18 abstentions. Both originals therefore retain 70 decisions, including every
unsupported accounting/award role. Approval certificates and child decisions
are explicit batch dependencies; invalidating a certificate marks its batch
report stale.

Validation passes 1,235 Service/PostgreSQL, 56 Agent and 17 acceptance-tool tests,
Ruff/format, 49 Service-source and Agent producer mypy, architecture and diff
checks. Eleven optional resource tests skip; one duplicate-ZIP warning is
intentional. [CI](https://github.com/sosodennis/value-investment-agent/actions/runs/43131785794)
passes all 12 executed jobs; release skips.

Two complete real batch runs reuse all artifacts, preserve 533 files' hashes,
sizes and mtimes, and use zero provider/parser calls. Input
`9d2eafd1fefba4d34d4f4f4892663946f936a3849f11c214577eacc26f3aaa20`;
output `4a723161fa5c44710e64c955cbb6ed6287fb438eb4ff44eff9af52d1e850154d`.
Empty-store recovery preserves 18 tables and 1,165 rows, with all 70 decisions
reproduced. The second backup, restore, recomputation and report return
unchanged. Recovery input
`5fd23062e64dc150bf003a5a3346dff535c6223dfd40b25b3a5c54b7dfbb01cd`;
output `7472790160c5de2bbab4787d3532e9afe4191ca57d93cc2264fef0aa904d311d`.

The appended `automatic_mapping_batch_increment` preserves all 43 prior entries.
This establishes mapping persistence and recovery, not complete accounting
coverage or numerical valuation. No Docker resources were started or removed.
Generated evidence stays outside Git; threshold remains null and PR #370 draft.

## Non-operating asset bridge checkpoint

Exact implementation `e1bfd8a55d1df860bf758c048ef727b2ac2cfb96` adds an explicit, mandatory non-operating asset
amount to the existing composer/calculator equity bridge. It preserves source,
period and observation lineage, rejects overlapping cash/working-capital inputs,
and versions both models to v2, requirements to v3, composer to v5 and calculator
to v2. Missing amounts cannot default to zero. The current FCFF profile therefore
requires 32 scalar roles; the earlier 17/31 NVE result below is historical.

Validation passes **1,221 Service/PostgreSQL, 56 Agent and 17 acceptance-tool
tests**, Ruff/format, 48 Service sources plus the Agent producer under mypy,
both architecture guards and diff checks. Eleven optional resource tests skip;
one warning constructs an intentionally duplicate ZIP.
[CI](https://github.com/sosodennis/value-investment-agent/actions/runs/43128124087) passes all 12 executed jobs; release skips.
Check input `988fad935a7b7faf02a988c056db7e183bce3139d4e16f5cc387ad3e1b4d70cd`; output `e662a444cf14546ba654cf9fea7ca1c0f8fa1c743d91411c46de20989dcfb486`.

The prior `0196c084` run's immutable fixture-policy collision and type failures
remain retained. The correction uses a model-versioned fixture policy and typed
JSON/constructor boundaries without deleting rows or weakening immutability.
All 42 prior accounting checkpoint entries remain intact (43 total).

NVE's corporate bonds 42,706,080, cash 10,283,550, cash-included money funds
9,842,796 and investment-interest receivables 460,627 still require a complete
source-bound classification. No real asset aggregate, missing role, quote,
policy or numerical valuation is approved by these engineering tests.
Threshold remains null. The existing isolated PostgreSQL project on 18665 stays
healthy; no containers, networks or volumes were started or cleaned.

## Exact automatic mapping checkpoint

Implementation `b8961d4f169444e6afff0aaae4732d9668cd5669` passes 1,196 Service/PostgreSQL, 52 Agent boundary
and 17 acceptance-tool tests; 11 optional resource tests skip. One warning is
intentional duplicate-ZIP test construction. Ruff/format, 47-source mypy,
architecture and diff checks pass. [Implementation CI](https://github.com/sosodennis/value-investment-agent/actions/runs/43119599803) passes all
12 executed jobs; release skips.

Both real NVE originals produce 36 automatic decisions: 34 approved mappings
across 17 of 31 scalar roles; both D&A mappings abstain. The audit retains 67
eligible and 8 rejected observations, including dimensional net-income contexts.
No zero, complete role coverage, numerical valuation, analyst/LLM ground truth,
AI verifier or human reviewer impersonation is claimed. This supersedes the
historical NVE proposal's zero-approved status below.

Mapping input `507df0b1e8d000fb0b809e2b8e3482ed0526e6cb9970a8e994b93d54416a3888`; output
`57b724a245d826c8cb114277eaf24887afc7bb1b7bff267866b794f4ce6b2b7d`. The full second run returns `wrote=false`, creates
zero artifacts and preserves all 321 content files'
hashes, sizes and mtimes. Both runs make zero provider/parser calls. Prior
policy-version artifacts remain retained outside Git.

Actual mapping-store backup restores into a separate empty PostgreSQL database.
All 36 decisions reproduce input/output digests and return `wrote=false` with
identical 18-table / 741-row counts and
unchanged restored bytes. Re-export and a second complete recovery command both
return unchanged. Recovery input `63bfd3aa49f4a3d2d5c25fd283d14ab0450c9f206281820e190096fcf6b33a19`; output
`54fe8b22daacf161fb36deb204edc059fd503393fe99f972b85130acd8f25249`. Backup manifest
`ae31299ac10581cd91100f9f2213884ab4bfe0210c83bf371ce010310bc981a1`. This verifies mapping evidence recovery;
it does not establish the remaining full numerical service acceptance.

The appended `automatic_mapping_approval_increment` preserves all 41 prior
checkpoint entries (42 total). No containers, networks or volumes were started
or cleaned. The existing isolated PostgreSQL project remains healthy on 18665;
only #361-owned databases/content/backups were added. AI validation remains
future scope; exact-input caller approval and independent PR review remain
separate gates. #361, #407 and PR #370 remain open, with the PR draft.

## Current implementation and verification

The earlier source-determinism implementation is `e30d2e5068f49709c68e794dbb0be1d2c1d11a96`.
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
18 of 31 required scalar roles. None was approved at that proposal checkpoint; the automatic checkpoint above supersedes this historical status. Audit input is
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
source scope and supported automatic mapping approval precede numerical acceptance; thresholds stay null.
