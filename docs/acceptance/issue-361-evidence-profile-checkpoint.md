# Evidence execution profiling checkpoint

Partial #361 engineering evidence only. M1, M2 and M3 remain incomplete;
PR #370 remains draft. No numerical release or caller approval is claimed.

## Exact `0322bd1d` deployment

The isolated SEC runtime uses project
`value-investment-agent-361-current-issuer`, ports 21471/21472, service memory
3 GiB and parser child memory 2 GiB with concurrency one. All 170 installed
Python files match Git; package source digest is
`7d558a9bf2fd7af7c0de670221f5decd179dcc98af5b1c9e4aae981fac57485b`.
SEC preflight passed with input/output digests
`d01c0f886dabdcd68ed3c26d8eb6f027b808a03617c9169a33dee291abe82a59` /
`cdbec022f9852cf1629fb7195812b8546852eb320252007ccdde87c9615e21c7`.
The existing signer/key was preserved and its executable suite pin updated.
Thirty-nine unrelated container identities were unchanged.

Exact checks passed 512 owner/PostgreSQL/recovery tests and 56 formal caller
tests with zero skips, lint/format, types, both architecture guards and diff
check. Input/output digests:
`77bff8d7ac5385d258e221f153297335c92a1781f347e277f600d636324bab00` /
`79d7b73a59986e61bb63b12366811127cb7d0dd4e790e5c15f69b829c8dda75a`.
CI run 43802905395 passed all 12 executed jobs. Its release gate was skipped;
it does not establish release acceptance.

## First complete-process diagnostic attempt

The v16 all-process cProfile request kept the fixed MSFT CIK/date, diagnostic
configuration, HTTP denial and 900-second issuer deadline. It returned in
606.87 seconds, blocked before mapping/history/release by a 2026 original
`XBRL_PARSE_FAILED`. It is an incomplete profile, not a performance success.
Request/output digests:
`8ab8628290cffb573b86e6c3ad0e8949b6f4835aa4ec2c1babade17ffdf497f7` /
`26a787f70bb2a4f80c3920e45d710577980eb379185c73ad44d6b80e6cbd6f2b`.

Original preparation took 590.86 seconds and 24.86 parent CPU seconds. Six
parser workers used 74.5–102.5 CPU seconds each; the largest reached
1,833/1,888 MiB RSS. The parent recorded 0.229 seconds of SQL roundtrips.
These diagnostic times include profiling overhead. Parent waits, worker CPU,
inclusive spans and reader counters overlap and must not be added together.
The profile summary SHA256 is
`bf14397441a541268e15657c2ee5faa91690ee6413a38b4dd535fa83701ccdc0`.

Direct owner validation of the same 2026 request subsequently passed in
103.52 seconds without cProfile and 211.55 seconds with cProfile. Both returned
the same validation digest:
`d4b77cd3e31e1bc0973d1d22d5b6be132223c67ebff7f1fff97b9618434c2f42`.
Neither diagnostic replaced the retained failed validation. The initial generic
failure's inner cause was not reproduced; memory pressure remains a hypothesis.
The source/domain/release row inventories stayed unchanged; twelve evidence
artifact/content records were added. No numerical replay is inferred.

## Resource failure classification

An independently reproducible adapter bug converted an inner `MemoryError`
into generic `XBRL_PARSE_FAILED`, bypassing the existing resource retry and
attempt-retention behavior. The regression first failed with that incorrect
code while the ordinary `ValueError` refusal passed. The adapter now returns
the existing `PARSER_RESOURCE_EXHAUSTED` code, preserving the exception cause
and sanitized public message. Ordinary parse errors still refuse. No resource
limit, calculation, wire schema or permission policy changes.

Independent read-only review of the parser and regression found no findings.
It traced the existing worker error propagation and original-preparation
attempt lifecycle, but did not run tests or certify the initial generic failure,
whole PR or end-to-end delivery.

The increment passed 139 focused parser/acquisition/preparation tests and 56
formal caller tests, zero skips, Ruff/format, parser types, both architecture
guards and diff check. WIP input/output digests:
`6aaf58761432f48e219820fb54615290d953ea3ef3a63edaf1ab8468aeb16e0c` /
`5b89a5d29fe9fad582852324b382a653a72cadb25a59508a0eb9209bb8306b0e`.
The exact-commit deployment and diagnostic follow below.

