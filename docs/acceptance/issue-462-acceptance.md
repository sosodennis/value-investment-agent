# #462 Fundamental report acceptance

## Source and scope

PR: https://github.com/sosodennis/value-investment-agent/pull/464. Target: `main`, base `4ce26d9f1db03fb137ffddd0485c0f2bd7ae8739`. Tested implementation: `83e5d7dac04189c90e908017f3ab7eab3efba57b`. Later commits may change only this acceptance document and `issue-462-runtime.json`.

The implementation delivers A, B, and C for the existing supported FCFF workflow. Fundamental Service owns arithmetic, conditional sampling policy, release selection, retained revisions, source rights, freshness, and exact input verification. Core owns orchestration, actor binding, artifact publication, and persisted source access. Frontend owns parsing, projection, presentation, and explicit user actions. Caller approval remains removed. No runtime dependency was added.

The applicable AGENTS, backend/frontend guides, and architecture standard were checked against current source. The standard's historical migration text was not treated as an additional migration requirement. Core architecture guard passes. The architecture-skill-maintainer check found no stale guidance requiring edits to the three agent supplements. The final selector adapter and assumption labels do not change layer ownership or topology.

## Delivered behavior

- A: shared manual/automatic valuation intent retains default Monte Carlo. Typed service results preserve nested deterministic base, quantiles, counts, diagnostics, nodes, references, canonical Decimal text, and separate root/base hashes. Preparation outcomes publish a readable report with calculation skipped. Facts-only stays explicit. Generic runner behavior remains shared.
- B: result, assumptions, financial evidence, and method have section anchors and disclosures. Equity total and per-share value remain distinct. Quantile markers use supplied values; no synthetic Gaussian, missing percentile, market quote, or upside is inferred. Facts retain period, unit, scale, dimensions, and quality. Fact, assumption, and node selections open the existing inspector.
- C: a reasoned terminal-growth edit creates a new run/artifact only after Recalculate. Percentage conversion preserves decimal text. Previous result, pending, and completed states remain separate. Source identity and operation tokens reject cross-run/preparation and late-response adoption. Historical and revised reports are read-only. Original/manual evidence stays available and application labels match the retained canonical input.

Owning fixes integrated and verified: #463 configured release; #465 conditional uncertainty/revision contract; #466 released filing identity; #467 service review witness and policy; #468 retained-source/rights authority; #469 service-owned automatic model binding; #470 mapping-version evidence parity; #471 source-hash scope; #472 direct-output source ACL with real PostgreSQL regression; #473 retained fiscal selector timing adapter; #474 original/applied assumption labels. Issues remain open until main delivery and post-merge smoke.

## Runtime identity

The canonical tuple is [issue-462-runtime.json](issue-462-runtime.json). All runtime commands ran from its dedicated integration worktree. The helper below fixes both Compose project names, env files, and ordered overlays:

`/Users/denniswong/.codex/diagnostics/issue-462-fundamental-report/runtime/compose.sh`

Only these projects were operated:

| Project | Services and host ports |
| --- | --- |
| `value-investment-agent-denniswong-462-app` | backend 21680, frontend 21681, PostgreSQL 21682, Redis 21683, LLM provider 21684, search 21685 |
| `value-investment-agent-denniswong-462-fundamental` | service 21690, PostgreSQL 21691 |

All eight containers were healthy for final acceptance. Frontend image `sha256:e62ff849d7a427d768404b0573af494b4a7adefd38fe04a776138c94554f963a`; backend `sha256:de89ae24ff2a66de2200d4793a4ce46910b46fd836534d4d1495b1aa44a1482d`; service `sha256:63d942e8f2159444fb5f6852155f81954839e90264ae80d02bb19947adddcfba`.

