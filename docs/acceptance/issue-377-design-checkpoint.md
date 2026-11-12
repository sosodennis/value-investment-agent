# #377 Prospective protocol-design checkpoint

Tested implementation: `d8d694046c821e77ebdb70e6c67ce45d88481d7e` on
`codex/issue-377-precision-protocol`, based on #361 integration
`79f9aaa75cc9cf0ecd1ae8f755bce43d60d6714e`. No history rewrite, parent checkout,
trust configuration, data publication, financial formula or Docker resource changed.

The [methods proposal](../research/issue-377-operating-study-proposal.md) and
[versioned JSON](../research/issue-377-protocol-proposal-v3.json) make proposed
loss/baseline/precision/noninferiority/multiplicity choices reviewable. They are
not approved/frozen promotion authority. The planning script preserves the fixed
100/589 inventory and at most 90 original eligible pairs; it exposes the infeasible
legacy 100-complete-pair requirement without changing it. Hypothetical variance
scenarios are normal approximations, not empirical power or achieved precision.

| Exact implementation checks | Result |
| --- | --- |
| Focused planning/publication boundary tests | 25 passed |
| Ruff 0.14.10 / format | Passed for both changed Python files |
| mypy 1.19.1 | Changed production script passed |
| Architecture / diff | Root and Fundamental guards, `git diff --check` passed |
| Two fresh-process executions | Identical input/output/report digest; second `wrote=false`, zero new files, existing bytes/sizes/mtimes unchanged |
| Docker/service acceptance | Not applicable to this offline design tool; no runtime behavior changed or service acceptance claimed |
| Real completed study issuers | **0/100**, 589 targets retained; threshold **null** |

External evidence root:
`/Users/denniswong/Desktop/Project/value-investment-agent-issue-376-research-evidence/checkpoint-d8d69404`.
Exact commands, exits, stdout/stderr, Python/Decimal/normal-quantile pins and
input/output identities are retained in verification report
`c3b2b4b239a7ffb1564f098b38c1f4853a55adc2f11e044b0e100deb03915cfb`,
input `87a269992381f059f718f2c317ce5f9b1291914898017e0dc07b5c16fe3db629`,
output `51c9ec3f2bf0b8c08e165708d3b83145cab766bf4a38e7cd12986cd175a555d1`.
The external reproducible driver is `references/issue377-precision-verification.py`.

Planning report
`01b6dd7dfa433957fade38d4b189fc0da8c2cc7689abe1ca61dacbe8cab55af9`
has input `38af7724431980c4d4a2179da6b4c0dd8c02e311827cc50ae9db16e64cbb6251`
and output `8942630cbbc0ce33881712a58990186fde61d72e11cfd20c9cffee4d9076066e`.
The two commands use the literal exact implementation SHA, checked-in proposal
and the same external output directory, with Python 3.11.15. Concurrent repeats,
corruption, interrupted publication and output-through-symlink boundaries also
pass. The script performs no network, SEC parsing, signing, snapshots or forecasts.

Still required: actual protocol review and business justification for proposed
numerical limits; a justified prospective variance or reviewed precision-based
replacement for the infeasible legacy gate; pinned simultaneous-inference and
missingness methods; source-bound NEWMARKET working-capital/capex evidence and a
trusted release; real #352 forecast/first-original label/error/repeat and full
fixed-cohort execution. Estimated labels cannot silently become observed ground
truth. #376/#377 remain open; this increment remains draft pending review/CI and
integration. No full study, powered result or supported threshold is asserted.

## Executable inference checkpoint

Issue #377 / parent #376, implementation
`004540004ee5d23ec0b3f27ede106f0c84bc41c0`, branch
`codex/issue-377-precision-protocol`, PR #417 to the #361 integration branch.
An ordinary merge brought in parent `8633ff44`; previous WIP commits remain.
The [v4 methods](../research/issue-377-executable-methods.md) implement paired
issuer resampling, the 32-hypothesis common-3/4/5 family, raw/scaled denominators,
degeneracy refusals and explicit missingness identification limits. They are
exploratory methods, not an approved promotion policy. Previously seen NEWMARKET
conditional outcomes are not relabeled as prospectively registered exact data.

| Exact implementation check | Result |
| --- | --- |
| Planning and analysis tests | **58 passed**, including full 100,000-replicate algorithm execution and an independently enumerated paired distribution |
| Ruff 0.14.10 / format | All four issue Python files passed |
| mypy 1.19.1 | Both research scripts passed |
| Architecture / diff | Both guards and `git diff --check` passed |
| Fixed original manifest | Digest checked; all 100 issuers / 589 targets retained; missing originals and horizon mismatch cannot carry scored losses |
| Two fresh-process analyses | Same input/output/report digests; repeat `wrote=false`, zero new files; bytes, sizes and mtimes unchanged |
| Real exact errors measured | **None**: the absence of an authenticated exact-loss panel is explicit in all 1,200 cells; NEWMARKET conditional references retained separately |
| Actual cohort bootstrap execution | Zero replicates, because no common exact-loss cases exist; the 100,000-replicate probe is explicitly synthetic |
| SEC acquisition, release and Docker | No download, signing, publication or DB writes; this offline tooling change does not establish service/ingestion acceptance |