## Exact `82a1a559` execution

The installed image is
`sha256:57505e1a3242c345f4cf1ef39fa29e7ad148f70cda73ffbb4a509e42ed1007af`.
All 170 Python files equal Git; package source digest is
`c975713218ba718e9b08531395ca557a6d1910b3bbc5fe2340c085a13c791d84`.
Exact checks passed 139 focused and 56 formal caller tests, zero skips,
lint/format, types, architecture and diff checks. Input/output digests:
`5430439d26340adec1d66b9f8b9908e356b8260b54825851117d04a7c5140740` /
`7f61d00a82a747a5cd64fa56ca127a47322d2a1ef2005853bbb280cebb821b76`.
SEC preflight input/output:
`41ab13595d23411c7652d9a3bce87edad3eb764f4619c03a85d0d7afc69ab0d7` /
`5ec9ab6ac69542c06d4bd448c438a326877f819828618f4e7557d3fd672c3278`.
Three installed Linux parser resource-limit assertions passed. CI run
43806470778 passed all twelve executed jobs; its release gate was skipped.

The v17 fixed-MSFT diagnostic retained the 900-second issuer deadline. Its
first attempt timed out in preparation (902.70 seconds including command
overhead), after discovery, original preparation, acquisition and history.
Input/output digests:
`766bf7922ece902e35d24f6c69f7b95916b22d703520e727446b3865538ba115` /
`9e197f17e235630520be40ce383a74cd00f1a606f2ae90dcc62a0b7d69dd128e`.
Twelve completed parser workers were recorded: six for original preparation
and six repeated during acquisition. Their peak RSS was approximately
1,826 MiB. No parser exception was captured; the old generic failure's cause
remains unproved.

An identical-command continuation completed in 362.45 seconds and retained
`DILUTION_QUOTE_ADMISSION_MISSING`. Input/output digests:
`a5522351e615300165a0be5f230f25464cf78a25bc521cdc81a45a600b1cb83a` /
`4e85e6865e61fc915f1abdc71e45e517bbf9bc3e8c173e9a74360fb8db42fbc8`.
Its completed preparation process recorded 337.65 wall seconds and 321.82 CPU
seconds. Inclusive spans include 118.50 seconds in 22 preparation reads,
122.26 seconds replaying 55 mappings and 170.95 seconds in the release content
verifier. These overlap. Artifact reads accounted for 18.72 seconds; SQL
roundtrips for 4.92 seconds. Read time alone does not explain the timeout.
The verifier reached the quote refusal; this is not a profile of successful
release signing or the unreachable post-refusal path. Summary SHA256:
`1b49b5bc7bb11bbf4c45db190837f8ac6f2705eb87ecd0dd4e2b5bea753ff60c`.

A separate ordinary run without cProfile/sampling completed in 218.78 seconds.
It returned the same blocked preparation digest
`089cfceb6a58cc7b31fd1c84a4368c47a9860a4ba45728afb1a279ff09a56ff6`,
with every lineage publication reporting `wrote=false`. All fifteen measured
tables retained identical row counts and ordered-row digests. Before/after
inventory output digest:
`b8bdaee85778dab5c58c6e96bce2022e4f6a5702c349d1df1333d22ef086de40`.
Ordinary request/output digests:
`0c6c490e87267acf2e35bd94053d9ea92dfe95b3f80ddbee1c5ac04a2a530c48` /
`b5791575d89cc0701b4f2355a7301b1af8e2a69d62b31385a4e8fc212130c833`.
Authenticated API retrieval returned 200 and the exact preparation digest;
the unauthenticated request returned 401. API input/output digests:
`20a86797eb6dcd79b16fb62cf7dde922679ddf04fdd5e9989c893566e1fe0d36` /
`4f049f26ccdd1175fd530b806defeedcb0051c9a69a2dd4fef2b2c75a941ccc6`.