Installed-source equality passed: 183 service Python files, source-map digest `3ca71bd325d503aaea3f1627ebd231e98e30ffed4f7beed4d017c2be7711c165`; 818 backend files, `07c20cdf3e581cfec0f4ceb935252b7eb4912daa9d74502727637dc42717accf`. No mismatches or unexpected Python files. Frontend Git tree `d452d35781edfc7204a1fb984342ea24b00a655f` was rebuilt in the isolated project.

The SEC-backed prepared release is `b6224b61a0aa631bebf2f74bc3902150b786e1b43620679381199e1ba7baeab6`, revision 3, `fcff_dcf/fcff_dcf-v2`. Snapshot `history-295533edf0f513fe6fbda61efeed904f6a6ff99f94de6f20034bad77c958545f`. Retained preparation returns HTTP 200, prepared, issues empty. Release verification suite digest `025bea3eb2d553d6f258f31760427fa96684fce84ddbd7e91be517bec141a4b6`, workflow `local/issue462/report-release-verification-v2`. Credentials and signing keys remain outside Git.

## Real browser and artifact evidence

Base route: `http://127.0.0.1:21681/workspace`. IAB browser 2, tabs 7/8/9. These were real browser → FastAPI → agent → Fundamental Service → persisted artifact → parser → UI runs. Authenticated artifact captures and DOM/screenshot observations are separate from fixture tests.

| Scenario | Thread | Run | Artifact | Result |
| --- | --- | --- | --- | --- |
| Manual Start | `thread_ecc4bab1-c2e5-47c5-8c2d-84c7349aff5e` | `dff08e5b-428a-436c-809f-44c4be73b7fb` | `18f3d4db-13aa-44e0-be69-caef65f2b61d` | completed, default MC, provisional |
| Auto-start | `thread_43890d1d-913b-4baa-8832-76b948778c68` | `0f47b609-c51e-4ec8-a23f-45c97ea721a7` | `ef3cc470-e23f-4582-8259-00561fc12932` | same canonical base/quantiles, distinct artifact |
| Recalculate 2.5% | `thread_68e1931a-d1be-44bc-b1d0-2833805f9cbb` | `e45bb96f-1162-400d-9004-5c6b20ed7afb` | `b35d7e0e-2f4a-46d9-a0f8-dd247aa641f0` | new completed valuation; canonical terminal growth `0.025` |
| Refuse 5% | `thread_6192b5c9-ad8a-40f4-b99d-f3661f89e3e9` | `2acd0736-c6de-43be-a056-109645dc31d6` | `a32cc9d2-7965-41a1-834a-7767da88c6fb` | `MANUAL_OVERRIDE_INVALID`, maximum 0.04; no successful result/execution/hashes |
| History reload | auto-start thread/run above | exact run in URL | original artifact above | original values retained; zero textboxes and no Recalculate |

Manual and auto-start canonical per-share base: `229.88242539685962775556419207139754074672901162460` USD/share. Equity total: `1731474428089.1467162549094946817662769043629155565` USD. P05/P50/P95: `144.66504923006348207751523639707097017148015276713`, `173.10058984916732564133256488227973785421478949288`, `197.99983774116374973780751746974444493359658532582`. Requested/valid/invalid: 256/256/0. Seed text `1393190347884600171`.

Revised canonical per-share base: `168.92316962973986376214271505310878928165576150584` USD/share. Equity total: `1272329313651.2006538564589297800154008694311956620` USD. P05/P50/P95: `141.57124272793601389959621076367348046065397087225`, `165.37191333836261456716162940400004671825148128127`, `189.07567612386557742679949774582590647273329379870`. Requested/valid/invalid: 256/256/0. Seed text `17071790345856403266`.

Revision preparation digest `99fdde441fdaf9183dbc1ad225066e45e4025662f3546c63e8c0312e28683d1b` differs from original `a8a5da8d918dabb5aeb4479d4dd3be0528f36962f51b8503db2e53578e18a5dd`. The saved reason is “Use a conservative 2.5 percent terminal growth assumption for this explicit acceptance revision.” Author is derived from the signed server actor; modification timestamp is retained. UI shows `0.0492` as Original retained assumption and `0.025` as Applied manual assumption. Both inspectors retain their own evidence ID and the same exact thread/run/artifact/preparation identity.

