# Fundamental evidence and parser reuse acceptance

Premerge runtime acceptance for #445 / PR #446, following completed #361 / PR #370.
Merge-SHA acceptance and issue-owned cleanup are recorded after ordinary merge.
Implementation `97d1d8a2206c1888a1fad320961f0c3d87682fd5`; tested delivery
`4f267c20f2c40f74e0ebe85061e0cd7347910636` changes only acceptance metadata.

## Implemented behavior

Preparation/accession and immutable report identities are shared within bounded
owner operations. Producer and independent verifiers establish their own scope.
Current metadata, revocation, retained bytes, trust, source-use permissions and
deadline remain checked at consumption/publication. Parser actions key complete
original/normalized/DTS/IXDS, normalizer, rules/taxonomy, parser implementation,
native/runtime and schema dependencies, using PostgreSQL single-flight and atomic
publication. Incomplete closure misses safely. Original parsed_at and exact raw
proofs are retained; uses and delivery attestations are separate.

Versioned computation identities preserve facts, findings/severity, validation
profile, rules and source closure while excluding execution coordinates. Exact
signed mapping inputs keep raw proofs, source revision and original headers.
Logical resource keys and UTC normalization stabilize equivalent deployments.
Legacy v1 digests retain their old interpretation. Both Docker contexts exclude
host bytecode without deleting shipped dependencies from runtime hashing.

## Real numerical flow

The fixed MSFT company/date input completed trusted release, formal composer,
deployment-authorized exact-input automatic caller, existing calculator,
persistence and authenticated API retrieval. Base what-if per-share result is
USD 228.57860113805253696196280467660237483564405879558; it remains provisional
and uncalibrated. Capital/awards/reinvestment assumptions did not become observed
disclosures. History threshold stays null; no #376/#339/#350 work is included.

Existing captured SEC sources, first preparation under clean parser build:
848.872877 seconds wall, 772.946997 CPU, sampled peak 3,021,398,016 bytes;
unchanged 900-second deadline. This single sample is not a cold-download claim.
Same immutable build, new delivery first preparation: 573.920472 seconds wall,
511.327796 CPU. Initial states differ; do not use them as a controlled speedup.

Cross-delivery proof: 18 parser results before/after, zero new results, unchanged
result IDs/report hashes/parsed_at, 12 new reused=true uses bound to the new
revision. Normalized/archive proof and current exact-input approval both ran.
Delivery result hash: `f7df522b9dba05f3d7a0b82942b801252175ce88848cba6f9f9377609bed34e3`.

## Full replay performance

Five alternating successful, unprofiled complete flows per side used one CPU,
one API worker, 3 GiB, API 5 seconds, CLI 900 seconds, fixed captured sources,
policies/model/dependencies and independent DBs restored from the retained main
base. Container restart was outside timing. Cgroup CPU covers CLI and API;
Cgroup memory usage is sampled, with its peak separately retained. This is not
process RSS. Host load is in each receipt.

| Metric | Main 078ab752 | Candidate 4f267c20 |
| --- | --- | --- |
| Wall median | 75.866107 s | 74.452887 s |
| Wall range | 74.633181–76.991712 s | 70.606663–78.782876 s |
| CPU median | 72.144452 s | 70.423494 s |
| Sampled memory median | 1,356,943,360 bytes | 1,412,255,744 bytes |

Warm speed difference is inconclusive: ranges overlap. The 40–55 second
engineering target was not reached. Earlier first-increment 40-second results
are historical evidence, not the final-version performance result. All ten runs
returned equal base numerical values, stable within-version complete results
and artifacts, wrote=false,
unchanged table counts and authenticated API/provenance equality. Raw benchmark
SHA-256: `383d328f7e76d809949f7ec2a0da45ab32885c80ab4a4b392b1b8c760cdb9baf`.

A separate retained-output check compares all three scenarios and base arithmetic
(values, assumptions, node values/formulas/units), excluding provenance identities
that intentionally differ by version. All five pairs agree; projection digest
`03873a463517f6c6c3ffc591d19410fc07ed0e1e23a47576b17ee40948ab525e`.

