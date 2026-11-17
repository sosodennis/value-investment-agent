# Fundamental performance acceptance

Premerge acceptance for #447 / PR #448 at implementation `ee5336728ee40bb87bcbe55b94a6a33cedbc3075`, against main `ef254896f67979e712abb8e289cfa3b2d0297881`. Later acceptance commits change metadata only. Merge-SHA verification and cleanup are recorded separately after merge.

The fixed MSFT company/date entry completes automatic source planning, real SEC original reuse and validation, trusted release, the formal composer, deployment-authorized exact-input approval, the existing calculator, persistence and authenticated numerical/provenance retrieval. This acceptance preserves the completed #361 and #445 deliveries.

The primary comparison uses 1 CPU, 3 GiB, one service worker, API deadline 5 seconds and CLI deadline 900 seconds. Each A/B sample restores its frozen starting state outside timing. Each workload has five baseline/candidate alternating successful complete flows. Profiler runs, qualification runs, failed attempts and extra-capacity experiments are excluded.

| Workload | Baseline median and range, seconds | Candidate median and range, seconds | Wall reduction | CPU median baseline / candidate |
| --- | --- | --- | --- | --- |
| A | 778.559881, 763.147498 to 822.114664 | 570.970766, 565.185625 to 597.283246 | 26.6632% | 708.436031 / 525.492699 |
| B | 539.717572, 537.050450 to 543.271976 | 337.190424, 336.192932 to 339.938329 | 37.5247% | 480.328708 / 301.166536 |
| C | 73.958712, 73.804620 to 74.730212 | 51.617652, 51.059617 to 53.133122 | 30.2075% | 70.095341 / 47.992588 |

A starts with captured sources and no parser action results for the build. B starts with applicable parser results and no delivery-specific mappings, release or decisions. C replays complete accepted fixed inputs of the same delivery. A is not a first-network-download benchmark.

| Workload and side | All five wall samples, seconds | Maximum container lifetime cgroup peak, bytes |
| --- | --- | --- |
| A baseline | 822.114664, 801.907098, 770.245488, 778.559881, 763.147498 | 3191058432 |
| A candidate | 597.283246, 580.444831, 570.970766, 565.185625, 567.924315 | 3060465664 |
| B baseline | 543.271976, 539.717572, 538.373449, 537.050450, 541.087610 | 2194792448 |
| B candidate | 337.440968, 337.190424, 339.938329, 336.192932, 337.170202 | 2478530560 |
| C baseline | 74.680443, 73.958712, 73.804620, 73.887994, 74.730212 | 1774817280 |
| C candidate | 51.059617, 51.753993, 51.617652, 51.124944, 53.133122 | 1460412416 |

All three performance gates pass. C has a median below 55 seconds and all workloads improve by at least 25%. Memory remains within 3 GiB without OOM. B has a higher peak on the candidate and retains that tradeoff. Sampled cgroup usage and lifetime cgroup peak are not process RSS. Host load, sampled memory, CPU and every input/output digest are in `formal-ee533672-samples.csv` and the per-sample receipts outside Git.

The timed boundary includes the company/date CLI through authenticated numerical/provenance retrieval. Post-run equivalence/statistics and starting-store setup are outside timing. All counted outputs calculate three scenarios. C preserves exact signatures, reports reuse with wrote=false, and changes no table contents. Fresh A parser execution timestamps and use proofs can differ. Within the same delivery, A/B computational domain digests over id, digest and payload agree, excluding created_at; exact approval evidence still binds the actual input of each execution.

The implementation removes repeated work in existing owners. Preparation exposes verified accession-indexed results within a bounded operation. Report identities and lease representation selection reuse `MappingInputDigests`. Each independent verifier establishes its own bounded artifact, build and taxonomy scope. Disclosure/lease candidates are filtered before deterministic sorting. Multiple required resource hashes share one verified traversal. Canonical v1 output bytes remain compatible. Current source bytes, metadata, revocation, permissions, trust and deadlines remain checked at consumption/publication.

Generic concept indexing, changes to read-time content registration and persistent parser workers are deferred. Concept selection was approximately 1 ms in the earlier case; baseline C registration was below 2 inclusive seconds. Neither observation supports a major whole-flow improvement claim. No extra CPU, RAM or timeout accounts for the formal performance change. Separate work-count and external subprocess profiles are indexed in `latest-diagnostic-attribution-ee533672.json`. Logical bytes are repeated processing volume, not disk usage. Inclusive durations overlap and are never added. The old `file_digest` probe does not observe the new dual-hash stream; it cannot measure total resource bytes.


