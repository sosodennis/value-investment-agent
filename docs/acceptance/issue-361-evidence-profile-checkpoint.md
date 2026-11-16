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
Exact-commit deployment and the remaining full-path profile still follow.

## Next measurement

Use parent cProfile plus bounded 20 Hz CPU stack sampling in parser workers
(at most 4,096 stack keys of twelve frames), with separate CPU/wait/RSS and
phase counters. Child cProfile startup statistics must not be mistaken for a
full worker call profile. Reconcile every phase and retained refusal, then run
ordinary comparisons separately. Select broader operation-local immutable
bytes/report/index reuse only after the remaining path has been measured.
Keep independent verifier scopes, exact source/profile/policy binding and
existing semantic input/signature identities.

Full reports, commands, instrumentation identities, profiles, inventories and
review receipts remain outside Git under
`.audit/issue-361-current-issuer-service/0322bd1d-*`. Qualified quote/source-use,
trusted release, authentic caller approval, numerical replay/restart/restore
and main delivery remain outstanding. The history threshold stays null and
#376's fixed cohort is unchanged.