Fact inspector: revenue `331839000000`, fact `sec-fact-5bf24a709fb138c5a909734c`, FY2026 period, USD/source scale 10^6, SEC concept/accession/content hash and snapshot. Base node inspector: exact per-share value, formula `equity_value / diluted_shares`, and base-scoped digest/hash. Root uncertainty scope remains separate. The browser has no service credentials or direct service proxy.

## Browser layout and accessibility

Light/dark, 320/390/768/1440px, long Decimals, narrow desktop pane, mobile Sheet, keyboard Enter, Escape/focus return, native Chrome 200% zoom, and native reduced-motion emulation were exercised. Native zoom/emulation were restored and the task-owned Chrome window was closed.

| Viewport | Report width | Main width / scroll width |
| --- | --- | --- |
| 320 | 288 | 320 / 320 |
| 390 | 358 | 390 / 390 |
| 768 | 480 | 528 / 528 |
| 1440 | 645.68 | 1200 / 1200 |

At 320px the existing organization selector in the global header adds about 7px document overflow. The report/main has none. Global shell redesign is outside #462; this is a recorded note, not a claim of whole-site zero overflow. Assumption selection returns focus to its exact trigger after Escape. Native 200% shows wrapped canonical text without overlap. No formal whole-site WCAG certification or representative-reader study is claimed.

## Commands and results

Commands used the dedicated worktree and its installed dependency environments. `RUNTIME` below abbreviates `/Users/denniswong/.codex/diagnostics/issue-462-fundamental-report/runtime`.

| Command / owning check | Exit | Evidence / result |
| --- | --- | --- |
| `cd frontend && npm run lint` | 0 | `frontend-final-lint.log` |
| `cd frontend && npm run typecheck` | 0 | `frontend-final-typecheck.log` |
| `cd frontend && npm run test -- --run` | 0 | `frontend-final-tests.log`, 400 passed, 56 files |
| `cd frontend && npm run check:contrast` | 0 | `frontend-final-contrast.log`, all token pairs pass |
| `cd frontend && npm run build` | 1, then 0 with same command | `frontend-final-build.log` retains Next security-advisory interruption; `frontend-final-build-retry.log` passes; no dependency upgrade |
| `RUNTIME/compose.sh app build frontend` and `up -d --no-deps frontend` | 0 | `frontend-474-docker-build.log`, `frontend-474-start.log` |
| `cd finance-agent-core && PYTHONPATH=. .venv/bin/python -m pytest tests/agents/fundamental/test_valuation_revisions.py tests/agents/fundamental/test_fundamental_service_cutover.py tests/agents/fundamental/test_service_request_producer.py tests/agents/fundamental/test_fundamental_service_client.py tests/agents/fundamental/test_forward_evidence_research.py tests/test_langgraph_runner.py tests/analysis_runtime/test_runtime_route_contracts.py -q` | 0 | `core-final-candidate.log`, 214 passed, 1 skipped (separate PostgreSQL flag) |
| Same environment, `FUNDAMENTAL_REVISION_POSTGRES_TEST=1`, isolated port 21682, `pytest tests/agents/fundamental/test_valuation_revisions.py::test_real_repository_reads_direct_output_and_refuses_child_source -q` | 0 | `postgres-final-candidate.log`, 1 passed; direct output allowed, child/cross-source refused; generated test rows cleaned |
| Core Ruff over changed Fundamental/shared-artifact/runtime boundary and tests | 0 | all checks passed |
| `python3 scripts/architecture_guard.py` | 0 | no boundary violations; guard applies to core imports |
| `bash scripts/generate-contracts.sh` | 0 | `contracts-final-candidate.log`; no generated diff |
| `git diff --check origin/main..HEAD` | 0 | no whitespace errors |
| `python3 RUNTIME/verify-runtime-source.py` | 0 | `runtime-source-equality.json`, exact source equality above |
| `python3 RUNTIME/summarize-final-evidence.py` | 0 | `canonical-final-evidence.json`, authenticated artifact identities/values/counts/refusal match |