Separate diagnostic full flows establish work reduction, not timing acceptance:
preparation reads 14→3; single validation reads 42→9; replay digest calls 51→18;
content logical bytes 4,668,935,871→1,879,521,983; canonical output logical bytes
5,085,738,766→3,451,951,220. Candidate context hits11/misses1/evictions0.
New independent build/action proof costs offset much of the warm saving. Unique
content and file-hash sets are retained separately; logical bytes are not disk
capacity, inclusive timings are not additive. Diagnostic receipt SHA-256 is
recorded outside Git with profiles.

## Checks and limitations

Exact implementation local full suite: 4,837 passed/20 resource/platform skips;
Linux head CI: 4,840 passed/17 skips. Pinned Ruff/format, 27 changed source files'
types, architecture guard, caller boundary and applicable Service calculator
release gate pass. Required CI 13 success, legacy release job skipped and not
counted as a pass. Independent read-only reviews found no remaining confirmed
blocker in their reviewed increments; they did not run tests/runtime/GitHub.

Single-core/single-worker concurrent acceptance failed one caller with HTTP408;
rows and artifacts remained stable. Its receipts are retained. Parallel/recovery
acceptance uses an explicit two-CPU/two-API-worker capacity tuple, still 3 GiB,
API5s/CLI900s. This capacity change is not included in the performance comparison.

Two-core/two-worker parallel acceptance passed: both full requests returned the
same results/artifacts and authenticated provenance, all wrote=false, in
75.240860/75.331269 seconds. SIGKILL interruption (exit137) resumed successfully;
service/PostgreSQL restart then replayed successfully. Complete table-content
digests remained equal before/after each check:
`9bce7a6929ea5dbf19bd0066afdbeed6042d7ca19f7dcf916cb873889fc2aea2`.

## Recovery and refusal acceptance

The owner-verified host backup manifest is
`e66c63d331ff1bb5c3321d9288b93045aea9335da77514fce17d5d3600661950`.
It covers 13,139 objects, 17,145,173,784 logical bytes and 42,342 rows in 19 tables.
11,925 existing objects (16,593,110,131 bytes) were hash-verified and hardlinked;
only 1,214 new objects (552,063,653 bytes) were copied. The prior #361 backup and
its shared sources remain retained. This avoids another full duplicate backup.

Actual restore into a separate empty database/content volume passed; first
wrote=true, repeat wrote=false. All 19 complete table digests matched. Full
company/date flow in the restored store completed in 72.364582 seconds with
identical numbers, provenance, result/artifact identities and wrote=false;
parser action rows remained unchanged. Authenticated API retrieval passed.

Fourteen negative API cases refused unsigned/wrong caller, wrong exact input or
approval policy, missing release, unsupported model, invalidated/stale evidence,
missing/corrupt content, invalid release signature, future/conflicting fact tamper
and invalid mapping version. Restoring the exact valid input calculated normally.
The fact tamper cases fail signed-release binding; full-suite source admission
and future-time semantics are separate evidence, not inferred from that failure.

Six real parser-evidence faults (revoked/stale result, conflicting dependencies,
missing/corrupt result bytes and replaced source report) also refused. Positive
proof passes before and after. Mutations were restricted to the independent
restored store and reverted in finally. Every original metadata row remains
unchanged; 17 tables match completely and the only new rows are three retained,
hash-verified rejected automatic approval records and their content objects.
Context eviction, cache loss/corruption recovery, dependency/build invalidation,
concurrent PostgreSQL single-flight and in-operation revocation are covered by
the passed contract/PostgreSQL suite; this does not claim all were injected into
the real company's live flow.

Raw sources/backups/profiles/logs and full
artifact lists live outside Git under the issue-owned audit/diagnostics paths.
Retained counterevidence includes the cold timeout, bytecode-induced build miss,
legacy fixture failure, unordered-count harness failure and corrected diagnostic
probe closure failure, and overly broad post-refusal/projection harness assertions
corrected to account for recorded refusals and intentionally versioned identities.
None is counted as a passing sample.

The final source/evidence review found no new confirmed trust, correctness or
ownership blocker; its memory/equality reporting corrections are reflected above.
Merge-SHA verification, issue closure and owned-resource cleanup remain mandatory
postmerge steps. Full evidence root:
`/Users/denniswong/.codex/diagnostics/issue-445-evidence-reuse-delivery/`.