| Diagnostic observed work | A baseline / candidate | B baseline / candidate | C baseline / candidate |
| --- | --- | --- | --- |
| fundamental_service.arelle_parser.parse_filing_offline.calls | 6 / 6 | 0 / 0 | 0 / 0 |
| OriginalPreparation.read_with_validations.calls | 4 / 3 | 4 / 3 | 3 / 2 |
| ArelleParseReportV1.replay_digest.calls | 119 / 113 | 119 / 113 | 18 / 9 |
| fundamental_service.serialization.canonical_bytes.logical_bytes | 16653636712 / 13376214254 | 16594736709 / 13317592541 | 3438343960 / 1886175233 |
| PostgresContentStore.get.logical_bytes | 29432624739 / 27575145122 | 29477636933 / 27714687344 | 1879521983 / 1997230487 |
| sql.round_trips | 62004 / 47857 | 61953 / 47854 | 4505 / 4867 |
| fundamental_service.arelle_parser._directory_hash.calls | 81 / 9 | 81 / 9 | 9 / 9 |

These separate diagnostic counters cover instrumented owner entrypoints, not every aliased function. They establish fewer repeated build traversals, preparation reads and canonical output bytes. They do not claim all work is removed. C content logical reads increase from 1,879,521,983 to 1,997,230,487 bytes and SQL round trips increase from 4,505 to 4,867 while overall wall/CPU improve. A/B retain about 27.6 GB of repeated logical content processing despite only 358,619,126 observed unique content-hash bytes. The remaining amplification is disclosed rather than interpreted as storage capacity.

A still runs six normalized/archive parser validations on both versions. External candidate sampling observes six XULE worker profiles from root startup and estimates 171.204 inclusive sampled thread seconds in XULE evaluation, 38.714 in DTS/model loading, 1.061 in XULE index building, 1.653 in ruleset access, 12.429 in imports at any stage, and 5.061 in post-validation report extraction/final identity. EFM validation including nested XULE is 180.694 sampled thread seconds and overlaps those categories. These are sampled stack contexts, not an exclusive wall/CPU phase budget. The sampler retains 57 errors. Baseline sampling attached after initial startup and cannot support a precise startup delta. Required XULE/DTS work and still-repeated evidence/DB processing limit further improvement.

The initial A diagnostic chain stopped because py-spy banners shared stdout with CLI JSON. Exactly one calculated formal flow JSON line was extracted to a separate file, preserving original bytes and hashes, then validated numerically and through the authenticated API. B succeeded, but its subsequent probe cleanup stopped when shutdown atexit changed PID1 counters after the snapshot. The original failure and every captured probe file remain. C uses fresh issue-owned scratch with the same B database/data store and matches all before/after tables. These probe failures do not alter the thirty uninstrumented formal samples.
The real numerical case uses CIK 0000789019, MSFT, model fcff_dcf-v2, requested timestamp 2026-11-16T07:13:40.766090+00:00 and frozen effective timestamp 2026-11-16T07:18:50.589199Z. Base, higher-reinvestment and lower-reinvestment per-share values remain USD 228.57860113805253696196280467660237483564405879558, 137.20642110105791021936101504026306779363021878679 and 313.49192356027099566315014377350413378960349955003.

These values remain provisional, uncalibrated what-if. Capital, awards and reinvestment assumptions remain assumptions. Unknowns have not become zero or observed disclosure. supported_history_threshold remains null. #376, #339 and #350 remain deferred.

Canonical exact input is `f3f922b58e1a628d653a50e77fda02c0f0d6b10e6e4d27214879277abb3b7228`. Authenticated API result is `0d57007fb4023329df1bbffda6e5de2c81dace922308924095c87c0d0b24a79c`. Automatic caller policy is `78bd618e96e902959ae991bef97b3a1a9cf37d52a05d748d8c1dcf20f17d3a98`, source-use policy is `a7ff57184cd22632a91a119dee78e414b6db5a12e3b941df190efa82cb4bb6ea`, mapping policy is `8a771bbbef0a9d3ddc92d7c96085bef4c20dfc8fbcd8a391e45db3aa3674606c`, release suite is `748a39f649562db5469b5f3419ee72a2aa0d3fec74a0d6c42c586732ec4be94a`.