Independent read-only methodology review identified limitations: checkpoint
JSON contributes to JSON counters; independently overwritten live/interrupted
JSON and pstats have no shared snapshot ID; bounded Python CPU samples cannot
be converted into exact CPU time or native attribution; and the direct
port-80/443 socket guard is not universal zero-download proof. No stack keys
were dropped in this run. The ordinary guard recorded three process loads and
no intercepted attempts, within that limited scope. Review receipt SHA256:
`0fd6bde46af58bf97d8e5492116a49a1cf281a849f461f3ba99611ac267fa73e`.
Raw profiles, inventories and requests remain Git-external as `82a1a559-*`.

## Next measurement

The diagnostic used parent cProfile plus bounded 20 Hz CPU sampling in workers
(at most 4,096 stack keys of twelve frames), with separate CPU/wait/RSS and
phase counters. Child cProfile startup statistics must not be mistaken for a
full worker call profile. The next increment can consume checked acquisition,
mapping and fact stage outputs within one preparation operation, then compare
the same reachable refusal path without a profiler. Further bytes/report/index
reuse requires bounded ownership and separate measurements.
Keep independent verifier scopes, exact source/profile/policy binding and
existing semantic input/signature identities.

## Prepared fact stage output

The next preparation increment retains selected mapping groups and canonical
facts in one private, frozen operation-local value. History assessment,
automatic candidate assembly and flow persistence consume that value when
available, checking its exact plan and snapshot digests. It holds selected
facts rather than parser reports; it adds no process-wide cache, serialized
validation flag or new input identity. A new operation reads the owning stores
again. Independent release verification still reloads and validates its own
evidence. If concurrent activation changes the resolved snapshot, persistence
selects facts afresh rather than using the prior snapshot's tuple. Bytes,
report, fact-index and concurrent-work reuse remain separate
work pending measurement.

Focused filesystem/PostgreSQL checks compare the persisted artifact and
`wrote=false` reuse with fresh selection, reject changed plan/snapshot scopes,
and reject missing or corrupt facts on the next preparation. Full-flow timing
must be measured on the new installed commit; the timings above describe
82a1a559 only.

Full reports, commands, instrumentation identities, profiles, inventories and
review receipts remain outside Git under
`.audit/issue-361-current-issuer-service/0322bd1d-*`. Qualified quote/source-use,
trusted release, authentic caller approval, numerical replay/restart/restore
and main delivery remain outstanding. The history threshold stays null and
#376's fixed cohort is unchanged.

## Bounded mapping artifact reads

Mapping replay and automatic release source checks now pin hash-checked bytes
in an owner-local LRU scope. The default retains at most 256 MiB of raw payload
and 128 artifacts. Each read still checks the complete current artifact record;
changed metadata evicts the pinned value, and a metadata change during a cold
read refuses. Corrupt bytes are never retained and reach the existing owning
validator so its refusal code is preserved. Issuer-integrity parsing also
checks its exact reference hash independently of the reader implementation.

Each operation uses one store. A new operation and the independent content
verifier establish fresh scopes. This is neither a serialized validation flag
nor a process-wide cache. The bound excludes transient reads, parsed models,
metadata and other owner structures; it is not a process memory bound.
Request identities, proposal decisions and signing semantics are unchanged.

The read-only experiment replays the same 55 approved real MSFT mappings in
one installed `3963dafc` process, injecting only the candidate reader. Its
83-artifact working set contains 259,032,283 bytes. The baseline reads 605
objects and 6,308,575,018 bytes per sample. A 64 MiB limit thrashes and saves
no reads; its two samples are slower. At 128 MiB, 398 reads and 2,756,436,309
bytes remain per sample. A 256 MiB limit retains the complete measured set and
reads each of its 83 objects once. All samples reproduce semantic digest
`579318c887cb9330d8d882a4cd4029702e97835f056a8f0e1556f5af8fe1483c`.
The failed and intermediate capacity experiments remain retained.

Five baseline and five 256 MiB samples, interleaving ABBA and three additional
AB pairs, have median wall times 81.33 and 75.80 seconds respectively; ranges
are 80.38–82.95 and 74.98–77.79 seconds. Process high-water RSS reaches
521,252 KiB across the samples. The shared host has ten logical CPUs; load
observed after the first ABBA was 4.96/5.03/5.11, without CPU isolation.
All fifteen retained PostgreSQL table inventories are unchanged. Measurement
summary input/output digests are
`a9bc71e213871fabd16c5d9273ab20512c78e245a440d0399afb473712b086ef` /
`a7f2ac5ca6cc4e117c01c6b631b3a9fddbedb3ea373deaa0dcdf6c54969359d3`.

