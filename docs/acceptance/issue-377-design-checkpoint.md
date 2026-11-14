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

## Cost-aware external calibration checkpoint

Issue #377, documentation commit
`4114a83c0ea9796aabe1f584b70a46eca1eb9b5e`, follows `91c1caee` without
rewriting WIP. The [cost-aware evidence choices](../research/issue-377-cost-aware-evidence.md)
record practical alternatives for the accounting, capex, Transition, label, and
history gaps. They support review of the bounded conditional adapter while exact
research remains incomplete. No executable method, tolerance, sample gate,
financial formula, trusted release, or promotion policy changes.

Eight primary method references returned HTTP 200 and have cached content
snapshots outside Git. Their scope includes scenario feasibility, rolling-origin
evaluation, scaling, dependence, bootstrap limitations, historical DQC profiles,
and proportionate model validation. They provide no numerical promotion approval.

Command `python3 -B /Users/denniswong/Desktop/Project/value-investment-agent-issue-376-research-evidence/issue377-external-calibration/verify.py`
exited zero in two fresh processes at the documentation commit. Six local links
resolve; five implementation/protocol files are byte-identical to verified
`43d74695`; both recorded Git checks pass. Cached validation downloads nothing.
Identical source/report publication returns `wrote=false`, creates zero new
second-publication artifacts, and preserves existing bytes, sizes, and mtimes.
These are documentation/source-cache checks, not new financial replay acceptance.
Prior financial test evidence remains bound to `43d74695`.

| External evidence | SHA-256 |
| --- | --- |
| Source retrieval report | `0807a36d83b6b412547f2320cfe4414c677c705f5d8bf6876c3677305ea78b1e` |
| Source retrieval input | `8e50dc4214f24b058b28779f6b02ee08ec70d1c3437c7529baf9e785c4f48112` |
| Source retrieval output | `72f40c9ddb4eed796ae8043c808f8ea9233b57e6788a42f873c3ed0a4763d951` |
| Documentation/cache verification | `c2a9b906e5f8e4d08bd5c5f7e547860d962d72325def16de150aa84bf8fc2563` |
| Verification input | `94f5d2735d76bc0d05ea1dce6dee2c6259e366e934ef2eebd7517fc409b2a427` |
| Verification output | `ccd844a6cf84312a9051399643c9d46e3358d8d50d739c4a6bfd240d45aace76` |

Evidence root: the external `issue377-external-calibration` directory linked in
the research document. The reproducible driver retains full Git command results
and source inventories. Raw sources and generated reports remain outside Git.
Remaining: independent main-chat review and serial integration; reviewed methods
and acquisition choices; exact evidence and the fixed-cohort empirical study.
Exact cases remain 0/100 and `supported_history_threshold=null`.

## Conditional window compiler checkpoint

Issue #377 implementation `638c5df2faded9e722f4eec738a5de3b79f87102`
starts from integration `719a238f` and preserves every previous checkpoint.
Branch `codex/issue-377-history-window-evidence` uses isolated worktree
`/Users/denniswong/.codex/worktrees/issue-377-precision-protocol-local/value-investment-agent`.
The [window replay tool](../../scripts/replay_history_study_windows.py) retains
common source/mapping/model/label identities, prevalidates generated arms with
the reviewed exporter, and uses the existing atomic content-addressed publisher.
There are no service schema, formula, database, trust or Compose changes.

Exact-commit command:
`PYTHONDONTWRITEBYTECODE=1 /Users/denniswong/.codex/worktrees/issue-376-aggregate-noncash-working-capital/value-investment-agent/fundamental-service/.venv/bin/python -B /Users/denniswong/Desktop/Project/value-investment-agent-issue-376-research-evidence/issue377-history-windows/verify_windows.py`.
It exited 0. Its external command receipts bind the full argv, exact SHA,
runtime, seed identity, exit code, stdout/stderr and input/output digests for
14 commands. The wrong-SHA negative command intentionally exits 2 before output
publication; the other 13 commands exit 0.

| Exact implementation check | Result |
| --- | --- |
| Window, evidence, precision, analysis, scenario and label tests | 120 passed |
| Ruff 0.14.10 / format | Both changed Python files pass |
| mypy 1.19.1, imports resolved against Service source | New production script passes |
| Root / Service architecture guards; Git whitespace | All pass |
| Real three-year NEWMARKET arithmetic | Request, forecast and comparison bytes equal the reviewed #417 inputs/outputs |
| Fresh-process window → export → analysis repeat | All three report/input/output digests identical, all second writes false |
| Output inventories | Windows 5 JSON artifacts; export 2; analysis 1; persistent publication locks separately retained |
| Second pipeline artifacts/downloads/parses | 0 / 0 / 0; bytes, size and mtime unchanged |
| Source inputs | All three pinned original request/forecast/comparison files unchanged |
| Publication interruption behavior | Tested recovery reuses the completed artifact and preserves its mtime |
| Docker / live service acceptance | Not claimed for this offline-only tool; shared resources were not modified |

