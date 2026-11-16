# Original GAAP2012 DQC configuration (#371/#376)

Implementation `ae807271f887377bc84cf6393d6a2acd12b4a91e`, base
`2af5f8e269005ebd312552371a51799162b478f2`, branch
`codex/issue-371-gaap2012-config`. PR #434 targeted the #361 integration branch.
Main-chat independent review of head `2d8dd47c3dfe0c8b9c082556221fad45435ef611`
found no correctness issues. It was merged after #432 at
`1b34ffa71602914c686e0edd1f13414c26c98bf0`; the first parent is #432 merge
`bc8e037f4327eca1e85e46ca11aa49e989eecef5`. Head CI had 12 passing jobs and the
release gate skipped. This increment does not close #371 or the fixed-100 study.

## Behavior and sources

The explicit `sec-efm-us-dqc-v3.6.2-gaap2012-config-v1` profile binds the complete
original FASB2012 standard taxonomy, the existing official v3.6.2 package and all
eleven unchanged rule hooks. The existing builder accepts `--taxonomy-year 2012`;
its default remains2013. Each profile accepts only its own literal namespace and
fixed config. No issuer-specific member exceptions, severity changes, modern
default changes or financial formulas are introduced. Old profile identity tests
remain unchanged.

| Fixed input | SHA-256 |
| --- | --- |
| FASB2012 entire original ZIP | `4f4d3298fe03f6a703d981fd2aeebb033916c936b7d73490c8d5b9c4c50b2da8` |
| Generated22-axis config | `ad6459e7d296a73e411be5a20ccad94e5bd99e5f0a1eba9847b34c66ff634ca0` |
| Official v3.6.2 package | `84a53e0c4e6e6f9300644978e4ce4884f8d34243a735434f3b36a841c3a28aaa` |
| Retained original selection/report | `9edcb319e3fe771f01492c09add4c59ff5492bfe8cd104a2e333b00af001d258` |

Official archive: <https://xbrl.fasb.org/us-gaap/2012/us-gaap-2012-01-31.zip>.
The original NEWMARKET annual2012 accession is `0001282637-13-000003`, available
`2013-02-15T16:27:39Z`; the fixed decision remains `2016-02-12T16:26:17Z`.
Fresh direct-LF and archive-CRLF parses retain all **1,965** facts and identical
fact-semantic digests. All **50** old DQC1 errors/refusal remain in the report.
The synthetic invalid-member case still blocks with original DQC error severity.
The original acquisition HTTP-receipt gaps remain unapproved.

## Exact checks and replay

All generated sources, full facts/findings, reports and command results remain
outside Git at `/Users/denniswong/Desktop/Project/value-investment-agent-issue-376-research-evidence/gaap2012-acceptance/`.
The external drivers below bind the exact implementation, their source digests,
runtime/package/lock pins, commands and results. Publication uses the existing
canonical ArtifactStore/report writer and atomic writes.

`check_exact.py` passes **73** parser/config/architecture tests; **9** optional
fixtures explicitly skip. Both configured2012/2013 real-original and invalid-member
tests execute and pass. Pinned Ruff0.14.10, changed-file format, dependency-aware
mypy1.19.1 on both changed production modules, both architecture guards and
`git diff --check` pass. Only the external Arelle package's `import-untyped` code
is suppressed. CI at the implementation passes all12 executed jobs; release gate
is skipped. Check report `ebc96ceeb0ffefe0f163738fbbeb7dd3597451fb35d6e868ed8f0455e25fcfb0`,
input `57bfe6a4ef6dae08aaed29313bc286619831fc5a6a16b50c1563524bdd0d0899`,
output `c7ef5090104afa5c6605d78df7607e2b1853de369a9e3bc4b2d0915ee9d8c174`.

`verify_original.py` runs two fresh desktop processes, each parsing archive,
direct original and synthetic invalid member. Second config/report publication
is false, with zero new files and unchanged bytes/sizes/mtimes. Input
`31821bc3f7e339a4fca1a94e2b47e9e3e11af4d4f830ee7bc76d6f0e196cf892`,
output `60fb228a7598831213f10d6af4706e57dbba534f470a98a91029d7fafc09d6ee`,
report `4b4cd4fbc9d287699aab9ca627b5320a322cdc8c129947263d33906e18ee1521`.

`run_container_isolated.py` uses Compose project
`value-investment-agent-371-gaap2012-config`, image
`sha256:e371d924f11d20ccc9ccc14b5c8f2654732d5da5fb29e647d43c35d5bc7eb2f9`,
1GiB/0.5CPU and `network_mode: none`. No host ports, DB, network or named volumes
are needed for this offline parser/compiler boundary. The batch HTTP healthcheck
is disabled; no service-readiness or live SEC-ingestion claim is made. Both fresh
containers verify all115 installed Python files against the exact source manifest.
The config builder exits in its own process before the parser runs, following
the existing offline CLI boundary. Every parse reports zero network attempts.

Second container reuse has `wrote=false`, no new/modified artifacts, identical
input/output/report digests and no OOM. Container output equals the desktop
output above. Separate Python3.11/3.12 runtime pins yield separate report identities;
cross-runtime report identity is not claimed. Container input
`e85b913596b10adccebb7d1e858d4ec3f771565f78bbc09e079c1f409ff8f6e9`,
report `bdfd2968110efffdeafab03addd7b1c307dcc7a1ef1669d43f1669d547e07562`.
Proof `dae7da40e7198505b83758cd399111d68fc36a3d613379fe88d34c342a15b5c8`,
input `b0dbeb88b00face2bba59c3d523c381c9b6314a832bd1b84a3f8b423046a4410`,
output `b11c3b4a51f277c3f627ee4d2fff228fa7f82ae9006548d74901b42e324ad53f`.

Initial combined-process768MiB and diagnostic1GiB runs OOMed. The diagnostic
retained approximately531MiB parent RSS after whole-taxonomy generation; parsing
then overlapped that parent with its worker. A redundant1GiB attempt was explicitly
stopped with exit143 before replacing that premise. These failures, profile log
and the stopped attempt remain retained. Process-separated generation completes
under the same1GiB limit without changing source/rule/financial outputs. Development
invocation/fixture-path and retained-report-shape errors were corrected before
the exact acceptance runs; they are not passing acceptance evidence.

## Cleanup and limits

Only this project's failed/finished containers and image tag were removed.
All91 baseline containers retain IDs, images, start times and states. No own
container/network/volume remains; external evidence and the review worktree remain.
Cleanup report `93a5b030ce0e1b97e2f6388b46bde9c1469543ebc3515702ea22f0d516d10dcd`.

## Merge-commit verification

On `1b34ffa71602914c686e0edd1f13414c26c98bf0`, all 73 focused parser/config,
architecture and source-replay tests passed; 9 optional fixtures skipped. Both
Ruff and format checks, mypy on both changed production modules, both architecture
guards and `git diff --check` passed. The 2012/2013 source-backed tests retain the
1,965/2,508 original facts, prior refusal/findings and invalid-member blocking.
The merge verification does not change the implementation evidence identities
or authorize accounting mappings/release.

Parser compatibility grants no mapping/reviewer/release authority. The official
`PaymentsToAcquireProductiveAssets` definition includes software/intangibles;
it still cannot alias PPE cash capex. Five-year accounting semantics, Transition
filed evidence, exact accounting/trusted reviews, prospective promotion review
and the complete unchanged100-issuer study remain unfinished. Independent
conditional issuers remain1, complete exact issuers0/100, and
`supported_history_threshold=null`.
