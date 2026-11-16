# NEWMARKET conditional Transition evidence (#376/#383)

Implementation `596f75f3af26f13377ed8b4f8fa092382ff3979c`, branch
`codex/issue-376-transition-evidence`, starts from integration checkpoint
`6f01c8980bb1f3daf2a7e8c17a3c914f8d192d37`. This increment completes a real
source-bound **conditional** dual-model forecast/label/error/repeat. It does not
complete the original reviewed, trusted-release-bound exact study. Independent
review, serial integration and parent delivery remain required. Keep
#376/#377/#383 open and `supported_history_threshold=null`.

## Source and authority

The fixed NEWMARKET CIK is `0001282637`; the unchanged origin is
`2016-02-12T16:26:17Z`. Decision original `0001282637-16-000028` contains the
2015 consolidated `us-gaap:ConsolidationPolicyTextBlock` and
`us-gaap:SegmentReportingDisclosureTextBlock`, context `FD2015Q4YTD`, annual
period 2015-01-01 through 2015-12-31, with no dimensions. Both original XML and
pinned parser-input XML reproduce each retained parser string exactly. Their
verbatim UTF-8 text digests are respectively
`1c26bed569fa92a7ee33d3e5d50c1ccb8683999513dde2ddfdf5a47e272d5a32` and
`2b9b84fd59ed0279b35e55037475ae38754deedb9789c7f4bac613ffa42b9db7`.

Raw source digest:
`06be302baf2ecf9ff95ab87243df1f2a1cd63e9ababc969b89c4764be794e380`.
Parser-input digest:
`90b1f0fddb61415dab858235894745b2c2808ee598ac0594b0a28010b808e14c`.
The existing numeric source, mappings, decision periods, 625 scenarios and first
subsequent original `0001282637-17-000005` label remain unchanged. No source is
downloaded or snapshot published by the compiler/replay. Original capture gaps,
parser findings and earlier refusals remain retained.

The shared SEC mapper preserves two observation-scoped provisional text facts;
the compiled request contains 71 facts and 39 mappings. It records accession,
period, availability, context, raw/parser/observation hashes and mapping identity.
The optional `fundamental.conditional-transition-disclosures.v1` pins the
`unreviewed-filed-operating-disclosures-v1` policy, digest
`900c5a78cb8f9ec85b32dc4cc7507e16b7e8d9c37cae36b5abe480d072e0ed51`,
and two selected fact IDs. Absent opt-in preserves previous request identities
and Transition refusal. Released preparation still rejects provisional evidence.
Text supplies a filed source reference only: no numeric operand, accounting
approval, reviewer signature or model-suitability claim is introduced.

## Measured conditional result

Both registered models, `fcff_dcf-v2` and `transition_fcff_dcf-v2`, execute through
the existing #352 composer and shared operating graph. Their arithmetic agrees
for identical scenarios. They are not independent predictive methods. Transition
adds source lineage and retains `TRANSITION_DISCLOSURES_UNREVIEWED` and
`MODEL_SUITABILITY_UNESTABLISHED`.

| Result, for each registered model | Three years | Four years | Five years |
| --- | ---: | ---: | ---: |
| Fiscal years | 2013–2015 | 2012–2015 | 2011–2015 |
| Provisional forecasts | 625 | 625 | 625 |
| Conditional paired FCFF errors | 3,125 | 3,125 | 3,125 |
| Sampled forecast range, USD m | 173.32–191.31 | 187.41–231.68 | 196.58–243.25 |
| Sampled signed-error range, USD m | −182.55–24.60 | −161.09–57.60 | −155.41–72.65 |

Each arm retains the same 125 conditional realized-FCFF labels, sampled range
USD159.28–363.30m. These are comparisons under explicit unreviewed working-capital
and continuing-capex allocations. Ranges are sensitivity results over the frozen
sampled scenarios, not exact ground truth, global bounds or confidence intervals.
Scenario/error rows do not increase the independent issuer count beyond **1**.
Exact study cases remain **0/100**. No three/four/five-year ranking or threshold
approval is inferred.

