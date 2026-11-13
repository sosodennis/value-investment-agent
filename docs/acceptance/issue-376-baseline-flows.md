# NEWMARKET five-year conditional history (#376/#377)

Implementation `a016e0f9f65875981a8e006b848b10a8cc3db299` follows policy checkpoint
`6c6fb7f0266817b3d0fb05b77f952135204fd416` on
`codex/issue-376-baseline-flows`. [PR #435](https://github.com/sosodennis/value-investment-agent/pull/435)
targets the #361 integration branch. Desktop and isolated-container replay
acceptance pass; independent review and serial integration remain pending. This is an incremental conditional study;
#376/#377/#425/#433 remain open for their accepted main outcomes.

## Behavior and scope

The explicit `baseline-unconsumed-capex-v2` policy represents unknown PPE capex
only in the earliest decision period, where #352 does not consume that amount.
It creates no numeric amount, zero, canonical fact or allocation. The versioned
baseline source policy selects complete core flows and complete working-capital
stocks from their respective latest eligible originals, requiring one original
within each family. Later periods and every conditional label keep their strict
observed-capex and same-original requirements. Full valuation, mapping review,
trusted releases, caller approval and model versions retain their existing gates.

Fixed first case: NEWMARKET CIK `0001282637`, origin
`2016-02-12T16:26:17Z`, fiscal years 2011–2015. The 2012 original provides 2011
stock balances; the retained 2013 original provides the already-available
continuing-basis restated flows. Original gross flows, historical parser refusal,
DQC findings and capture-receipt gaps remain in the source audit. Broader
`PaymentsToAcquireProductiveAssets` never becomes PPE capex. Eight additional
mapping proposals produce 69 provisional facts and 37 mappings across four
originals; they grant no accounting or publication approval. All 625 parent
scenarios survive without an invented baseline-capex dimension.

The first eligible subsequent original annual filing
`0001282637-17-000005` stays label-only. Its 125 conditional label scenarios
are unchanged. Comparisons use the existing paired allocation rule, preserving
all model refusals. Sampled ranges are conditional on explicit unreviewed
working-capital/capex assumptions, not exact ground truth, global bounds,
confidence intervals or evidence that five years is preferable.

| Result per arm | Three years | Four years | Five years |
| --- | ---: | ---: | ---: |
| Fiscal years | 2013–2015 | 2012–2015 | 2011–2015 |
| FCFF provisional forecasts | 625 | 625 | 625 |
| FCFF conditional comparisons | 3,125 | 3,125 | 3,125 |
| Transition forecast abstentions | 625 | 625 | 625 |
| Transition comparison abstentions | 3,125 | 3,125 | 3,125 |
| Sampled forecast range, USD m | 173.32–191.31 | 187.41–231.68 | 196.58–243.25 |
| Sampled signed-error range, USD m | −182.55–24.60 | −161.09–57.60 | −155.41–72.65 |

Transition retains `TRANSITION_EVIDENCE_MISSING`. Independent conditional issuers:
**1**. Complete exact study issuers: **0/100**. All 100 issuers and 1,200
model/target/window panel cells remain, including nine missing original labels,
one horizon mismatch and original refusal reasons. The #377 v4 protocol remains
exploratory; promotion is disabled and `supported_history_threshold=null`.

## Exact-commit verification

At `a016e0f9`, **2,541 Service/PostgreSQL tests pass**, 17 tests explicitly skip
because specified SEC/historical resources are absent. Pinned Ruff 0.14.10,
format on 12 changed Python files, source-aware mypy 1.19.1 on nine source files,
both architecture guards and `git diff --check` pass. Tests include v1 exact
request/forecast/comparison digest regression, strict later-period and label
refusals, source-family selection, failure retention, interrupted publication and
identical-input reuse. [CI 43409860847](https://github.com/sosodennis/value-investment-agent/actions/runs/43409860847)
passes all 12 executed jobs; release gate explicitly skips.

The desktop driver executes compile, window replay, export and analysis twice in
fresh subprocesses with network connections blocked. Second-run stage digests
match, all publishers return `wrote=false`, zero files are added, and existing
bytes/sizes/mtimes remain unchanged. All nine canonical request/forecast/comparison
artifacts also match the earlier `6c6fb7f0` bytes. The orchestration improvement
holds canonical bytes rather than simultaneous decoded copies, then decodes one
artifact at a time for the unchanged atomic publisher. No output schema or
financial artifact identity changes.

Generated originals, mappings, full numeric panels, drivers and command receipts
stay outside Git at
`/Users/denniswong/Desktop/Project/value-investment-agent-issue-376-research-evidence/baseline-flows/`.
Each report below is identified by its canonical SHA-256 filename.

| Evidence | Digest |
| --- | --- |
| Fixed cohort manifest | `448f496b10e51a2ed351a7a37deb36e0d4b9672c1fbc5ed3b0b845c8cd54da3a` |
| Baseline source/mapping audit | `7e67652af7f469e3c97eb4d645542bebb3c455112c84a3e37563195f9c3b27b2` |
| Typed v2 extension | `efc8f0d7d4d60e815d0c87680774d1001c4ee7c0a7b5e9aedf32e3257d27f6e7` |
| Compiled five-year request | `6343482f039c782fcb7f00a1bb364802f556429786d9b1327bbed31dea576a13` |
| Mapping manifest | `01e68751a0fe4f35d80559e15c183a3bbc9b1a339c02124a92c858d81da2eed2` |
| New research input policy | `4a70aa29f160705053c958a23dc25dbc0e35188554d55358e40d1671ce0c4fe8` |
| Exact checks report | `0e5cbeaa62e72b59ea841b89347ff354fb5e3c415ba9a72ddb2e4ba994700165` |
| Desktop full repeat proof | `61d620c37b389687de79d74c23e05fa97c8956297759498f753263bb6eda691d` |
| Container full repeat proof | `0d3f836554b3aa5e0265f4bce2f76309525b156b0368cbc9dd551efd0b957872` |
| Installed Python/SQL source comparison | `2645c22cbaa73f3d7a00f87a2181f7a7af6ec17b647a3335dbaeceb386fa2795` |
| Final runtime/readiness/ownership proof | `93be98edc8c045d18354d120e4d94f22b18c05429708badb5edc25c291263a5c` |

Checks proof input/output:
`b542b66350e59716410a4dd6e2984d760f2575da54ac3a9a7ebf612deb637cc6` /
`80212d12498737130f7f02acc205efbf6e3792418b8ab594e1ce9e1a49a7e1ad`.
Desktop proof input/output:
`7b1b3e73809509c9698d08167e57ece38534830a4a3599c12ef7abf1caf6f89e` /
`70080749039eff62126ef762963a60c72795fa188a81b25304d1828ede1e517a`.
Desktop pins: CPython 3.11.15, arm64/Darwin, Pydantic 2.14.2,
Arelle 2.47.4, cryptography 50.0.2; frozen lock
`229bc76c75019d54df8c1cba240839bacf01e56d7493f4bc615e058c4e5f6f11`.

## Isolated runtime and remaining acceptance

Own project `value-investment-agent-376-baseline-flows` uses localhost ports
15777/18777, subnet `10.247.77.0/28` and its own PostgreSQL/service volumes.
Canonical Dockerfile image:
`sha256:6cc366a100c6c0b817a7bc56ceeca6479bca79a09036292e2e1b57de6dcbd523`.
The service and PostgreSQL became healthy; `/readyz` returned 200 with
`identity_resolution_configured=false`. This establishes offline service health,
not SEC acquisition, trusted-release or company-valuation readiness. All 122 installed Python/SQL files and the image lock match the implementation
checkout. Two fresh Linux workers, each network `none`, one CPU and 2 GiB, pass
compile, all three history arms, formal forecast/label/error comparison, export
and analysis. Peak RSS: 712,540 / 712,712 KiB. Both container exit codes are zero
and OOMKilled is false. The second run adds zero artifacts, returns `wrote=false`
and leaves every existing byte, size and mtime unchanged. All nine financial
request/forecast/comparison artifacts match desktop bytes. Container runtime:
Python 3.12.16, Pydantic 2.14.2, Arelle 2.47.4, cryptography 50.0.2 and xlrd 2.0.2;
cross-runtime report identity is not claimed.

The container's stable arithmetic report is
`b135253fd01b9fb6835364b3f5d8da69534cbae209ac6a65582a13965b708450`, input/output
`9774bc262a1bcbf9a7e6d90b578b1591a3b3462a3d7fa9c1b0573340beb8ddb5` /
`3ba0f92a5368bfb132393d9f81e23c70130456f1b4bb241e0b9734d2f6fc1cec`.
The separate repeat-proof input/output is
`1caf572cc86817f0060f692c7a0190f89e2b34a64b4e1d10ca3ea7a458d0de82` /
`92f948b70086580a274123d81d04ca795bd92ce7850bd04a525b4d75012e17b8`.

The initial old-base overlay failed because `xlrd` was absent; it was replaced
using the canonical Dockerfile and frozen lock. External verifier receipt-shape
errors and all failed 137 worker results remain under
`verification-driver-history/` and `container-command-receipts/`. Retained
container state confirms OOMKilled, while fine profiling shows a worker around
400 MiB, cgroup memory.events below its own limit and only about 300 MiB available
in the shared 8 GiB Docker VM. This distinguishes global memory pressure from a
proven per-worker limit failure. Own services/profile worker were stopped after recording results. The earlier,
already-integrated #414 `via-issue376-wc-policy` acceptance pair was also stopped,
with both volumes retained; its exact labels and lack of external active clients
were inspected first. This released enough VM memory for both complete bounded
runs. Baseline comparison shows the other 93 pre-existing containers retain
identical IDs, images, start times and states. No foreign resource or daemon
configuration was changed. Own temporary acceptance services were restarted serially after replay for final
readiness and disposable-data inspection, then stopped. Their two new disposable
volumes, stopped project containers/network and the dedicated image are retained
until independent review/integration. Retire only this exact project after merge;
keep the earlier #414 volumes intact. Generated research evidence stays outside
Docker and Git. The runtime proof records the exact Compose file digest, localhost
bindings, explicit absence of env files/browser, image, ownership and rebuild
commands. No full SEC-backed preflight is claimed for this offline increment.

Pending: final evidence checkpoint CI, independent review, serial integration
and merge verification.
No exact study, accounting release, Transition evidence or threshold completion
is claimed. Keep the PR draft until those incremental delivery gates pass.
