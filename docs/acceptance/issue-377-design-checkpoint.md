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