The fixed loss panel retains all 100 issuers and 1,200 model/target/window cells:
1,194 missing and six abstained scalar cells. The conditional FCFF ranges are
retained as evidence without substituting them for exact loss observations.
The other 99 issuers, missing annual labels, horizon failures and refusal reasons
remain visible. The exploratory #377 v4 protocol disables promotion.

## Exact-commit checks and repeat

At `596f75f3`, the full Fundamental Service/PostgreSQL suite passes:
**2,609 passed, 17 explicitly skipped**, one intentional duplicate-ZIP warning.
Skipped tests require configured SEC EFM/DQC or original historical runtime
resources; no live SEC validation claim follows from this run. The 22 new tests
cover scoped text, full-path refusal, opt-in execution, unchanged FCFF arithmetic,
lineage, old identities, duplicate/missing/foreign/future/dimensional/numeric or
tampered evidence, invented reviewer and policy substitution. Pinned Ruff
0.14.10, format, source-aware mypy 1.19.1, both architecture guards and diff
checks pass.

An initial full run reused another worktree's editable installation: 2,608 passed,
17 skipped, one installed-CLI boundary failure. Its entrypoint invoked the older
worktree's plan schema. After `uv sync --frozen --project fundamental-service
--extra dev`, the entire suite passes using this checkout's installation. The
failure record is retained separately; no production validation was loosened.
Wrong exact SHA and malformed seed controls both exit 2 before output creation.

The desktop driver runs the compiler, fixed-window replay, evidence exporter and
analysis twice in fresh network-blocked subprocesses. Stage digests and failure
classification match, every second publisher returns `wrote=false`, and no file
is added or changed in bytes, size or mtime. Publications use the existing
content-addressed locked temporary-file/fsync/atomic-rename writer. Generated
originals, reports, mappings, requests, drivers and command receipts remain
outside Git under
`/Users/denniswong/Desktop/Project/value-investment-agent-issue-376-research-evidence/transition-evidence/`.

## Isolated Docker runtime

Worktree:
`/Users/denniswong/.codex/worktrees/issue-376-transition-evidence/value-investment-agent`.
Own Compose project: `value-investment-agent-376-transition-evidence`.
Ordered file list: external `transition-evidence/compose.json` only; no env file,
application stack or browser session. Host bindings are localhost15786/PostgreSQL
and localhost18786/Fundamental, subnet `10.247.86.0/28`; named volumes are
`value-investment-agent-376-transition-evidence_postgres-data` and
`value-investment-agent-376-transition-evidence_fundamental-data`.

Image `sha256:1e522b6861a5c6dff86b37aafbc713f6601c1c9a77a6d2125c5b4070a1f853ba`
reuses the already-built frozen-lock baseline image with this exact source
overlaid under a new tag. All 123 installed Python/SQL files and the lock equal
the checkout. Both services became healthy and `/readyz` returned 200 with
`identity_resolution_configured=false`. This is offline service/runtime
acceptance, not SEC acquisition, trusted release or full valuation readiness.
Development trust fixtures provide no actual accounting review authority.

Two fresh workers, network `none`, one CPU and 2 GiB each, execute compile,
three windows, forecast/label/comparison, export and analysis successfully.
Installed Service code is imported from `/app/src`, not a host source override.
All nine financial request/forecast/comparison artifacts match desktop bytes.
Both exit 0 without OOM; peak RSS is 1,039,536 / 1,039,368 KiB. The second worker
returns `wrote=false` and preserves artifact inventory/bytes/sizes/mtimes.
Container pins: CPython3.12.16, Pydantic2.14.2, Arelle2.47.4, cryptography50.0.2,
xlrd2.0.2. Desktop pins: CPython3.11.15, arm64/Darwin, with the same recorded
Pydantic/Arelle/cryptography versions and frozen lock. Runtime-bound report
digests need not agree across platforms.

Workers are removed after capturing their state. Own services are stopped after
runtime proof; own volumes/image/network/checkout are retained for review and
scoped post-integration cleanup. No foreign Docker resource is mutated. Baseline
inspection observes 63/65 pre-existing containers unchanged; two concurrent
parent-project container IDs became absent. No universal unchanged-state claim
is made for concurrent parent work.

## Evidence identities

Each report has canonical bytes and a SHA-256 filename outside Git. Full command
arguments, exit codes and input/output digests are in the referenced reports.

| Evidence | Digest |
| --- | --- |
| Fixed cohort manifest | `448f496b10e51a2ed351a7a37deb36e0d4b9672c1fbc5ed3b0b845c8cd54da3a` |
| Frozen seed | `6343482f039c782fcb7f00a1bb364802f556429786d9b1327bbed31dea576a13` |
| Compiled comparison request | `f1803642df0e86d62503a86a2edc7805b6c13449b2e9607f00320fa77ca42f21` |
| Source/mapping audit | `da16d4f9ba4aaf838e3ff9e50d8dd10647bfea819244b5cfd17d2e4d3eb37642` |
| Raw XML/parser text equality | `47242ba43d7e4336c1ce9c6eb898a9519462f0471b4352257acb6b51c5a374d7` |
| Full tests/static/failure retention | `fce294bc42502904bb3cb92dc4f32a60c4a34f850352800e73da7e6d162d320c` |
| Wrong-SHA/corrupt-seed controls | `1f349083b9a0c9db4e138dcf5678b8979e14889b3211f3dd2c3df344fa613d39` |
| Desktop full repeat proof | `cf2698408e98d66aafaa798e9707ecbecb8c9e6f092e4647b75da57c5756c1cc` |
| Conditional model/error comparison | `27a60b10fe4de820d8ca31ebb62d628dddb5aea40bf5fa4f375efa3107746b7b` |
| Container stable computation | `a22d599c8ffdcb619169ced5fd3b8fc151c7235b7f434e44c5dcce28cd075d5b` |
| Container full repeat proof | `88fc7b0fc910de4f7a0d2129784473ba2bab6f648bc9c06f6ae8020bd6387f07` |
| Installed source/runtime/ownership | `bec4bcde925b33559890299dc32863a99d25d9592134d7d514c9daed4970ba74` |
| Docker baseline and scoped stop | `8e68cd19bca6aa85d2fb2d1500f34555254ca6e3971f0455c2fc25f3a11ccae5` |

Desktop repeat input/output:
`bce270541c28468e1447cf74e2d678d56a1eb6ef201346ccaa4ace38990c6786` /
`ac15a5251bb8736fa89a092a845394c9548b661e5adb2ee2876a54e652eeaf81`.
Container repeat input/output:
`d487b84fd1e5f1958f69c19544a1111c95a33833168ec85e7751361a61143ea3` /
`b6edd136c3334a9aedfbb2b5ddf9e4c5588c0d81799b10c8e39ec8d9aaecd268`.

Reproduce with the external `verify_replay.py` using `ISSUE376_WORKTREE`,
`ISSUE376_EVIDENCE`, `ISSUE376_OUTPUT`, and `ISSUE376_COMMIT` set to this exact
implementation. `verify_container_repeat.py` checks the clean host commit and
launches both bounded workers; `verify_runtime.py` checks source, readiness and
resource ownership before scoped stop. `verify_checks.py`, `freeze_checks.py`,
`verify_original.py`, `verify_negative.py` and `report_results.py` retain the other
command and source comparisons. Restore service health with the exact recorded
Compose file/project before repeating runtime acceptance.

Next delivery gates: independent diff/evidence review, PR CI, serial integration
and merge-commit checks. Exact accounting allocations, trusted reviewed release,
broader cohort coverage and a prospectively approved adequately powered #377
study remain separate research gaps. This one conditional case does not satisfy
threshold approval or issue closure criteria.
