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

Full reports, commands, instrumentation identities, profiles, inventories and
review receipts remain outside Git under
`.audit/issue-361-current-issuer-service/0322bd1d-*`. Qualified quote/source-use,
trusted release, authentic caller approval, numerical replay/restart/restore
and main delivery remain outstanding. The history threshold stays null and
#376's fixed cohort is unchanged.
