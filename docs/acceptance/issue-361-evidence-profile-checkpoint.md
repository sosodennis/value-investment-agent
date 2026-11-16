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