These counts establish bounded reuse of this working set, not a numerical
valuation or successful release. The experiment excludes discovery, parser
subprocesses, history and other release work. RSS is a cumulative process
high-water mark, not an independent per-mode memory comparison. Timings must
not be presented as end-to-end speedup: decoding reports, rebuilding mapping
requests and canonical input digests still traverse large evidence. Their
cost and duplicate parser work remain separate owning-layer work.

Independent static review found no new scoped findings. It covers metadata,
hash/error ownership, eviction and verifier separation only; it does not
establish whole-PR, runtime or performance acceptance. Boundary tests cover
cross-mapping reuse, fresh-operation corruption, invalidation, changed metadata,
eviction, oversized objects and issuer-integrity reference corruption.
All raw measurements and review receipts remain Git-external under
`.audit/issue-361-current-issuer-service/3963dafc-scoped-bytes-*` and
`scoped-artifact-bytes-independent-review-final.json`.

## Primary and supplemental filing membership

The real MSFT current-source run at `3211068e` passed automatic release
verification and retained a signed candidate after correcting a stale deployment
mapping-version pin. The runner then refused that candidate because it compared
all filing-role accessions with the annual source plan. Three retained
`sec-supplemental-filing` records support the capital/award evidence; they are
not additional annual inputs. All other snapshot pins and released fact/mapping
memberships matched in the retained diagnosis.

Plan membership now excludes only that explicit supplemental source ID from
the primary accession equality. Supplemental records remain in the immutable
snapshot and history/integrity checks. Missing originals, unexpected primary
filings and unknown filing-source IDs still refuse. A history regression covers
supplemental evidence through release, composition, calculation, deterministic
reuse and original corruption refusal. These synthetic calculations do not
count as M2. The real run still needs formal preparation, authentic caller
approval and numerical replay/recovery acceptance.

Failed runs, the signed candidate, deployment policy versions and diagnosis
remain outside Git under `.audit/issue-361-current-issuer-service/3211068e-*`.

## Bounded HTTP execution and absolute stage deadlines

The installed `13312b0c` real company/date run exceeded its unchanged 900-second
budget (902.31 seconds including subprocess shutdown). No prepared input or
numerical result was returned. This is a failed end-to-end run; passing CI and
the supplemental-membership correction do not establish M1 or M2. Its request,
receipt and store-state inventory remain outside Git under
`.audit/issue-361-current-issuer-service/13312b0c-*`.

The HTTP prepare, calculate, policy-calculation and uncertainty routes now share
one per-application worker slot. Waiting uses the authenticated operation's
existing absolute deadline; an expired waiter does not start work or occupy the
slot. Running work stays attached to the worker until completion, so timeout
handling cannot release capacity while that work is still running. Liveness
requests remain available while a valuation waits on blocking work.

The application owner propagates that same deadline through conditional input
recomposition and checks it between source verification, composition, calculation
and persistence stages. These are cooperative stage checks: they do not kill a
running Python function or roll back a transaction already started. The caller's
approval, input identity, released policy and calculator formulas retain their
existing semantics. This bounds HTTP execution and prevents entering a later
stage after expiry; it does not resolve the separate issuer CLI performance
failure or claim a whole-process memory bound.

The increment's owner/PostgreSQL checks passed 270 tests and formal caller
checks passed 56, with no skipped tests. Ruff 0.14.10, changed-source mypy 1.19.1,
both architecture guards and diff checks passed. Independent correctness and
maintainability reviews of the four changed code/test files found no actionable
findings; this is bounded static coverage, not whole-PR review. Full receipts
and reviewed file hashes remain Git-external as `wip-http-execution-receipt.json`
and `http-execution-independent-review.json` in that audit directory.

## Restrict mapping sorts to relevant candidates

The evaluator now skips its generic observation loop when an existing
specialized selector owns the representation. Direct mappings filter the exact
source concept before the existing stable SHA256 sort. Alternative concepts
are similarly filtered before sorting, with every eligible same-period peer
still checked for conflict. No period, unit, dimension, precision or conflict
validator was removed. Relevant rejected candidates retain their original
reasons and ordering; full original/source checks still precede selection.

