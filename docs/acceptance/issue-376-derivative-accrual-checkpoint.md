# NEWMARKET accrued interest-swap checkpoint

Refs #376, #381 and #383. This increment corrects the previous partial accrued
classification proposal: the original derivative note locates an interest-swap
liability in **Accrued expenses and Other noncurrent liabilities**. Excluding
capital-project and observed stock-repurchase payables alone is incomplete.

The owning Fundamental accounting evaluator now represents one negative
interest-swap component with its exact original dimensions, original
classification passage, positive consolidated accrued base and positive
noncurrent derivative pair. It preserves source scope and precision, checks
period/unit/issuer/source membership and amount consistency, and retains the
existing independent review and release gates. Unset component scope is omitted
from canonical bytes. No Agent/UI code or financial model formula changed.

## Exact implementation and checks

- Worktree: `/Users/denniswong/.codex/worktrees/issue-376-composer-integration-local/value-investment-agent`.
- Branch: `codex/issue-376-derivative-accrual`.
- Tested implementation: `e2149919210ac28a5419e4d0d4463809a35df7d8`.
- Preserved base: `e7af51c1c175ab74bf838361f179bf81e0d95340`, draft #397.
- Later checkpoint commits contain acceptance Markdown only. No history rewrite.

At the exact implementation commit, the owner/issuer/accounting tests passed
**105 tests with 6 PostgreSQL skips**. The complete Fundamental suite passed
**829 tests with 48 explicit database/resource skips**. Ruff 0.14.10, changed
formatting, mypy 1.19.1 with CI import settings, both architecture guards and
`git diff --check` exited 0. Exact command strings, observed results and file pins
are retained in the external verification report below. That receipt records
terminal summaries, explicitly not a full raw-stdout archive.

The tests cover provisional quality, exact source/passage membership, canonical
round trips, preserved dimensions/precision, wrong issuer/unit/period/member,
unsupported segment axes, conflicts, missing/negative/noncurrent pairs,
double-counting, amount bounds and security-serving refusal. The value-object
addition changes no agent topology, workflow/state ownership, runtime boundary
or cross-agent responsibility; existing agent skills need no update.

No Docker/service-backed acceptance ran in this increment. No parent checkout,
environment file, database or Docker resource was modified. This checkpoint
cannot authorize merge, issue closure or a real data release.

## Real retained-source replay

The first case remains CIK `0001282637` / NEWMARKET, origin
`2016-02-12T16:26:17Z`. The originals remain
`0001282637-15-000004`, `0001282637-16-000028` and the first subsequent annual
label `0001282637-17-000005`. Label-only evidence never supplies origin inputs.

Each successful replay freshly parsed all three retained originals offline with
the pinned EFM/DQC resources. All three parser replay and fact-semantic digests
equal the earlier retained reports; no original finding was suppressed.
The actual accounting ingestion path produced six **partial, provisional**
accrued relations: four origin observations and two label observations. All source
observations remain attached, including classification passages. The overlapping
2014 and 2015 partial values agree across their original filings.

The observed total-minus-noncurrent swap portions are USD 2,270,000 for 2013,
2,242,000 for 2014, 2,240,000 for 2015 and zero in the 2016 label. The last value
comes from actual label observations; it is not an origin absence assumption.
The resulting partial balances remain **unapproved**, because Other accrued
balances and other required classifications are unresolved.

The second full process returned the same report/input/output digests and
`wrote=false`. A further retained command receipt checked 1,226 source/cache/
report files before and after a fresh process: zero additions or changes to
bytes, sizes or mtimes. Reports use the existing canonical atomic report writer.
Generated executors, receipts, sources and outputs remain outside Git.

External evidence root:
`/Users/denniswong/Desktop/Project/value-investment-agent-issue-376-research-evidence`.

| Evidence | Report digest | Input digest | Output digest |
| --- | --- | --- | --- |
| Real partial replay | `07abe1eef233c9a495c47e2d4920c3bea7ed4ac963d062f6079d3e942d46abdc` | `89d5171a6a27383ce20f113fe0688d8cc376a9f4859327aeddd85eb480967b9e` | `85a6f4715e75def78faeeb0d56d67becbf1ff998821aa51302298f767d3921f4` |
| Fresh-process unchanged-file receipt | `7dbe7fa63014ded63e79a8b948cda2ee4fa5a7867614d8c68901f4ff3af5a0c9` | `898516a8a9db594bfc02a1c8d24baa5e7f614ab33da89f6d773469150df30e62` | `2f5732f44a454e3e8701b294052895f543265b1bc3b08f6eb23501f2dc02c675` |
| Observed verification results | `0658ba811d4b8b8ebc6f7085c2279bb4774baa80f1d688307a2338312d41aca6` | `5d93f4e90a35f8524608e207eea5524210b43f56a79f036a3f70409510afed2d` | `5506459fe025485a0aefde0b5c7c0fb67223bae0ae138b3dbfd66325839b9f8a` |

Reports reside under `checkpoint-e2149919/{derivative-accrual,derivative-accrual-repeat,verification}/`.
Run each external executor with `uv run --frozen --project fundamental-service
python` from the recorded worktree. The real replay executor is
`references/issue376-newmarket-derivative-accrual.py` followed by the full tested
implementation SHA; the repeat and verification executors are
`references/issue376-derivative-accrual-repeat.py` and
`references/issue376-derivative-verification-checkpoint.py`. They require a clean
checkout at the recorded commit; do not reset this branch to rerun old evidence.

## Remaining first-case work

The existing `fundamental-sign-mapping-review` tool was located and its CLI
entrypoint executed successfully in help mode. It signs an existing independent
approved mapping/review with a matching trusted key; it does not supply missing
accounting classifications. This increment creates no replacement signer,
reviewer identity, trust root or real signature. Development fixture keys grant
no actual issuer approval.

Next: resolve remaining receivable/accrual scope and contract-assets/deferred-
revenue evidence, retain the mixed continuing/discontinued 2013 D&A precision
gap, complete actual independent review and trusted publication, then execute
both formal #352 models, first-original labels, errors and full repeat. Freeze
reviewed #377 criteria before outcomes can select a threshold. The fixed cohort
and original dates remain unchanged.

Actual approved mappings, signed reviews, trusted releases and formal study
forecasts from this increment are **zero**. Completed study cases remain
**0/100** and `supported_history_threshold` remains **null**. A successful
partial relation is engineering evidence, not a completed empirical result.
