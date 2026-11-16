# Native conditional research persistence checkpoint (#361)

Implementation: `92db0351fe6bfb5ab3d07de22b6f7b41d224176e`.
The Service-owned `fundamental-research-enterprise` command calls the existing
research method, official #352 operating composer and shared enterprise DCF.
It stores canonical request, result and execution artifacts in the existing
PostgreSQL/content store. No schema, financial formula, release authority,
caller approval or valuation quality promotion is added.

Execution identity binds the operator-declared revision, actual installed
source, runtime pins and request digest. Installed acceptance independently
matches all 132 Python/SQL files to the implementation commit; source digest:
`dd392eec406f623457019401ff17a51764c38dba89373628cdf8990a191df5a0`.
Architecture decision: [#394](https://github.com/sosodennis/value-investment-agent/issues/394#issuecomment-6869684138).

At that exact commit, 2,903 Service/PostgreSQL tests pass with 17 external
parser-resource skips. The 33 focused research/runner tests are included.
Ruff 0.14.10 lint/format, changed-owner mypy 1.19.1, both architecture guards,
diff and SEC-capable service preflight pass. [CI 43545319421](https://github.com/sosodennis/value-investment-agent/actions/runs/43545319421)
passes 12 jobs; the release gate is skipped. CI supplies no independent review.

The isolated project `value-investment-agent-361-enterprise-persistence`
uses ports 20971/20972 and subnet `10.231.94.0/28`. Its installed command
processes four real-original NVE requests, retaining 109 canonical facts and
55 authenticated automatic mapping decisions from the retained v17 evidence.
Two conditional enterprise scenarios succeed; missing revenue, future evidence
and unavailable transition evidence retain abstentions. No equity/per-share
result or complete current filing coverage is established.

The first execution saves 12 artifacts. Ordinary and concurrent fresh-process
repeats, service/database restart, and repeats after canonical empty-store
restore return identical references/digests and `wrote=false`. All metadata
rows and content bytes/sizes/mtimes remain unchanged during each repeat.
Canonical backup/restore covers 18 tables, 47 rows and 12 content objects;
repeated export and restore also return `wrote=false`.

- Research input: `947be153f2edcee73ccd3b4dbea96fa1ab8b586c76626b9bd0292040efa1fab1`
- Research output: `fb8e49be55a688196f22e4bdd81883a5a1adbbef460f94f3846229d78ac85596`
- Backup manifest: `e3da65f94a96d03d39a40a2c0614e0a1fc0101b4a22a687b4a028a71821c5990`
- Checkpoint report: `0b2c719bcd15c62b8d64c80152ae33962e62b07c6dea03f2e8da707948608577`

Exact commands, runtime tuple, input/output digests, command receipts, retained
failed checks and generated evidence remain ignored under
`.audit/issue-361-enterprise-persistence/`. The initial acceptance harness
selected the empty `public` schema; its failure occurred before publication.
The corrected harness inventories the canonical `fundamental` schema.
The full PostgreSQL/content backup is verified on the host before deleting
only this increment's two containers, one network and two disposable volumes.
All 60 baseline containers retain their IDs, images, start times and statuses.
Images/cache and the retained v17 source project are preserved.

Next: connect company/CIK plus valuation timestamp to automatic preparation
and result retrieval; resolve original-bound capital/award/quote evidence and
complete authentic caller-approved equity acceptance. Independent review,
main delivery and merge-commit verification remain outstanding.
#361/#369/#394/#376/#377 stay OPEN, PR #370 stays draft, eligible research stays
provisional, incomplete equity valuations abstain, and
`supported_history_threshold=null`. This checkpoint verifies persistence of
conditional research, not the parent valuation flow or accounting signoff.