A read-only differential experiment evaluated 55 retained real MSFT mapping
inputs with five interleaved baseline/candidate samples. All complete decision
payloads matched after binding both experiment versions to the same policy
digest solely for comparison; nothing was signed or published. Across those
55 evaluations, evaluator-module fact sort inputs fell from 105,552 to 338 and
fact digest calls from 106,290 to 1,076. Observed Python report iteration fell
from 459,408 to 429,756, so substantial repeated traversal remains.

The sum of evaluator intervals has a median of 30.44 seconds before and
27.01 seconds after (five samples each, ranges 30.02–31.23 and 26.98–27.29).
Resolution, source loading, discovery, parser, release and persistence are
excluded. One shared host/process was used; cumulative process high-water RSS
was 907,821,056 bytes. This establishes reduced local sorting work and semantic
equivalence for those inputs, not successful full-flow timing or a per-mode
memory comparison. Serialized evidence and source checks remain the dominant
unresolved costs. Normal new policy/source identities and deterministic replay
must be verified separately on the committed candidate.

Raw comparisons remain outside Git as
`e2eb5d52-mapping-candidates-five-pairs-receipt.json` in the audit directory.
Input/output digests are
`5366567bd261eed8e33bddd98ae261650a8d5761ad1e5ab1cc76a71c9850b6da` /
`054bafb357fe2191b755c6f7ec401999774e86f3f7c8871fbd66ecf24af3c263`.

## Source compiler consumes checked originals

OriginalSourcePlan now consumes the preparation and ordered validations returned
by one `read_with_validations` call. It no longer discards those validations and
then reloads each selected filing. Exact reference checks and the preparation
owner's complete validation remain. Every subsequent compile rechecks storage;
there is no cross-operation state. Compiler regressions preserve historical
identity conflicts, publication/reuse and corruption refusal. This removes one
known duplicate read per filing per compile; full-flow timing remains unverified.

## Operation-local referenced report resolution

V2 mapping resolution now decodes a shared report once per owning verifier
scope. It hydrates that immutable report through a private typed context while
parsing fresh original metadata and the request through their existing JSON
contracts. Every reference still checks current artifact status, retention,
media type, dependencies and exact bytes. Original claims bind all metadata
and the checked report content hash; the complete request digest and approval
semantics remain unchanged. Inline v1 inputs retain their existing validation.
No serialized validation flag or `model_construct` grants trust.

The owner retains at most eight reports, 64 MiB of serialized report input and
50,000 facts, evicting least recently used reports. Oversized reports still
validate without retention. These are retention budgets, not heap/RSS bounds;
transient parsing, callers' references and verified fingerprints are separate.
New operations and independent verifiers establish new scopes.

A read-only work-count comparison resolved 55 retained real MSFT mapping inputs
once per side. All complete request digests matched the original approvals.
Explicit report decodes fell from 55 to three. Diagnostic resolver intervals
totaled 16.82 and 6.55 seconds, with concurrent owner tests; this single sample
is neither a formal latency comparison nor an end-to-end result. The baseline
uses the unchanged generic embedded-original check path in the current owner.
The comparison made no writes or policy-digest substitutions.

543 owner/original/mapping/release/recovery tests passed without skips, alongside
Ruff, format, changed-source mypy and both architecture guards. Two independent
static reviews found no actionable scoped findings. Full-flow installed-commit
acceptance and whole-PR review remain outstanding. Git-external receipts:
`wip-report-resolution-receipt.json` and
`e63f7073-report-resolution-work-comparison-receipt.json`. Comparison input/output:
`527ce8f9d1cc1355827fe3a4ab0496b1e481955e27c92b23a391f586c853995b` /
`ec7c55cbf4f47cb0b8dd3db8c65faabf32486f36bb9f363ded0c5993bb057e1a`.

## Installed real company/date continuation reaches preparation

At installed implementation `465ad865ecfa73e3dd719f2c7f82ab5a4bbe8cdc`,
the first MSFT company/date run exceeded the unchanged 900-second deadline
(901.98 seconds including shutdown). A second ordinary invocation with the
identical input digest completed in 566.91 seconds and returned
`approval_required`. Discovery, original preparation, source-plan compilation
and current-source selection reported `wrote=false`; the completed source
preparation was newly written. This demonstrates continuation through trusted
release and the formal composer, not a cold-run timing improvement or complete
M1/M2 acceptance.