External root:
`/Users/denniswong/Desktop/Project/value-investment-agent-issue-376-research-evidence/issue377-methods-v4/checkpoint-00454000`.
The reproducible driver is its parent directory's `verify.py`. All nine command
receipts include full commands, exact commit, input/output digests and exit zero.
It uses Python 3.11.15 from the existing Fundamental environment with source
imports explicitly pointing at this worktree. No parent checkout, trust, DB or
Docker resource changed. Historical data, panels and complete reports are external.

| Evidence | SHA-256 |
| --- | --- |
| Verification report | `8689b05a730c2e099202af19391916debf1dd429972876d97f5bb153b06803f9` |
| Verification input | `8aa108b6975bdac9121864d6795353122eae081a16e37d4199a364d8424a2cea` |
| Verification output | `ee60f2c2d9ed1f85a0d91e3e9a7796cddd002649d162be1f285aba869460e871` |
| Fixed-manifest analysis report | `d01865ed876f866d7a1ce343543b06f4325a1a0acdb508e8c21a38819e2a9c9f` |
| Analysis input | `a3af2422c98f48c7837286321f103937088e5b24b060940c1b338a069a695e25` |
| Analysis output | `0926e67b720d0d1e26d6891cd0db923b900e96df245c60c9ccba4541c8034bc8` |

Remaining: independent method/business-margin review; explicit approval of any
precision-based replacement for the infeasible legacy sample gate; authenticated
loss-panel generation and real cohort execution; main-branch delivery and final
acceptance. The old gate is unchanged. Complete exact study cases remain **0/100**
and `supported_history_threshold=null`. Main chat owns independent review and
serial integration; #377 stays open and #417 remains draft until its actual
accepted delivery scope passes review. No finite-sample interval guarantee,
prospective power or threshold promotion is claimed.

### Report interruption follow-up

Final tested implementation:
`be0fabbcba6cfb4a84c9c3f77d7e710a5b74cf17`. The previous checkpoint remains
retained. A regression test first reproduced an orphan temporary file when
`fsync` failed (one failed, one passed). The publisher now covers the temporary
write, flush, synchronization and rename with the same `finally` cleanup.
Both synchronization and rename failures leave only the lock file; retry writes
once and then reuses the report. The failure log remains external as
`issue377-methods-v4/fsync-regression-before.log`.

All **59 tests**, four-file Ruff/format, both-script mypy, both architecture
guards and diff pass at this exact commit. The complete two-process fixed-manifest
analysis again has `wrote=false`, zero new files and unchanged bytes/sizes/mtimes.
The statistics output digest remains identical to `00454000`; report/input
identities change because the implementation and publication tool changed.

External directory: the same evidence root's `checkpoint-be0fabbc`; reproducible
driver `verify-be0fabbc.py`. All nine commands exited zero.

| Final evidence | SHA-256 |
| --- | --- |
| Verification report | `ef00745ed13abd8fe1596c2a50ad7e2f6c79f2e5c802b24b12f12d063b7eed20` |
| Verification input | `e38f91ba1c235a105aadfcf4cd10049fe879ddeb6d86f37d3098b6a02bef2231` |
| Verification output | `bf7f60bc6f852df59fe467a8a95af88c755e1d4c99359f637423318412b0fec0` |
| Analysis report | `e199ef314392b067c850eaeda0c83ce687f8a23dab3fe4c51950c12ee03132b1` |
| Analysis input | `b91de8d3acfbeb0ff5da3f9ea2ac8234cf8090cdebb8dd4c6b05fd46617ebda9` |
| Analysis output | `0926e67b720d0d1e26d6891cd0db923b900e96df245c60c9ccba4541c8034bc8` |

The study/review/authority limitations above remain: no exact case or threshold
is produced by this interruption repair.

## Formal conditional evidence adapter checkpoint

Issue #377 / PR #417, branch `codex/issue-377-precision-protocol`, worktree
`/Users/denniswong/.codex/worktrees/issue-377-precision-protocol-local/value-investment-agent`.
Verified implementation: **`43d7469515a760a0389db33ba8d767d1bb3328be`**,
following `6a8f5c14`. Ordinary merge `92dedde1` brought in parent `ee4fea7c`
without rewriting existing WIP. The following commit contains acceptance metadata
only. This is a validated offline conditional adapter, **not completed #377
research, a trusted release or threshold approval**.