Earlier owning checks remain applicable where source is unchanged: service full suite 5006 passed, 163 PostgreSQL-dependent skips, four warnings; independent calculator release gate; core broader contracts/producer/cutover 303 passed, 7 skips; public graph 14 passed. Final-head CI separately runs the full service suite with PostgreSQL and the calculator release gate. Skips are not counted as passes.

Final clean preflight and independent source verdict are recorded in the runtime manifest once complete. Final-head CI, ordinary merge identity, and post-merge smoke are recorded on PR #464 and #462; no post-merge result is claimed by this pre-merge record.

## Evidence retention and limits

Raw authenticated artifacts/snapshots, command logs, hash receipts, and screenshots remain in `RUNTIME`. Key files: `final-{manual,auto,revision}-success-{artifact,snapshot}.json`, `final-policy-refusal-{artifact,snapshot}.json`, `canonical-final-evidence.json`, `browser-474-{report,history-report,manual-inspector,original-inspector}.txt`, `final-report-success.jpg`, `browser-474-manual-inspector.jpg`, `report-{320,390,768,1440}-{light,dark}.jpg`, `evidence-node-desktop.jpg`, `report-200-native-result.png`, `report-reduced-motion-native.png`, and `browser-layout-metrics.json`.

Live opt-in Research returned `LLM_PROVIDER_FAILURE`/unavailable with no claims and no Apply. A successful live licensed Research→Apply is **not verified**. Retained actor-bound licensed-witness handling, exact citations/rights, mismatch rejection, and unsupported nonconditional paths are covered by owning service/API/fixture tests and independent review. Search discovery without rights stays unknown/excluded. No citation or permission was invented to force a live success. Other workflow agents can abstain when their provider is unavailable; Fundamental valuation itself completed. #350 provider deployment, #376 history sufficiency, and #339 deferred work remain independent.

Results remain provisional/uncalibrated and conditional on retained hypotheses. Quantiles have no assigned scenario probabilities and do not predict stock prices. Selected canonical facts do not promise complete historical statements. Supported company/model scope has not expanded.

Failed runtime attempts are preserved: the original 2GiB parser child/3GiB service limit produced typed `PARSER_RESOURCE_EXHAUSTED`; the task-owned service was adjusted to child 3GiB/container 4GiB/concurrency 1. An external Docker stop/destroy interrupted the retry with exit 137, which is not proof of OOM. The third preparation succeeded. Files: `report-final-original-failure.json`, `report-final-validation-failure.json`, `external-{app,service}-interruption-events.log`, `report-retry-preparation-exit.json`, `report-recovery-preparation.json`. #451 history was not changed.

Earlier revision failures are also retained: `controlled-refusal-final-*` is the repaired #472 `REVISION_SOURCE_NOT_FOUND`, not a successful policy refusal. `revision-472-selector-failure-*` is the repaired #473 selector-shape failure. Only `final-policy-refusal-*` establishes the actual 5% policy rejection.

## Delivery and cleanup

Pre-merge acceptance does not include post-merge smoke. PR stays draft until the source/runtime review and applicable final-head CI pass. Delivery uses an ordinary merge commit guarded by the verified head SHA. The actual main merge SHA must then pass installed-source/service and browser smoke for result, evidence, refusal, recalculation, and history before issue closure.

Cleanup is limited to the two recorded Compose projects, this issue's managed worktrees, and merged issue branches. Named volumes, historical artifacts, signing/trust files, certified SEC assets, diagnostics, shared Docker resources, and unrelated WIP are retained. No global prune or volume deletion is authorized by this record.
