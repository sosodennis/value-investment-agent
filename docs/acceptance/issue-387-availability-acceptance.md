# Issue 387: retained Microsoft filing availability

Implementation `bc38f23e97168de8ce5bfd50ec82889c0ea58c2e` ports only the
timestamp and report regression from `071169f953e69713a5a202c9a0030356f1834802`
onto main `17975bd1b5a5195d0dcaab9ba0e4c5808434424e`. The dedicated branch is
`codex/issue-387-availability-main`; its worktree is
`/Users/denniswong/.codex/worktrees/issue-387-availability-main/value-investment-agent`.

The retained SEC submissions capture identifies accession
`0000950170-24-087843` as accepted at `2024-07-30T20:06:22.000Z`. Its SHA-256 is
`7a94136c40b74495512c975e6bcb62270977e945a855e5f8d8f424b54d08435e`, agreeing with
the earlier #312 capture. The manifest incorrectly recorded 16:06:22 UTC.
Correcting it prevents the report from admitting this original four hours early.
Canonical filing members and their hashes remain identical. The bundled
archive remains the existing test fixture; no new source data is added to Git.

## Exact implementation checks

Commands ran from the dedicated worktree, using Python 3.11 and the frozen main
Service environment at
`/Users/denniswong/Desktop/Project/value-investment-agent-issue-361-independent-review-evidence/386-main/venv/bin/python`
(`$PY` below). Sources and generated evidence are external to Git at
`/Users/denniswong/Desktop/Project/value-investment-agent-issue-376-research-evidence/cleanup-387-main`.

| Command / check | Result |
| --- | --- |
| `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=fundamental-service/src:finance-agent-core $PY -B -m pytest -q fundamental-service/tests -p no:cacheprovider` | 317 passed, 25 explicit optional DB/resource skips, one preexisting Pydantic warning; exit 0 |
| `uvx --from ruff==0.14.10 ruff check fundamental-service/tests/test_history_sufficiency_report.py` | Pass, exit 0 |
| Corresponding `ruff format --check` | Pass, exit 0 |
| `$PY -B scripts/architecture_guard.py` and `$PY -B -m fundamental_service.architecture_guard` with the same `PYTHONPATH` | Pass, exit 0 |
| `git diff --check 17975bd1b5a5195d0dcaab9ba0e4c5808434424e...HEAD` | Pass, exit 0 |
| Actual commit hooks | Whitespace, large-file and Fundamental pinned Ruff/format pass; other package hooks correctly skip |

Checks receipt: `a18485dbd824cf2b65a791051c0979cbdd6a561f71462bbeec97fa806c1f80ec.checks.json`.
Input digest `caa410e2c4644d452856873eea7ab14f3fcfd1ebe43bef5b21f62c85686bbbeb`;
output digest `7da24630444ab0292dd0ce4c98eb979a74c6e8178020b56eb38143e493dfcc4f`.
The receipt includes the exact command arguments, runtime, lock and fixture hashes.
Production Python and public schemas are unchanged; changed-source type checks
have no production source to check for this two-file correction.

## Original metadata, boundary and report replay

The actual `SecAcquisitionUseCase._select_filing` was called with the retained
authoritative SEC submissions, the exact accession selector and the existing
2024/10-K runtime policy. It rejects both 18:00:00 and 20:06:21 UTC with
`FILING_NOT_AVAILABLE_AS_OF`, and selects the original at exactly 20:06:22 UTC.
The corrected manifest timestamp equals that selected timestamp. This is an
offline source-selection check; it does not claim a new download or publication.

The old main manifest fails the corrected availability assertion with
`AssertionError: 2024-07-30T16:06:22Z`. Both fresh report CLI calls after initial
publication return `wrote=false`, zero new files, unchanged inventory bytes,
sizes and mtimes, and report digest
`9fd84f37004c5ef5667f737cc8ced35659398d4100bada14fa9dabc0fc9d7206`.
The report remains `underpowered`; the threshold remains null.

Replay receipt: `6f283821f0cd7624e36b324a24f784f2ccc74386250eeb360fe62ac8ab40242c.pit-replay.json`.
Input digest `a63b22452e6f086a2c6aeec7b61b26afbe5f30c2f61194b54dbcfd28a4e02cc2`;
output digest `505d142366a1ab92a927e125acd6d3e923aad85baf8ac0e7c3f672ce828ab75b`.
The initial external driver imported `ServiceError` from a nonexistent module;
that exit-1 receipt is retained as
`84ac302f74cc14f8f19eae1bd00d7ceed60f5e475816b76ac41883253674159c.pit-replay.json`.
Only the external driver import was corrected, to the existing operations owner.
The same receipt retains successful first publication/reuse and the fail-before
assertion. No repository code was changed to accommodate the driver.

## Delivery boundary

Independent review, current-head CI and main merge-commit verification are
required before closing #387. This corrects retained fixture availability;
original parsing, financial mapping/release approval, full #361 acceptance and
the fixed-100 threshold study remain under their existing issues. No Docker
resources are created and no Docker, HTTP or user-workflow acceptance is claimed
for this fixture-only diff. Remove this dedicated worktree and branch after the
main merge has been verified and the worktree is clean.