Canonical repeat, warm-flow SIGKILL/resume, service/PostgreSQL restart and independent empty-store restore pass numerical, exact-signature, authenticated API, provenance and complete table-content comparisons. Backup `58a2f5db53f03af1a4a7f3762b96c8559dee78d9a177ea650fbc7ff22ebfacc5` contains 19 tables, 2,457 rows and 1,049 objects. Restore first writes and then reports wrote=false. Existing verified content is hardlinked in the backup; only missing bytes are copied. This batch does not separately establish cold-parser interruption recovery.

One worker with two simultaneous full CLI flows retains one HTTP408 and one success, with no duplicate data. Explicit two-worker capacity under the same 1 CPU, 3 GiB and deadlines passes both full flows in 96.807648 and 96.850897 seconds with unchanged tables. This is capacity acceptance, not a one-worker speedup or throughput claim. The canonical configuration returns to one worker.

A request waiting on a controlled database lock leaves livez/readyz responsive. A queued 100 ms request returns HTTP408 in 0.106682 seconds. Current metadata invalidated while the first request waits causes HTTP422 before calculation. Queue and original-row digests remain stable. Exact-commit worker tests separately count calls and prove an expired waiter never enters later calculation. The first observation tool reused a PostgreSQL transaction statistics snapshot and failed to see the wait. Its failure is retained; clearing the statistics snapshot before each poll repairs the probe without changing service behavior.

Fourteen real API refusals plus a restored valid positive pass. Missing/corrupt content, current metadata invalidation/staleness, wrong signatures, model/mapping versions, caller, policy and exact-input approval are refused. Future/conflicting domain-fact and invalid mapping-version substitutions are rejected by signed-release binding; source-admission semantic coverage is separately established by tests. Six additional real parser-proof negatives cover revoked/stale results, dependency conflicts, missing/corrupt bodies and substituted reports. Valid proof succeeds before and after faults. All original rows across all 19 restored tables remain equal. Three added artifacts are verified retained refusal evidence with valid formal contracts, metadata, dependencies and exact content bytes.

The exact configured PostgreSQL suite passes 4,902 tests with 20 skips locally. Linux CI passes 4,905 with 17 skips, executing the three Linux-only memory cases. The shared skips require external SEC resources and are complemented by this real SEC-enabled acceptance. Architecture guards, pinned Ruff/format, changed owner types, contracts, caller boundary and diff checks pass. Applicable CI and fundamental-service-release-gate pass. The skipped legacy fundamental-release-gate is not counted as passed.

Independent review covers all 36 source/benchmark/test files and the retained numerical, performance and fault evidence. The reviewer did not author the code or execute implementation, tests, runtime or GitHub actions. Static source review and read-only evidence review remain distinct from primary-agent execution. Review findings in verification tools were fixed before their results were used.

Full evidence root is `/Users/denniswong/.codex/diagnostics/issue-447-fundamental-performance`. The [runtime tuple](issue-447-runtime.json) records exact image, installed-source digest, runtime pins, Compose project, ports, files and per-gate evidence digests. Raw sources, full reports, profiles, datasets, credentials and backups remain outside Git.

| Evidence | SHA-256 |
| --- | --- |
| formal-ee533672-complete-measurements.json | `0bd4efffadbb09b8ada032151ad1729923b5f3600fe03e3059ce652b70237fff` |
| formal-ee533672-samples.csv | `bd0ebc7d4e0917394b041eb55f39a4d866daa672bb403507c66898640a640855` |
| latest-diagnostic-attribution-ee533672.json | `186c15d196340bc346f88eda89f2a13c7c419057d8a3915678975c49bdedf321` |
| runtime-faults-completion-ee533672.json | `d02f6bda74438972795dca27cd67120aceb73716c779676b26284e0d74a8c145` |
| additional-parser-faults-ee533672-receipt.json | `2b1aba8e183f5d920e1e8ae611735ccc554e67b103fdeb5187d433ff12439ba5` |
| final-retained-rows-ee533672.json | `2d01d2a770460cd9c1f34b3d316b27be358388c699fdb36224b5a90ec9bbd846` |
| final-evidence-review-ee533672.json | `98ef3e4639a0906275e45ad2d946b5aeb21ad0a24dfd2106cd8d8fff62dfdb6e` |
| exact-ee533672-ci-contract-job.log | `fb1822f0c972cfa8f7683b0d0c627b9062c9b9ae8608d2736cc787e719eb2f90` |