Fixed requested timestamp: `2026-11-16T07:13:40.766090Z`. The existing current
capture policy selected effective valuation cutoff
`2026-11-16T07:18:50.589199Z`, preserving later capture availability rather than
claiming those sources were known at the requested timestamp. The input digest
for both CLI invocations is
`4d5832958bec0154928eb2100c7ea5728b541e113f251b0deb92bab748806726`;
the successful continuation receipt output is
`00e1c3f70ff3abde969bf804d042a5f72efd3a1784e1edd68a2dc6cc506ab9d3`.

The signed candidate, canary and preparation were each retrieved through the
installed authenticated artifact API with HTTP 200 and exact content hash;
unauthenticated requests returned 401. Preparation artifact content digest:
`bb7cb949a5c4366a48f91dd69c14f97fec30a340a323c6c71e887e968c808700`.
Release manifest:
`88e84f1aa6be856c047ca1ba33ab90f6d88ccfb733ca674ef7bbb827ff86d1ca`.
The exact valuation input is
`fbc1649ec9f1281aee5ab2782b0f5b04d69fadbea6f94d8f010e3d7398f490a9`;
preparation digest is
`40ced07dfaf09e47af60e154a4fbeee1d4b9ae6941e4c026e030ca656b78a267`.

This input contains three explicit, uncalibrated capital and forward
reinvestment what-if scenarios. Unknowns remain recorded; zero scenario values
are hypotheses, not observed absence. Quality is provisional and the history
threshold remains null. No caller approval or numerical calculation is claimed.
The user subsequently requested automatic approval as the future default;
AGENTS.md now records that direction, including exact-input, authenticated caller
and versioned-policy evidence requirements. That documentation change does not
implement automatic approval or convert the user's direction into a human
approval of this prepared input.

Complete evidence and the exact-input review bundle remain Git-external under
`.audit/issue-361-current-issuer-service/465ad865-*`. All M1/M2/M3 completion
boxes remain open. CI run `43838059735` passed twelve executed jobs; the release
gate was skipped and is not counted as passed.

## Prepared-input replay, concurrency and owned restart

Installed implementation remains `465ad865`; head `5f91bf4d` adds documentation
only. The exact company/date command completed again in 111.59 seconds, then
two concurrent invocations completed in 228.30/228.50 seconds. All five stage
lineage dispositions were `wrote=false`. The two concurrent outputs are byte
identical to the ordinary replay. This proves retained-output and storage
deduplication; it does not prove singleflight of CPU work or zero network calls.

Restarting this issue's PostgreSQL and service restored SEC-enabled readiness.
All 46 unrelated container identities, images, start times and running states
were unchanged; no volume was removed. The post-restart fixed-input replay
completed in 113.29 seconds, with byte-identical output and `wrote=false`.
All 15 measured PostgreSQL tables retained the same counts and ordered row
content hashes through ordinary/concurrent/restart runs. Inventory output digest:
`596ac3c7fb0a000f30cef29a654b1c7d62a654ac3e917e386d3d29ac61d89c97`.
The four replay stdout hashes are
`1306fb4ec0259345430bdd6591d2301b9bc7a06b5877b9fe59e031c7ce45cca1`.
Restart receipt input/output digests:
`d2cf120605b0b0768ac900b131ff41aaab21b63bab490785e2a920f9750c71b2` /
`2dc3bf11c88509371f465909b40c4e243bb860d1bfb81821413aa1de295f822f`.
These remain preparation-only checks: no approval or calculator execution.

Git-external commands/receipts: `run_prepared_repeat.py`,
`run_prepared_concurrency.py`, `restart_prepared_runtime.py`,
`run_prepared_post_restart.py`, `capture_prepared_store_state.py` and their
`465ad865-prepared-*`/`465ad865-msft-prepared-*` outputs in the same audit folder.

## Executed legacy release gate remains failed

