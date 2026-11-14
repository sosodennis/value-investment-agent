# PR439 independent review and serial integration (#361)

Reviewed head: `547510fb2b77c8acd99154851327fc0793424db9`.
Implementation: `38908d49c1c1f17568e65a373842021aadc93a43`.
Ordinary merge into `codex/issue-361-replay-evidence`:
`7951e3e0224f81ab0687d21c62428f3b30b345ad`, with parents
`5908ab0628afe8b8d053d3487a922446b909a14c` and the reviewed head.
All three child checkpoints and parent WIP are retained.

[Independent engineering review](https://github.com/sosodennis/value-investment-agent/pull/439#issuecomment-6869866634)
inspected the actual four-file diff, official Fundamental forecast/label calls,
model-version binding, source/mapping/label lineage, failures and idempotency.
No blocking findings remain. This review does not supply accounting or
independent statistical/business approval.

At both the clean PR head and exact integration commit, the complete fixed100
audit runs twice in fresh network-blocked processes:100 issuers,589 targets,
19,437 mapping decisions retained. Second publication returns `wrote=false`,
zero new artifacts and unchanged input/output bytes/sizes/mtimes. The output
digest `0c1d604a6ba4c26126bc0da5ad1c186e8da27ba9bd202252706cec3ccd276309`
matches the implementation evidence.136 related tests pass at both SHAs.

At the merge commit: **2,887 Service/PostgreSQL tests pass**,17 external parser
resource skips;181 installed focused tests pass. Ruff/format, source-aware mypy
on four changed owners/tools, both architecture guards, diff, SEC-enabled service
preflight and12 byte-identical full-calculator golden cases pass.
[CI43541082309](https://github.com/sosodennis/value-investment-agent/actions/runs/43541082309)
passes all12 executed jobs; release gate skipped. The131 installed Service
Python/SQL files still match the merge commit exactly: PR439 changes an offline
tool and tests/docs, so the verified Service image/source digest is unchanged
from the [enterprise checkpoint](issue-361-enterprise-stage-checkpoint.md).

| Evidence | Digest |
| --- | --- |
| Independent review | `4697247ba3fb724b468d7c2a51cfe76f782b655620d9abfb10bbb80a946c503c` |
| PR-head repeat/check proof | `147d6893ae29d8010c31ea52f1eb5583dfcc409baa8262c285c75b30014a47db` |
| Integration repeat/check proof | `6bc3018612eb806b87e1e5ffd410455a0e29c93f7b06ae6ef180652105783003` |
| Integration checkpoint input | `7c4de52cf8f6cef3b720b93320475e928f05c337cf3fafcdf035fcf978334ff8` |
| Integration checkpoint output | `4b7aef8a132f2a112d2570593a16d6de73058f653582419854e39b47d7b7ab78` |
| Integration checkpoint report | `92d3261c18d04cab05875f041f46e950cf5c837432ef936a1fa7393fc642b279` |

Ignored command/review/runtime evidence:
`.audit/issue-361-enterprise-stage/integration-checkpoint.json`.
Generated cohort proof/reports remain outside the checkout under
`/Users/denniswong/Desktop/Project/value-investment-agent-issue-361-research-evidence/enterprise-stage/pr439-integration/7951e3e0224f81ab0687d21c62428f3b30b345ad/`.
The initial integration driver correctly failed because its output directory
was inside the checkout; correcting only that external path passes. Its failed
receipt is retained.

The real NVE enterprise research also repeats at the integration SHA, including
concurrent/fresh-process reuse and filesystem restore. Its input/output digests
are `e46ae26a7d1abb724df79130249dc635773947e9e878bf5dfb4651f0659e4efb`
and `49238694e94f415332ef57980e52d0b4f555063d4e35749ce1f87be808051e03`.
The additional commit-bound report explains18 retained files versus17 at the
earlier SHA; repeating the same commit adds none. After verified host backup,
only this increment's two containers, network and two disposable volumes were
removed. All60 baseline containers retain ID/image/start/status; images/cache,
the older v17 source runtime and other projects are preserved.

Keep #376/#377 OPEN: conditional independent issuers1 (NEWMARKET), exact cases
0/100, verified0, threshold null. #361 remains incomplete and PR370 stays draft.
Continue the original persistent source/preparation/approved numerical/recovery
flow; this offline readiness increment does not replace parent acceptance.
