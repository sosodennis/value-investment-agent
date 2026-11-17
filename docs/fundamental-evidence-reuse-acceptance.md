# Fundamental evidence reuse acceptance

This records the first implementation increment for #445 / PR #446. It does
not replace the completed #361 / PR #370 delivery or establish parser-action
reuse acceptance.

## Tested implementation and runtime

- Baseline: main `078ab75262dda93f8a1b6c6978fbf6b248890a05`.
- Candidate: `7713fb263f5d211ea05a685477a22567e06bdc72`.
- Worktree: `/Users/denniswong/.codex/worktrees/issue-445-evidence-reuse/value-investment-agent`.
- Compose project: `value-investment-agent-445-evidence-reuse`.
- API / PostgreSQL: loopback ports 21491 / 21492; network `10.231.101.0/28`.
- Service limit: one CPU, 3 GiB. Baseline and candidate use separate metadata
  databases restored from the same retained main backup. Immutable content is
  shared only inside this issue's owned volume.
- Baseline image: `sha256:34875a1e51b247ff41aa69a7fba5dfe99e128c2b5e644113a67456c25f4fc4ed`.
- Candidate image: `sha256:d068a9e3a5d4e0a2775b4480d60527766a3577586ce04886b8e24592d92193ad`.

The ignored audit directory `.audit/issue-445-evidence-reuse/` contains
`runtime.json`, `candidate-runtime.json`, the exact Compose and request inputs,
receipts, profiles, row counts and authenticated API readbacks. Credentials are
excluded from this record. The implementation was tested from an archive of
the exact candidate commit, excluding subsequent parser-action WIP.

## Full numerical replay measurements

Five alternating, unprofiled, successful company/date runs per version used
the fixed real MSFT inputs, pinned sources, policies, dependencies and model.
Each run included trusted release, formal composer, deployment-authorized
exact-input automatic caller, existing calculator, persistence and authenticated
API retrieval. Container restart happened outside each timed region.

| Metric | Baseline | Candidate |
| --- | --- | --- |
| Wall median | 75.14938 s | 40.15769 s |
| Wall range | 74.17274–77.14072 s | 39.28545–41.54218 s |
| CPU median | 71.33583 s | 36.84488 s |
| Sampled memory median | 1,360,412,672 bytes | 1,391,357,952 bytes |

Median saving was 34.99169 s (46.6%). Host load and every sample are retained
in `stage1-final-benchmark.json`; shared-host load varies and this is not a
throughput claim. CPU is the service cgroup delta, covering CLI and API.
Memory is sampled; container peak is separately recorded in each receipt.

All ten runs calculated the same numerical outputs across versions. Within
each version applicable artifacts were stable, all execution and lineage
publications reported `wrote=false`, domain row counts were unchanged, and API
result/provenance matched persistence. Result hashes differ legitimately with
source revision:

- Baseline: `4bbf6f27c48b6ea067b80d360f8fd1eddef6716fe8d97dfed31b78445709ce37`.
- Candidate: `c5bd280b0c3ee5ad44ca3d71aa48251915cdd64985738f9d3e419fa8fee001bd`.

Existing-source first preparation took 664.5843 s (CPU 631.2558 s; sampled
peak about 3.066 GB, cgroup peak 3.118 GB) and completed the numerical/API flow.
It created new versioned evidence and is not a warm-replay sample. New-original
first execution is not established by this increment.

## Separate diagnostic work counts

The v3 probes cover CLI and API processes. They are for attribution, not the
wall-time comparison above. Layered reads overlap; their bytes are not added.

| Work | Baseline | Candidate |
| --- | --- | --- |
| Full preparation reads | 14 | 3 |
| Individual validation reads | 42 | 9 |
| Report replay-digest calls | 51 | 18 |
| Content reads | 1,366 | 823 |
| Content logical bytes | 4,662,142,450 | 1,579,756,972 |
| Artifact reads | 730 | 512 |
| Artifact logical bytes | 521,986,239 | 252,228,465 |
| Union unique content bytes | 223,479,651 | 223,479,651 |
| Union unique content objects | 161 | 161 |

Candidate preparation context: 11 hits, one miss, zero evictions. Report
identity misses were nine for both versions, with zero evictions. Independent
producer/verifier scopes deliberately retain separate validation. Logical
bytes describe repeated work, not disk capacity.

## Commands and correctness

From the active worktree, both commands exited zero:

```sh
python3 .audit/issue-445-evidence-reuse/benchmark_final_warm.py
python3 .audit/issue-445-evidence-reuse/run_diagnostics_v3.py
```

The exact candidate archive full Fundamental suite used the owned test
PostgreSQL URL and archive-only `PYTHONPATH`:

```sh
fundamental-service/.venv/bin/python -m pytest \
  .audit/issue-445-evidence-reuse/stage1-exact-code/fundamental-service/tests -q -rs
```

Result: **4,726 passed, 20 skipped**, exit zero. Skips require separate pinned
SEC/historical resources and are not release acceptance. Real SEC-enabled
numerical service acceptance above ran separately. Focused publication,
revocation and deadline boundary checks: 39 passed. Read-only independent
review of `7713fb26` found no remaining concrete first-increment blocker.
Required CI for that SHA passed, including
`fundamental-service-contract-gate` and `fundamental-service-release-gate`.
The legacy `fundamental-release-gate` skipped and is not counted as a pass.

Raw evidence SHA-256:

- `stage1-final-benchmark.json`: `17770e8454bbd8b9cacf5ac4cc5ca7f97a07c9a7c012560cef0b2dc4d1950705`.
- `stage1-work-summary-v3.json`: `238973af2d5f0fe5d81c9e4d27b9e06d5fcc1003d88f9ad1f186c27c70fca697`.
- `candidate-runtime.json`: `7f7b3befb0ca1e47acbf8912660fe40d552f291b29ed76bcca5020e42b0726c3`.

## Limits and retained counterevidence

MSFT remains provisional, uncalibrated what-if; capital, awards and
reinvestment assumptions are not newly observed disclosures. The supported
history threshold remains null. No #376/#339/#350 work is included.

The first preparation was initially interrupted (exit 137) by a runtime switch;
its incomplete attempt is retained and excluded. A successful first-preparation
run was initially misclassified by the harness's warm `wrote=false` assertion;
the classification and harness were corrected before the five final pairs.
An initial diagnostic failed on a read-only output mount; the corrected probe
uses a dedicated writable output directory. These failures remain in the audit
directory. None is represented as a successful performance sample.

Parser-action reuse, new-original timing, restart/recovery acceptance for new
actions, final delivery-commit acceptance and merge verification remain outside
this checkpoint.