The manually dispatched release gate at exact head `5f91bf4d`, run
`43844023954`, job `133219550706`, actually executed and failed with exit 4.
The retained agent clamp profile is 252 days old against a 21-day limit;
consensus has 2 samples against 20 required; replay has 2 against 4 required.
Its Arelle facts-only profile uses 2.38.20, whereas the service uses 2.47.4.
Service calculation does not consume the agent clamp/consensus/forward-signal
artifacts. Applicability and a real service release gate still need an owning
layer correction; neither skipping this job nor reducing its thresholds is
acceptance. #376's fixed cohort/threshold work is unchanged.

Full failed logs and snapshot/replay/backtest artifacts remain outside Git as
`5f91bf4d-release-gate-*`. Executed gate receipt input/output:
`4e54e990093c8450d1e65a2b02651d683ac9bbe9ebba6a15886151ddf803ba7a` /
`07e0881a31f934a16dccd6cf2e7d376781b6e83034743e39b32228d2a6e5eb89`.
PR-event CI `43843650727` passed twelve executed jobs with release skipped.
The dispatched run's separate service-contract job was still running at this
checkpoint. M1/M2/M3 and final review/main delivery remain incomplete.

## Deployment-authorized automatic caller endpoint

The service adds `POST /v1/valuation/calculate-automatically`. An authenticated
context supplies the caller and organization; the payload supplies only the
release/snapshot/model selector and expected input/policy digests. The formal
composer runs again. A deployment-pinned policy controls caller grants, exact
model/policy versions, source-use policy, authorization time, provisional
quality, explicit uncalibrated what-if permission and enumerated diagnostics.
No default grant, supplied approval envelope, manual override or Monte Carlo
path is admitted here. The policy does not establish provider permission or
turn assumptions into observed facts.

The owner saves policy, preparation and automatic approval/refusal evidence
before execution. Approved results use the existing calculator; a separate
immutable execution artifact binds the automatic decision to its result and
saved evidence references. Repeats recompute the decision from current release
and configuration checks, preserving deterministic artifact identities.
Corrupted retained decision bytes refuse before calculation.

113 focused automatic-caller/API/composer/execution tests passed, zero skips.
Changed-source mypy, repository architecture guard, both preparation-boundary
tests, full Service Ruff, changed-file format and diff checks passed. An initial
refusal-test harness incorrectly patched a frozen application instance; it was
corrected to patch the class before these passing checks. This is synthetic
owner verification, not real MSFT numerical acceptance. The installed runtime
remains `465ad865` and has no automatic caller policy deployed yet. CLI wiring,
real acceptance, bounded independent review and final whole-PR review remain.

The three agent-specific skill entrypoints were checked under the architecture
skill maintainer. Their graph/state/ownership guidance remains current: this
increment adds a Service-owned HTTP boundary and changes no agent graph or
valuation formula. No skill edits were required. The previously dispatched
`5f91bf4d` workflow has now completed: the Service contract job passed and the
workflow failed because its actually executed legacy release gate failed.

## Company/date automatic caller wiring

The issuer CLI now discovers the optional deployment automatic approval policy
and service origin at startup. After source preparation it reads the exact
artifact through the authenticated API, verifies its content hash and invokes
the automatic endpoint with the composer's exact input digest. The output joins
the source receipt to the automatic decision/execution artifact and preserves
write dispositions. `--prepare-only` and an explicit approval are mutually
exclusive; source-only checks can stop without requesting calculation.

A bounded HTTP child receives the credential through stdin, never argv or
diagnostic output. The parent limits the complete connection/header/body work
to the original command's remaining deadline and kills/reaps an expired worker.
Redirects refuse and responses are bounded to 8 MiB. The typed response
reconstructs execution evidence to bind the returned calculation and saved
references to its publication hash and exact approved policy.

Independent read-only review found three P2 gaps in the initial candidate:
socket timeout did not enforce a total deadline, prepare-only could forward a
manual approval, and response validation did not bind the numerical result to
execution content. All three were corrected in their owning boundaries. The
reviewer's subsequent static pass found no remaining confirmed actionable
findings. It executed no tests/Git/GitHub actions and remains a bounded review.
Slow-drip HTTP deadline, conflicting mode, changed result, source hash and
credential regressions cover these corrections.

