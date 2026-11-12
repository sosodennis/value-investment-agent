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