The new CLI recomputes formal scenario and conditional label/error outputs and
requires their complete canonical bytes to match the frozen artifacts. It
retains complete source/mapping/assumption/model/policy lineage and all refusals,
then exports the fixed 100-issuer / 1,200-cell panel plus a conditional appendix.
It implements no financial formula. See
[`issue-377-evidence-adapter.md`](../research/issue-377-evidence-adapter.md).

| Acceptance at exact implementation | Result |
| --- | --- |
| Adapter + methods/planning + official scenario/label tests | **112 passed**, including 22 adapter tests |
| Ruff 0.14.10 / format | Six scoped script/test files pass |
| Mypy 1.19.1 | Three scripts pass |
| Root and Fundamental architecture guards | Both pass |
| `git diff --check` | Pass |
| Real fixed NEWMARKET 2016 formal replay/export | 125 conditional labels; 625 FCFF comparisons; 625 Transition abstentions; one independent issuer |
| Export and analysis, two offline fresh processes each | Identical input/output/report digests; all second publications `wrote=false` |
| Source and output inventory comparison | Zero new second-run artifacts; existing bytes/sizes/mtimes unchanged |
| Wrong exact commit | Expected CLI exit 2; no new artifact |
| Exact study / actual cohort bootstrap | **0/100 exact cases; 0 cohort replicates; threshold null** |
| Docker / service / acquisition / trusted release | Not claimed; offline adapter changes none of these boundaries |

All 11 positive acceptance commands exited zero; the wrong-commit probe exited
2 as expected. Commands and full results are retained in the verification report.
The first CLI attempt at `6a8f5c14` failed because strict Python-mode validation
rejected JSON arrays. Its command receipts remain in `checkpoint-6a8f5c14`.
A new CLI regression reproduced the failure before `43d74695` switched the
owning boundary to JSON-mode validation, preserving duplicate-field checks.

Canonical runtime: CPython **3.11.15**, Darwin arm64, Pydantic **2.14.2**,
Arelle **2.47.4**, cryptography **50.0.2**; `uv.lock` SHA-256
`229bc76c75019d54df8c1cba240839bacf01e56d7493f4bc615e058c4e5f6f11`.
The existing interpreter was reused with `PYTHONPATH` explicitly selecting this
checkout, bytecode disabled and fresh-process network calls disabled. No parent
checkout, `.env`, keys, configuration, database or Docker resources changed.

External evidence root:
`/Users/denniswong/Desktop/Project/value-investment-agent-issue-376-research-evidence/issue377-evidence-adapter/`.
Driver: `verify.py`; complete reports/inputs/command receipts:
`checkpoint-43d74695/{inputs,commands,export,analysis,verification}`. Historical
documents, original parsed reports, frozen inputs and generated outputs stay
outside Git. Only code/tests and compact methods/acceptance documentation are
committed.

| Evidence | SHA-256 |
| --- | --- |
| Verification report | `639fb65e1d8809cfa1c4466c5050bb476811464d6ad7dd3112a08967ee1a9422` |
| Verification input | `b3e4484c71c640a4af741aee532bd5b6487e0440a0cf5f838e7b3c9d6e0f248c` |
| Verification output | `d60d7e3f3ddeaa80872d457035f0604394a55ec9f0a35f7eeaae8e1fc56c567f` |
| Export report | `731ef79e4487f7b10e6d34b892914387c0740b0c384a057c75a91d9638a50be3` |
| Export input | `54eba6e16109f1d6d26eea0014ec9c6315c7cfb988ebaa861d9dfbfaf3c55c0d` |
| Export output | `1b96eaf0587333a6679ed33ee0fb13a9fc74be56156a89795a9495067de71185` |
| Analyzer panel | `c08ca5f05248a2976dfb852b59f62f93c1a4e07d2089fa571373097118b11ebf` |
| Analysis report | `2e092ba872023e6f234d0747e805f455a351fd81da554734b3e61312e6935532` |
| Analysis input | `beab378c4fbc4a3867900f3ba3a6dec6dad0c26ef991a44d22338a0895bf1320` |
| Analysis output | `1fb66f9f0f83a1bb0a192205813abb6ed750d1112bf9c5da476db4ede85c3fe2` |

Remaining: independent main-chat review and serial integration; authentic exact
release/label evidence; four/five-year histories; missing accounting/Transition
evidence; reviewed primary policy, precision and promotion criteria; the full
fixed-cohort empirical study. Conditional scenario dispersion is not sampling
uncertainty and cannot replace these gates. #377/#376 stay open and PR #417 stays
draft pending that work.
