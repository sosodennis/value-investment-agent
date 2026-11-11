# Issue 376 diagnostic checkpoint

Status: partial research evidence; empirical study incomplete. No threshold,
mapping, policy, release or valuation quality is approved by this checkpoint.
Refs #376; protocol blocker #377; historical owners #369 and #371.

Implementation tested: `6323686e69594a804e61111cba12fe608c3f74cc` on
`codex/issue-376-history-study`, based on main
`52e84dfe5a0dae0c11d2e62fd9a58e885b6eadc9`.
Worktree:
`/Users/denniswong/.codex/worktrees/issue-376-history-study/value-investment-agent`.
Later acceptance documentation does not change the tested implementation.

## Exact-commit evidence

The clean-worktree checkpoint executor ran every command at the implementation
commit and checked HEAD and clean status again at completion. Its external
canonical receipt records every argv, exit code, log digest, input/output digest
and full audit summary.

| Artifact | SHA-256 |
| --- | --- |
| Checkpoint receipt | `a823ed38967f293bb69e9459b5bab86bf35fccfa1b1f6f93796605fcd6cd8f5c` |
| Checkpoint inputs | `456835af248f598df8cc331a3eee6c7bdc75c4815987d4bfacda02f687aca1e5` |
| Checkpoint outputs | `c244d91169db162d083cafab2003e03b958dc11ff710fbe26501fe56c2adcfea` |
| DQC audit report | `11464789ae9b2e547c7761f31f46cbed54f8392675cda91b11c493cf7f16acaf` |
| DQC inputs | `daa0f23e24b39675980efa6d26fade01f558f52c24342a311766ee4a1f029cbb` |
| DQC outputs | `198d3e8953d780a02ba68da0929364659a1c13855002629ad9ea08493a2a4898` |
| Source representation report | `75353eb582b53d88564ab694d3955b55e76aea60548a85c357556e16611bdaa5` |
| Source inputs | `73142268bc6c0fac7343b4ed902eb458d178bb229e73b3f3f2d4ac8b78a27090` |
| Source outputs | `56ac004cdde72c180d0d4d625da742bb53f023940ad65808de46b6e5adbe684e` |
| Fundamental lockfile | `57b9ea3f92002720d4bce735df3316df071479da4c0599a31ae914e9e6c32a18` |
| Checkpoint executor | `643afb547ebcedeedc4f994a812ffdd79bf4c67203bc4b52ff748b1ef3f3fc7b` |

Runtime: CPython 3.11.15, lxml 6.1.3.0, libxml2 2.14.6. These audit runtime pins
are distinct from the historical parser's recorded runtime; original results
and their original pins remain unchanged.

External evidence root:
`/Users/denniswong/Desktop/Project/value-investment-agent-issue-376-research-evidence`.
Reports and command logs are under `checkpoint-6323686e/`; official references
and exact executor sources are under `references/`. The original research tar,
manifest and complete-history bundle remain in the separately verified #361
research archive. Local retention is not a shared production evidence service.

## Executed checks

All commands exited 0 at the exact implementation commit:

- `uv run --frozen --project fundamental-service pytest scripts/tests/test_audit_history_dqc_applicability.py scripts/tests/test_audit_history_source_integrity.py scripts/tests/test_verify_issue361_research_archive.py -q`: 21 passed, no skips.
- Ruff 0.14.14 `check` and `format --check` on the three tools and three tests.
- mypy 1.15.0 `--follow-imports=skip --ignore-missing-imports` on the three tools.
- `python3 scripts/architecture_guard.py --summary`.
- `uv run --frozen --project fundamental-service python -m fundamental_service.architecture_guard`.
- `git diff --check`.
- Complete archive verification/reuse: 10,358 files; `wrote=false`; every
  existing size and mtime unchanged after content verification.
- Complete 589-filing DQC audit, then identical repeat: same input/output/report
  digests, `wrote=false`, zero new report files and unchanged bytes/sizes/mtimes.
- Complete 187-filing source-representation audit, then identical repeat:
  same input/output/report digests, `wrote=false`, zero new report files and
  unchanged bytes/sizes/mtimes.

The exact checkpoint driver command was
`uv run --frozen --project fundamental-service python /tmp/issue376-verify-checkpoint.py`.
The external receipt retains its complete subprocess command arrays. The
[runbook](../research/history-sufficiency-study.md) provides the parameterized
reproduction commands. Both full audits read local retained bytes only; no new
SEC download, database publication or composer invocation occurred.

## Observed limits

The fixed population remains 100 issuers and 589 filings. Ninety-five parser
refusals have only pre-effective blocking DQC findings; none were relabeled as
passed. Of 187 size refusals, 55 have equal Canonical XML without comments and
132 differ. Canonical equality is not regulatory or financial approval.

Nine missing first-original labels and one horizon mismatch cap complete
eligible pairs at 90. The original hardcoded 100-complete-pair state and
descriptive history groups require #377's reviewed accuracy/power protocol.
The official Hyndman sources informed the proposed evaluation method only;
they supply no financial labels or threshold ground truth.

No service runtime or browser workflow changed. Docker/service-backed empirical
acceptance, formal #352 forecasts, reviewed mappings/policies, complete labels
and the full forecast replay repeat have **not** passed. The study remains
incomplete with `supported_history_threshold=null`; #376 must stay open.