142 related caller/issuer/API/composer/execution and typed-boundary tests passed,
zero skips. Changed-source mypy, both architecture guards, configuration
reference, Ruff/format and diff checks passed. The automatic-caller Compose
overlay mounts an explicitly supplied policy read-only. Real installed-runtime
acceptance, real numerical M2/M3, applicable release gate and final review/main
delivery remain outstanding. No milestone is marked complete by this increment.

## Installed issuer import correction

Exact implementation `7ec988be` passed its 142 related committed-SHA cases and
all recorded static gates, and its installed 174 Python files matched source
digest `7e084273cfe63393e0c27b696b57117d69ded8e3f2e355f9fb71b589a65d9e3e`.
SEC readiness/preflight passed. The first actual company/date `--prepare-only`
invocation then failed at startup: the new caller adapter imported
`src.shared.internal_services` before the installed CLI initialized the shared
contract path. No source acquisition or calculation began. Failed receipt
input/output:
`31dfb0582e10b7ef884a2400df995a8d74b6d4e0e9a7c0a6b943e62ab425348b` /
`b59b9800a5d2366f5c2c1e92da871183893aa6fdd52f93e4c2f44826c710b8e3`.

The HTTP caller now initializes the installed shared-contract root at the
composition boundary and imports the context builder only when it sends a
request. An isolated Python subprocess, without backend PYTHONPATH or repository
cwd, covers actual CLI import/help. All 42 caller/issuer tests pass, zero skips;
Ruff, changed-source types, service architecture and diff checks pass. Raw
`7ec988be-automatic-caller-*`, preflight and failed issuer artifacts remain in
the ignored audit folder. Numerical acceptance still has not occurred.

## Automatic active-release market compatibility

Exact `7407b82e` passed 142 related cases, zero skips, types, lint, both
architecture guards, configuration reference and diff checks. All 174 installed
Python files matched that commit. Its SEC-enabled company/date source-only run
completed in 793.50 seconds within the existing 900-second deadline, but retained
`ISSUER_MARKET_PREPARATION_RELEASE_MISMATCH`; no composer input or calculation
was produced. Preparation artifact `62b05aa363cd4f5643e501cc7fb3d90202c737db856765df01b30b26b640f1e2`
was retrieved through authenticated GET200 with exact bytes; unsigned GET401.
All five source/compiler stages were automatic, without a caller-supplied plan.

The active release contained the same history snapshot but the old compiled
market request. Active-release reuse checked accounting and recipe compatibility
without checking the market request; the later reference invariant correctly
refused. Diagnosis digest:
`bde7ed5a900a9d0c4fba6ae41fd034a183cbd4c53858690a7ef8e27a726cb977`.

Automatic release reuse now reads the retained market evidence through the
existing hash/metadata validator and requires its exact request, snapshot and
complete release references. Incompatible evidence makes the active release
ineligible for reuse and leaves the existing assembly/canary/signing path to
publish a new release. Corrupt evidence still refuses; explicit-candidate checks
are unchanged. Old releases and the failed source report are retained.

The focused regression first demonstrated four incorrect reuse/corruption
outcomes and one compatible reuse. The corrected WIP passes 297 related cases
with isolated PostgreSQL, zero skips; the temporary database was removed. Types,
Ruff/format, both architecture guards and diff checks pass. WIP receipt
input/output digests:
`e9e2c5a96debe7984e5ddd9e5b64126f3f4c462d92a7fd9cef23ab9505a97dd4` /
`ece11243e5050873b9b481fca49e4876c828dfc9c00c869813a46c1e60f97b05`.
Independent bounded static review found no confirmed actionable findings; it
did not run tests or certify the whole PR or real flow. Exact committed-source
checks, deployment and real release/numerical acceptance remain next.

At `7407b82e`, the existing independent Service calculator gate actually ran:
21 cases, ten positive and eleven refusal/degraded, zero findings. Its report
digest is `834108cc99333ea7c1d5471757838cc145e624a9043e269495cfcb224e9616a8`.
This engineering cohort does not establish real numerical acceptance. CI run
43851750615 passed all twelve executed jobs; its legacy release gate was skipped
and is not a pass. Applicable release-gate integration remains outstanding.
M1/M2/M3 remain incomplete, threshold null and PR370 draft. Detailed receipts,
failed-before logs and original bytes remain in the ignored audit directory.
