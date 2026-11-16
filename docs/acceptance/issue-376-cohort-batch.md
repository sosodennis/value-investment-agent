# Fixed100 original-candidate batch acceptance (#376/#377)

PR [#440](https://github.com/sosodennis/value-investment-agent/pull/440),
branch `codex/issue-376-cohort-batch`, targets `codex/issue-361-replay-evidence`.
Original implementation `ccd08052af83904bc7f9b39ff6004656178b3b41`; verified
integration merge `79e94ab236d2b5fc8a1231c1e2e304e7ab4f4912` preserves the
implementation and all prior commits. The later head adds acceptance metadata
and the parent's acceptance checkpoint only. Worktree:
`/Users/denniswong/.codex/worktrees/issue-376-cohort-batch/value-investment-agent`.
Design/ownership: [#376 record](https://github.com/sosodennis/value-investment-agent/issues/376#issuecomment-6869697724).

This completes an offline batch-tool increment, pending independent review and
serial integration. It does not complete #376/#377. It processes actual retained
original parser observations through Fundamental Service's proposal/candidate
contracts and replays explicit conditional seeds with the existing formal
three/four/five-year runner, label comparison and #352 composer. It does not
rerun Arelle, reapprove retained failures, release mappings, or promote quality.

| Result | Count/status |
| --- | ---: |
| Fixed issuers / filing targets retained | 100 / 589 |
| Canonical first10 targets / candidates | 65 / 468 |
| Full100 source-bound candidate observations | 3,315 |
| Independent issuers with candidate observations | 49 |
| Retained prior parser successes / refusals | 74 / 515 |
| Explicit current original supplements | 5 |
| Current supplied unreviewed packets / issuer refusals / source refusals | 74 / 2 / 513 |
| Independent conditional cases | 1, NEWMARKET CIK0001282637 |
| Exact completed / verified study issuers | 0 / 0 |
| supported_history_threshold | null |

The two issuer refusals retain `ORIGINAL_ISSUER_DEI_SCOPE_INVALID` and
`ORIGINAL_ISSUER_SOURCE_INVALID`. Candidate observations are not complete
financial periods, eligible forecasts or independent error observations. All
periods, units, scopes, dimensions, conflicts, accessions, source hashes and
mapping versions remain available for actual review. The existing service's
revenue alternatives are exposed as provisional proposals; approval policy and
accounting rules are unchanged.

| Candidate role | Observations |
| --- | ---: |
| revenue | 1,055 |
| operating_income | 519 |
| income_before_tax | 256 |
| income_tax_expense | 357 |
| depreciation_and_amortization | 259 |
| capital_expenditure | 267 |
| cash_and_equivalents | 334 |
| current_assets | 130 |
| current_liabilities | 138 |

The unchanged marker62 execution retains59 unsupported-taxonomy,230
parser-blocked,187 archive-size,37 entrypoint,1 unavailable-validation and1
invalid-payload refusal. These are historical execution counts, not current
parser validation. Supplied newer evidence does not erase any earlier refusal.
The other99 issuers have no supplied current replay seed in this index; every
model/history arm explicitly abstains. This does not assert that their source
data is absent everywhere. NEWMARKET conditional results remain separate from
exact losses and do not approve a supported threshold.

## Exact-commit proof

For both the original implementation and integration merge, fresh processes run
first10, full100 and identical full100 again with network connections blocked.
The full100 repeat returns `wrote=false`, `artifacts_written=0` and identical
input/output/report digests. Existing artifact bytes, sizes and mtimes and all
explicit input files remain unchanged. First10 issuer packet digests equal the
first10 entries of full100. Partial-prefix/retry behavior is also tested.

At the integration merge,235 focused tests pass, including37 new batch boundary
cases. They cover canonical/gzip/chunk identity, duplicate/missing/substituted
results, original-source metadata, future/origin/label changes, preserved
severity, revenue alternatives/conflicts/dimensions, no approval, typed JSON
arrays, partition equality and resumable atomic publication. Source-aware
mypy1.19.1 (three production files), Ruff0.14.10 check/format, both architecture
guards and diff checks pass. Wrong exact SHA and duplicate-JSON CLI controls
exit2 before publication. Twelve command receipts bind commands, commit,
input/output digests, exit codes and outputs.

Canonical runtime: CPython3.11.15, arm64/Darwin, Pydantic2.14.2,
Arelle2.47.4, cryptography50.0.2; lock digest
`229bc76c75019d54df8c1cba240839bacf01e56d7493f4bc615e058c4e5f6f11`.
The retained interpreter is read without installation changes; `PYTHONPATH`
selects this checkout's Service and scripts. No local Docker/DB/.env/trust or
browser state is changed. New live SEC or full service-backed study acceptance
is not claimed by this offline increment. CI provides separate PostgreSQL
service contract coverage.

The canonical evidence root is
`/Users/denniswong/Desktop/Project/value-investment-agent-issue-376-research-evidence/cohort-batch/`.
Generated sources, datasets and reports remain outside Git. One shared
content-addressed `artifacts/` directory reuses unchanged source/conditional
artifacts across checkpoints. The original checkpoint's same-byte files use
hard links; metadata-only commit changes do not duplicate those large objects.

| Artifact at verified integration commit | SHA-256 |
| --- | --- |
| Fixed manifest | `448f496b10e51a2ed351a7a37deb36e0d4b9672c1fbc5ed3b0b845c8cd54da3a` |
| Batch index | `264a8971944e161813bf0db68dd509ad901bc368642d2445d874c9033399787e` |
| Full100 input | `4ae7bcaecbc3cd7e185b6367d6fdcb9a76c23a04a31a69789b262c7a682f322d` |
| Full100 output | `83f40e15e845387d94e42b7b83a55df46eaf1e48d1714d20cadb29f2be4f3876` |
| Full100 report | `1d5fce1275fa09ee807c3c0187b5daba5dba3c849f2a2216a019d3b22757be85` |
| Verification input | `829b2e9e34b098306586de0eaae95a58cfc79f31e496ed4731c0dad03d51e08a` |
| Verification output | `da6f2511daeeda251b7121e86b36c2a8917571a8ac8c71c9edbc84c2876b1b03` |
| Full verification report | `a7a98cf48a1de3e7f465f25e3c679f0871fd1a4b561319b2899ab46e5060ecd2` |

The integration repeat preserves366 existing shared artifacts
(501,397,720 logical bytes). Only102 small issuer/report artifacts were added
when binding the newer commit; unchanged sources and formal outputs were reused.

Reproduce the integration-commit proof at that exact clean checkout:

```sh
PYTHONDONTWRITEBYTECODE=1 \
  /Users/denniswong/.codex/worktrees/issue-376-transition-evidence/value-investment-agent/fundamental-service/.venv/bin/python -B \
  /Users/denniswong/Desktop/Project/value-investment-agent-issue-376-research-evidence/cohort-batch/verify.py \
  79e94ab236d2b5fc8a1231c1e2e304e7ab4f4912
```

The original implementation proof is preserved under its own SHA, including
its original driver. The compact CLI/index contract and direct replay command
are documented in `docs/research/history-cohort-batch.md`.

[Implementation CI](https://github.com/sosodennis/value-investment-agent/actions/runs/43547352188)
and [integration-commit CI](https://github.com/sosodennis/value-investment-agent/actions/runs/43548119417)
both pass all12 applicable jobs; the release gate is skipped. The latter runs
2,940 Fundamental Service/PostgreSQL tests successfully with17 explicitly
resource-dependent skips. No skipped resource check is represented as passed.

Remaining work: independent code review, actual issuer/period semantic
adjudication and trusted releases, explicit eligible seeds for additional fixed
issuers, independently reviewed #377 error/precision/comparison criteria, then
complete cohort losses/uncertainty and isolated service-backed study acceptance.
A null threshold is retained; unfinished engineering is not an underpowered
empirical conclusion. Do not close #376/#377 or clean this worktree before the
increment has been reviewed and integrated.