Runtime: CPython 3.11.15, Darwin arm64, Arelle 2.47.4, Pydantic 2.14.2,
cryptography 50.0.2; lock digest
`229bc76c75019d54df8c1cba240839bacf01e56d7493f4bc615e058c4e5f6f11`.
The manifest remains
`448f496b10e51a2ed351a7a37deb36e0d4b9672c1fbc5ed3b0b845c8cd54da3a`.

| External artifact | SHA-256 |
| --- | --- |
| Exact verification | `9f88315abf397fb5805e30c89fa830cc95b0fc5f5ac1bc965a8ba7358e6275a1` |
| Verification input / output | `47466ee1381c749f89196b14062a1ac8232d6c8407b9366361a57c7ee0e513c6` / `6b315c11726c79d73a0e3609d839cf1906c05a95f2168a22025d7cbe4a2bd5f6` |
| Window replay report | `7c25211ff92ea90adad83f58990483255d91f55f1a094882201205d520208def` |
| Window input / output | `56617ab04e1069ebf60c65154f1a652c1caea9040d285dd7326af0d8dd366b45` / `5ebefbb878022911e6989ae8500649b7c84ad49e50dd71b5f0f4cd973e1e3281` |
| Generated evidence index | `9928572738be6bc677b34785e8d20f498b30220ed451e43c17500ca39bb33479` |
| Formal evidence export | `25ead3b405a011b1d2f25e295992c50f90cc5fc9915d6081d49907f26cdf0edb` |
| Export input / output | `26b619332ac3ab04c15b5ebdcbc3c4c85298f2dbb899d13a64378d13fe235b69` / `1b96eaf0587333a6679ed33ee0fb13a9fc74be56156a89795a9495067de71185` |
| Exploratory analysis | `d4e2011856592c9a605509d3b20bb80adf14b68af637cec654d67cf9377c05a4` |
| Analysis input / output | `b26002c3e77ae8ea5cb3fac22496d0d860cd90379894f85ae7a1afd1533d87be` / `1fb66f9f0f83a1bb0a192205813abb6ed750d1112bf9c5da476db4ede85c3fe2` |

The fixed panel retains 100 issuers / 589 filing targets / 1,200 cells. Actual
conditional evidence remains one issuer, 125 labels, 625 FCFF comparisons and
625 Transition abstentions in the three-year arm. Four/five-year windows remain
unavailable. No exact case, sampling uncertainty or promotion authority was added.

Four-year investigation at source commit `719a238f` acquired three SEC HTTP200
responses and parsed direct/archive XML offline with the same retained archive
DTS. Both retain 2,508 facts, identical semantic digest and all 48 DQC1 errors.
Parser report `0a63bed54906b12523de47dc370e189ff9f0ca7273a531eb86054b7a627c9eed`
reuses unchanged with zero parser calls. Nine source/period mapping proposals
all retain `PARSER_VALIDATION_BLOCKED`; audit
`9d2e882d38355918599a8f821673d27688075e8bc8435b2e61daea4dda91a4df`
reuses with `wrote=false`, input
`9f01a81daf9a833e673a334c5e8c4e8119d178196831056c23c99e5d6b888e79`,
output `02d89d4187392d60f30038fe45ca6056b6e95a6c2f66e5659ffe3e2dfc569276`.
The capture repeat disabled network and preserved all retained bytes and mtimes.

[Linked blocker #371 evidence](https://github.com/sosodennis/value-investment-agent/issues/371#issuecomment-6840878314)
records the observed generic rule configuration fallback for the 2013 taxonomy.
The [official rule guidance](https://github.com/DataQualityCommittee/dqc_us_rules/blob/cafb54391c1d21e4c219bc3d491b855a9b877cb6/docs/DQC_US_0001/DQC_0001.md)
was also retrieved HTTP200 (digest
`b3a0190d198cdbeaa965b20fc58ed4a80c0d0a00b7b2cd52521eb291778b1827`):
it states release September 29, 2016 and effective March 28, 2017. Its date and
the member's existence in the 2013 schema do not prove that the reported
axis/member combination is valid. Validate applicability and original taxonomy
relationships in the parser layer; no severity, engine or profile was changed.

Evidence root:
`/Users/denniswong/Desktop/Project/value-investment-agent-issue-376-research-evidence/issue377-history-windows/`.
Generated reports and historical sources are outside Git. Failed exploratory
attempts remain recorded: content-store path lookup, ambiguous dimensional D&A
selection, fixture import lint, publication-lock counting in the new recovery
test, and a missing explicit GitHub repository argument. Corrected runs preserve
source/refusal semantics.

Next: independent review and serial integration of this bounded tool; resolve
#371's per-rule historical compatibility evidence before producing the four-year
arm; resolve 2011 source/scope gaps for five years. Primary policy, precision and
promotion review, complete accounting/Transition evidence and the fixed-cohort
study remain incomplete. Keep #376/#377 open and `supported_history_threshold=null`.
