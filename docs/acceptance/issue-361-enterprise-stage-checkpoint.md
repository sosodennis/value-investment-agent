# Conditional enterprise research checkpoint (#361)

Verified implementation: `1947ad8d53637045975dea0c294c74069d1b12d3`,
including shared enterprise-stage checkpoint `97ed6a1d05504be8c87eb8ce250f30cf964a89ae`.
The official #352 operating composer and full calculator now share the existing
enterprise DCF graph. Research emits conditional enterprise value without
inventing missing capital claims, shares, quote permission or release authority.
Internal operating forecast v2 preserves an explicitly absent release digest
as null. All repository consumers migrated; full valuation gates are retained.
Architecture decisions were recorded before production edits in
[#394](https://github.com/sosodennis/value-investment-agent/issues/394#issuecomment-6868932549)
and its [release-reference refinement](https://github.com/sosodennis/value-investment-agent/issues/394#issuecomment-6869149419).

At this exact commit: **2,857 Service/PostgreSQL tests pass**,17 external parser
resource skips;181 installed focused tests pass. Pinned Ruff0.14.10, format,
mypy1.19.1 on the three changed owners, both architecture guards, diff and
SEC-enabled service preflight pass. Twelve full-calculator golden cases retain
byte-identical outputs, hashes and nodes. [CI43539778103](https://github.com/sosodennis/value-investment-agent/actions/runs/43539778103)
passes12 jobs; release gate skipped. No agent topology/state/runtime ownership
change triggers architecture skill maintenance.

Runtime: `value-investment-agent-361-enterprise-stage`, ports20871/20872,
subnet10.231.93.0/28; Python3.12.16, Pydantic2.14.2, Arelle2.47.4.
All131 installed Python/SQL files match the commit; source digest
`ef3f1f75d533eff44494fce8c1dd13f2c03eaaa41dcb4aeb6a0ca86c86e73910`.
Image `sha256:2253f74baf54be9222eca65762ff1792c253b67b551115f845f257f5fcbd283e`.
The frozen host suite uses Python3.11.15/pytest9.2.0.

The real-original harness verifies both retained NVE component snapshots,
109 canonical facts,55 signed automatic mapping approvals, market/source
admissions and composite working-capital evidence from the read-only v17 backup.
FCFF baseline/proxy and ERP+one-percentage-point scenarios produce provisional
enterprise conclusions. Transition retains abstention for missing
`filed_operating_evidence`; missing-revenue and future-market cases also retain
abstentions. Two ordinary runs, concurrent runs, a fresh process and a service
restart reproduce identical input/output digests with `wrote=false`, zero new
downloads and unchanged bytes/sizes/mtimes across17 files. A verified host copy
and separate filesystem restore reproduce the same result without writes.

| Evidence identity | Digest |
| --- | --- |
| Research input | `dc215821b73b0a4e525f009b046315cd34d12cf94f44ea935569a247811752d0` |
| Research output | `9d976ae8cf9470cf915b868ac37aabee847e32507fd1cd4fbe41abe37078bb6d` |
| Retained file contents/sizes | `29ac650d0f35ef351d723cf12e162f3fcf3e0fda9497c43cf558508392a059af` |
| Checkpoint input | `4d05cd4049f0523f94f4bba91c52f7ee08f55a4a55dc283fd38c9490cfaa1871` |
| Checkpoint output | `2e688ef9ac194a98edbbf6ddf23bcf3e8c4adb47724fb3962b15724ed7869dd9` |
| Complete checkpoint report | `89d06cbe6d697703789b4af2683dcc310eb698aafc3fad49d7482eba164e3796` |

Ignored evidence root: `.audit/issue-361-enterprise-stage/`. Its canonical
`checkpoint-report.json` records exact commands, exit codes, commit/diff and
input/output digests, runtime pins, scripts, logs, CI, retained diagnostics and
the host-backup digest. Generated originals, harnesses, reports and backups stay
outside the PR. Diagnostic failures include the strict future-trace fixture,
an aggregate-only harness that read zero facts, and installed-test file/layout
errors; corrections preserve production validation and the failed evidence.

This is **not complete #361 acceptance**. NVE2023/2024 originals are not current
complete filing coverage; residual working-capital fractions and market proxies
retain assumptions. No complete trusted release, capital/award inventory,
entitled quote, common-equity/per-share valuation or authentic exact-input caller
approval is claimed. Restore here covers research files, not new PostgreSQL
recovery or numerical HTTP full-flow. Eligible research remains provisional,
incomplete valuations abstain, history remains underpowered and
`supported_history_threshold=null`.

Next: independently reviewed PR439 serial integration and merge-commit checks,
then continue the original persistent automatic source/preparation/calculation
and recovery flow. Keep #361/#369/#394/#376/#377 OPEN and PR370 draft. Retain this
isolated runtime until integration verification; clean only its owned resources
after verified backup.
