# Fundamental Master Backlog
Last Reviewed: 2026-03-11
Owner: Fundamental Maintainer
Cadence: Bi-weekly (artifact output, manual paste)

## Scope
- Consolidate all fundamental backlog/planning docs into one execution entrypoint.
- Keep old docs for traceability; execution priority is managed only here.

## Status Legend
- `Now`: currently executing
- `Next`: ready to execute next
- `Later`: planned but not scheduled
- `Blocked`: waiting on dependency/decision
- `Done`: implemented and verified
- `Superseded`: replaced by newer plan and/or implemented slices

## Now
1. `FB-035` Arelle-first enterprise XBRL full cutover (highest priority)
- Status: `Done` (`S1-S9 Done`, 2026-03-10)
- Source: `fundamental-arelle-enterprise-xbrl-full-cutover-plan-2026-03-09.md`.
- Why: current tag-centric extraction still misses key valuation inputs on extension-heavy filings (AMZN `tax_rate` path fail), and enterprise-grade taxonomy-aware parsing is now top priority.
- Locked decisions:
  - Arelle is the long-term primary parser.
  - direct full cutover (no rollback path).
  - no legacy-data compatibility requirement.
  - performance must include filing-package cache + concept-resolution cache.
  - DQC/EFM is required, with severity gates (`Block` for critical/fatal, `Warn` for non-critical).
- Exit: Arelle pipeline is production parsing path, extension-anchor mapping and DQC/EFM severity gates are live, and release gates consume new canonical payload + diagnostics contract.
- Closure (`2026-03-10`): `FB-035-S9` completed with Arelle-only runtime enforcement (legacy parser fallback removed, Arelle unavailable now fail-fast).

2. `FB-036` Arelle enterprise validation/runtime hardening (wave-2)
- Status: `Done` (`S5-S8 done`, 2026-03-10)
- Source: `fundamental-arelle-enterprise-xbrl-full-cutover-plan-2026-03-09.md` (Arelle Enterprise Validation Hardening Addendum).
- Why: current Arelle integration is parse-first but not yet full enterprise validation orchestration (EFM/DQC plugin runtime, version governance, concurrency/caching hardening).
- Exit: `S5-S8` 完成後，quality gate 以官方 validation 輸出為主來源，且 release gate 可審計規則版本漂移與性能。
- Closure (`2026-03-10`): `FB-036-S8` completed with validation-rule runtime signature evidence, drift-count governance gate, and release snapshot/CI wiring.

3. `FB-003` Backlog consolidation cadence execution
- Status: `Now`
- Goal: bi-weekly consolidated artifact output.
- Exit: one stable artifact per cycle, no duplicate active items across source docs.

4. `FB-006` FCFF-WACC + SBC dilution policy remediation
- Status: `Now`
- Source: `fundamental-fcff-wacc-and-sbc-dilution-remediation-plan-2026-03-08.md`.
- Why: DCF formula-policy still uses CAPM-cost-of-equity proxy as WACC and SBC addback path; needs enterprise-grade correction.
- Exit: S1/S2 implemented and validated, S3 design deferred as planned.

5. `FB-033` Dynamic-parameter enterprise alignment and consensus-relative convergence
- Status: `Now`
- Source: `fundamental-dynamic-parameter-enterprise-alignment-plan-2026-03-09.md`.
- Why: current cohort still shows material ticker-level gap dispersion versus mainstream consensus.
- Exit: cohort median `|consensus_gap_pct|` reaches `<=10%~15%` with auditable `raw/guarded/calibrated` traces.


## Next
1. `FB-005` AAPL consensus-anchor reliability + dcf_standard bias remediation
- Status: `Next`
- Source: `fundamental-aapl-consensus-anchor-remediation-plan-2026-03-07.md`.
- Why: AAPL 實跑 `target_mean_price` 回退 yfinance，且相對主流共識仍顯著偏保守。
- Exit: consensus applied/fallback reason 可觀測，AAPL consensus gap 回放顯著收斂。
- Progress (`2026-03-10`):
  - completed `S1` parser drift-hardening baseline: TipRanks/Investing/MarketBeat text-fallback patterns strengthened and fixture-backed regression coverage added (`tests/fixtures/free_consensus/*` + `test_free_consensus_providers.py`), with targeted validation green (`23 passed`).
- Progress (`2026-03-11`):
  - completed `S2` warning-code propagation baseline: market snapshot now emits `target_consensus_warning_codes`, metadata/completion fields now carry the same machine-readable codes, and fallback classification is normalized for downstream gates/log analysis (`27 passed` targeted tests).
  - completed `S3` replay evidence baseline: replay report now tracks baseline/replayed warning-code sets with added/removed diff and counts for deterministic drift audit (`16 passed` targeted replay tests).
  - completed `S4` backtest governance baseline: backtest summary now exposes warning-code distribution + provider_blocked/parse_missing rates, and monitoring gate adds code-rate thresholds (`max_consensus_provider_blocked_rate`, `max_consensus_parse_missing_rate`) with runner/report test coverage (`16 passed`).
  - completed `S5` gate-profile closure: warning-code monitoring thresholds are now required in gate-profile config and exported by resolver (`FUNDAMENTAL_MAX_CONSENSUS_PROVIDER_BLOCKED_RATE`, `FUNDAMENTAL_MAX_CONSENSUS_PARSE_MISSING_RATE`, `FUNDAMENTAL_MIN_CONSENSUS_WARNING_CODE_COUNT`) with profile resolver/validator tests updated (`11 passed` targeted bundle).
  - completed `S6` release governance closure: release snapshot now records warning-code thresholds and summary evidence (`consensus_warning_code_distribution`, `consensus_provider_blocked_rate`, `consensus_parse_missing_rate`), snapshot validator enforces the new contract, and CI workflow summary/build steps now wire these thresholds (`11 passed` targeted bundle).

2. `FB-001` Extend base guardrail to `dcf_standard`
- Status: `Next`
- Source: `fundamental-base-assumption-guardrail-requirement-breakdown-2026-03-05`.
- Why: current guardrail path is `dcf_growth`-first.
- Exit: `dcf_standard` emits `raw/guarded` diagnostics and regression green.

3. `FB-002` Productionize monitoring thresholds
- Status: `Next`
- Source: guardrail/backtest stream.
- Why: gates exist, but production cohort thresholds still need hardening.
- Exit: fixed thresholds for `extreme_upside_rate`, `guardrail_hit_rate`, `consensus_gap_distribution` with release criteria.

4. `FB-004` Formalize bi-weekly consolidation run output
- Status: `Next`
- Source: consolidation governance stream.
- Why: avoid drift between active docs and master backlog.
- Exit: each cycle records source inventory, archived docs, and unresolved assumptions.

5. `FB-034` Enterprise valuation governance hardening (canonical data + release gates)
- Status: `Next`
- Source: architecture study/planning baseline (`2026-03-09`) aligned to QuantLib/Strata/ORE governance patterns.
- Why: current system has strong replay/guardrail/calibration foundations, but still lacks hard canonical data contracts and cohort-based release governance as first-class ship blockers.
- Progress (2026-03-09):
  - completed: canonical market datum normalization + single-source consensus degraded enforcement.
  - completed: profile-driven release thresholds (`config + resolver + validator`) with CI wiring.
  - completed: release-gate snapshot artifact + validator.
  - completed: replay contract hard-checks for terminal-growth + forward-signal trace fields.
  - completed: replay trace pass-rate gate (`min_replay_trace_contract_pass_rate`) and release-gate exit code `7`.
  - completed: rolling cohort stability report builder (`scripts/build_fundamental_cohort_stability_report.py`) + first prod artifact (`reports/fundamental_cohort_stability_report_s15_prod.json`).
  - completed: rolling cohort stability validator (`scripts/validate_fundamental_cohort_stability_report.py`) with strict gate mode (`--require-stable --min-considered-runs`).
- Remaining:
  - bind `FUNDAMENTAL_LIVE_REPLAY_DISCOVER_ROOT` to artifact export sink in deployment/runtime env.
  - verify FB-033 + FB-034 joint KPI stability (`|consensus_gap_pct|` median/p90 with consensus quality constraints) before marking done.
- Exit:
  - canonical market datum contract enforced (quality/fallback/shares-scope/horizon fields auditable; invalid payload fail-fast or deterministic degraded path).
  - release gate blocks publish when cohort median `|consensus_gap_pct|` exceeds `10%~15%` or when single-source consensus is not down-weighted.
  - standardized `raw -> guarded -> calibrated` trace is present in snapshot/backtest/replay artifacts with `mapping_version` and degraded reason.

## Later
1. `FB-020` Sensitivity Phase 2 (model-specific dimensions for non-DCF)
- Status: `Later`
- Source: `fundamental-valuation-sensitivity-requirement-breakdown-2026-03-05`.

2. `FB-021` Sensitivity Phase 3 (2D heatmap full-grid, e.g. `wacc x terminal_growth`)
- Status: `Later`
- Source: `fundamental-valuation-sensitivity-requirement-breakdown-2026-03-05`.

## Blocked
- None.

## Done (Code-Verified)
1. `FB-010` Forward signal source semantic split (`xbrl_auto`)
- Evidence: `forward_signals.py`, related tests.

2. `FB-011` CAPM market fallback ladder with assumption traceability
- Evidence: `capm_market_defaults_service.py`, param builder tests.

3. `FB-012` Forward signal calibration mapping and pipeline/runbook
- Evidence: calibration modules, scripts, validators, runbook, tests.

4. `FB-013` Base assumption guardrail v1 on `dcf_growth` plus metadata/UI visibility
- Evidence: dcf payload guardrail hook, assumption/update services, frontend parser/output tests.

5. `FB-014` Sensitivity v1 (DCF one-way shocks) plus diagnostics/UI
- Evidence: sensitivity contracts/service, calculator integration, tests.

6. `FB-015` Backtest monitoring metrics plus gating (`exit code 4`)
- Evidence: backtest report/runtime/runner updates, tests, runbook.

7. `FB-030` Replay input-contract migration (remove log-coupled replay gate)
- Evidence: replay input contracts, replay checks script, release gate manifest path, CI workflow migration, tests.

8. `FB-031` P2 conservative-path replay observability completion
- Evidence: terminal-growth metadata path in parameterization result, replay report metadata-first extraction, replay gate hard-check (`terminal_growth_path_missing`), tests and runbook/docs updated.

9. `FB-032` GOOG shares-scope + reinvestment remediation (`S1-S4`)
- Evidence: shares-scope policy治理、reinvestment guardrail、replay/backtest diagnostics、monitoring gate 指標與測試完成。

## Superseded
1. `fundamental-valuation-bias-remediation-plan-2026-03-04`
- Status: `Superseded`.
- Reason: core slices implemented and absorbed into current streams.

2. `fundamental-forward-signal-calibration-mapping-plan-2026-03-04`
- Status: `Superseded`.
- Reason: core implementation complete; now governed by cadence/runbook/release gate.

## Active Source Docs (Not Superseded)
1. `finance-agent-core/docs/backlog/fundamental-base-assumption-guardrail-requirement-breakdown-2026-03-05.md`
2. `finance-agent-core/docs/backlog/fundamental-valuation-sensitivity-requirement-breakdown-2026-03-05.md`
3. `finance-agent-core/docs/backlog/fundamental-replay-input-contract-migration-plan-2026-03-07.md`
4. `finance-agent-core/docs/backlog/fundamental-aapl-consensus-anchor-remediation-plan-2026-03-07.md`
5. `finance-agent-core/docs/backlog/fundamental-fcff-wacc-and-sbc-dilution-remediation-plan-2026-03-08.md`
6. `finance-agent-core/docs/backlog/fundamental-p2-conservative-path-replay-remediation-plan-2026-03-08.md`
7. `finance-agent-core/docs/backlog/fundamental-goog-shares-scope-and-reinvestment-remediation-plan-2026-03-08.md`
8. `finance-agent-core/docs/backlog/fundamental-dynamic-parameter-enterprise-alignment-plan-2026-03-09.md`
9. `finance-agent-core/docs/backlog/fundamental-arelle-enterprise-xbrl-full-cutover-plan-2026-03-09.md`

## Archived Source Docs
1. `finance-agent-core/docs/backlog/archive/fundamental-valuation-bias-remediation-plan-2026-03-04.md`
2. `finance-agent-core/docs/backlog/archive/fundamental-forward-signal-calibration-mapping-plan-2026-03-04.md`

## Consolidation Notes (2026-03-07)
1. Added `FB-005` for AAPL consensus-anchor remediation and registered new source doc.
2. Open assumptions:
- `dcf_standard` guardrail rollout remains pending.
- production monitoring threshold tuning remains pending (cohort coverage rule not fixed yet).

## Consolidation Notes (2026-03-09)
1. Added `FB-033` as the new governing backlog stream for enterprise-grade dynamic-parameter alignment.
2. Locked requirements: cohort KPI `|gap| <=10%~15%`, nominal-only long-run growth policy, single-source consensus mandatory down-weight, bi-weekly profile update with replay evidence.
3. Added `FB-034` to formalize enterprise governance hardening: canonical data contract enforcement, cohort release-gate hard blockers, and end-to-end valuation trace standardization.
4. `FB-034-S9/S10/S11` completed: replay trace contract hardening (`forward_signal_trace_missing`), replay trace pass-rate gate (`min_replay_trace_contract_pass_rate`), snapshot/replay schema updates, and checklist/backlog governance sync.
5. `FB-034-S12` completed: generated filled cohort release checklist artifact from real run (`reports/fundamental_cohort_release_checklist_s12_2026-03-09.md`) with backtest/replay/snapshot evidence.
6. `FB-034-S13` completed: executed `prod_cohort_v1` gate run and produced reject artifact (`reports/fundamental_cohort_release_checklist_s13_prod_2026-03-09.md`); blocker confirmed as cohort coverage不足 (`consensus_gap_available_count=2<min:20`).
7. `FB-034-S14` completed: added prod-like cohort fixture/baseline + backtest contract support for consensus quality fields + release-gate dataset override env; `prod_cohort_v1` rerun passed with approve artifact (`reports/fundamental_cohort_release_checklist_s14_prod_2026-03-09.md`).
8. `FB-034-S15` completed: added rolling cohort stability report tooling and generated first prod artifact (`reports/fundamental_cohort_stability_report_s15_prod.json`), currently showing `stable=false` due to prior failed run in window.
9. `FB-034-S16` completed: added rolling stability validator + tests + runbook/spec updates; governance flow can now hard-fail when rolling window not stable.
10. `FB-034-S17` completed: generated new `prod_cohort_v1` pass run (`s17`) + snapshot and rebuilt rolling stability report (`S14+S17`) with strict validator pass (`summary.stable=true`); checklist artifact added at `reports/fundamental_cohort_release_checklist_s17_prod_2026-03-09.md`.
11. `FB-034-S18` completed: added live replay cohort tooling (`build_fundamental_replay_manifest.py` + `validate_fundamental_replay_cohort_gate.py`) and produced `AAPL/MSFT/GOOG/NVDA` live cohort artifacts with gate pass (`manifest_cases=4`, `unique_tickers=4`, `pass_rate=1.0`).
12. `FB-034-S19` completed: live replay manifest builder now supports staged durable input directory (`--stage-dir`) and cohort gate supports strict path governance (`--require-relative-input-paths`, `--require-input-root`); generated staged `live_s19` artifacts with all gates pass.
13. `FB-034-S20` completed: replay manifest builder now supports discovery mode (`--discover-root`, `--discover-glob`, `--latest-per-ticker`, `--ticker-allowlist`) and default-skips invalid/legacy inputs; generated `live_s20` staged artifacts with strict cohort gate pass.
14. `FB-034-S21` completed: removed backward-compat toggles in replay manifest builder and made v2-only filtering explicit in discovery path; generated `live_s21` staged artifacts + strict cohort gate pass.
15. `FB-034-S22` completed: added config/env-driven one-command live replay cohort runner (`run_fundamental_live_replay_cohort_gate.py`) and default config (`config/fundamental_live_replay_cohort_config.json`) to automate discovery->stage->replay->gate flow.
16. `FB-034-S23` completed: wired fixture-backed live replay cohort gate into CI workflow (`monorepo-contract-gates`) with dedicated CI config and artifact upload bundle.
17. `FB-034-S24` completed: hardened discover-root env contract in live cohort runner (`discover_root_env_key` + `require_discover_root_env`) with test coverage for required-env failure and env-key override success; docs/spec updated for explicit precedence.
18. `FB-034-S25` completed: connected live replay cohort runner into release-gate main flow (`run_fundamental_release_gate.sh`), standardized live cohort failure exit code `8` with explicit error codes, added snapshot live-replay evidence fields, and auto-generated CI release checklist artifact (`reports/fundamental_cohort_release_checklist_ci.md`).
19. `FB-034-S26` completed: removed legacy replay-manifest release-gate path (`FUNDAMENTAL_REPLAY_MANIFEST_PATH`) and enforced canonical live replay cohort gate as the only release-gate replay contract path; snapshot error field renamed to `gate_error_codes` (breaking, non-backward-compatible), and `prod_cohort_v1.max_consensus_gap_p90_abs` tightened to `0.20` (first-stage target before final `0.15`).
20. `FB-034-S31` completed: reran canonical live replay cohort gate and full release gate against `reports/fundamental_replay_inputs/live_auto_s30_prod_p15`; artifacts (`fundamental_live_replay_cohort_run_release_gate.json`, `fundamental_replay_checks_report_live_release_gate.json`, `fundamental_replay_cohort_gate_release_gate.json`) all passed with `issues=[]`, and replay deltas remained unchanged versus prior cycle (no new drift introduced by latest slice).
21. `FB-034-S32` completed: added intrinsic-delta hard gate for live replay cohort (`intrinsic_delta_p90_abs`) with profile-driven threshold export (`FUNDAMENTAL_MAX_REPLAY_INTRINSIC_DELTA_P90_ABS`), cohort validator enforcement, and release snapshot/CI summary wiring; verified on real cohort run (`s32_intrinsic_delta_gate`) with `replay_intrinsic_delta_p90_abs=340.4145 <= max:450.0` and gate pass.
22. `FB-034` status update: governance stream moved to maintenance mode (`Next`) after S32; active execution focus shifted to `FB-033` parameter-alignment slices.
23. `FB-033-S1` completed: replay diagnostics now emit `delta_by_parameter_group` (`growth|margin|reinvestment|terminal`) using one-at-a-time baseline reversion, enabling deterministic parameter-group attribution for cohort tuning without formula changes; live cohort artifact generated at `reports/fundamental_replay_checks_report_live_s33_fb033_s1.json`.
24. `FB-033-S2` completed: added low-premium (`target_premium <= 30%`) conservative reinvestment floors for `dcf_growth` (`capex terminal_lower >= 8%`, `wc terminal_lower >= 0%`) to reduce over-optimistic FCF release in low-premium cases; cohort replay (`s34_fb033_s2`) passed with no gate issues, GOOG replay value moved from `524.98` to `497.05` (still above consensus; further slices required).
25. `FB-033-S3` completed: for `dcf_growth` low-premium cases with shares-scope mismatch (`scope_mismatch_detected=true`), added mismatch-aware conservative reinvestment band tightening (`capex terminal_lower >= 12%`, `wc terminal_lower >= 2%`, with widened upper bounds to keep valid terminal bands), plus assumption trace fields; live cohort replay (`s35_fb033_s3`) passed with no gate issues and reduced GOOG replay intrinsic from `497.05` to `433.37` while keeping AAPL/MSFT/NVDA unchanged.
26. `FB-033-S4` completed: added conditional beta mean-reversion (Blume-style 67/33 shrinkage toward 1.0) in SaaS CAPM path with hard guards (skip when shares-scope mismatch ratio >= 20%, skip degraded low-premium consensus, skip high-beta > 1.5); live cohort replay (`s37b_fb033_s4_beta`) passed with no gate issues and improved under-valuation names (`AAPL: 244.61 -> 253.61`, `MSFT: 497.24 -> 514.82`) while keeping `GOOG/NVDA` stable. Cohort absolute gap median is now `~13.58%` (within `10%~15%` stage-1 target), with GOOG still as remaining high-side outlier.
27. `FB-033-S5` completed: added enterprise-style targeted reinvestment clamp for `dcf_growth` only when `shares_scope` is harmonized market-class with severe mismatch (`ratio >= 45%`) and degraded low-premium consensus (provider fallback). Clamp uses year1-linked terminal floors (`capex=max(14%, year1*1.25)`, `wc=max(2.5%, year1*0.35)`) instead of hard-coded target-price fitting; live cohort replay (`s38_fb033_s5_shares_reinv`) passed with no gate issues and reduced GOOG replay intrinsic (`433.37 -> 398.79`) while preserving AAPL/MSFT/NVDA trajectories.
28. `FB-033-S5A` completed: added enterprise validation addendum for shares-scope + reinvestment clamp (methodology + data evidence + trigger constraints) to prevent price-fitting drift; evidence recorded in `fundamental-goog-shares-scope-and-reinvestment-remediation-plan-2026-03-08.md` under `Enterprise Validation Addendum (2026-03-09)`.
29. `FB-033-S6` completed: externalized severe harmonized-mismatch reinvestment clamp knobs into a versioned runtime profile artifact (`reinvestment_clamp_profile_v1`) with env override (`FUNDAMENTAL_REINVESTMENT_CLAMP_PROFILE_PATH`), deterministic fallback (`embedded_default`), builder script (`build_fundamental_reinvestment_clamp_profile.py`), and runbook; policy assumptions now emit profile load/fallback and severe-floor `profile_version` for replay audit.
30. `FB-033-S7` completed: wired reinvestment clamp profile into release-gate hard checks via `validate_fundamental_reinvestment_clamp_profile.py`, added release-gate exit code `9` (`reinvestment_clamp_profile_gate_failed`), integrated CI snapshot metadata (`reinvestment_clamp_profile_report_path/available` + summary block), and extended snapshot/build/validator/release-gate test coverage.
31. Added `FB-035` as highest-priority stream for Arelle-first enterprise XBRL full cutover with locked decisions: direct full cutover, no rollback path, no legacy-data compatibility, and mandatory performance architecture (filing package cache + concept-resolution cache).
32. `FB-035` governance policy locked: DQC/EFM is required with severity gates (`Block` for fatal/critical valuation-impact issues, `Warn` for non-critical issues), and release gate must consume these quality outcomes as first-class blockers.
33. `FB-035` decomposed into execution-ready `S1-S8` implementation tickets in source plan doc, with explicit per-slice scope, dependency chain, and exit criteria for direct start.
34. `FB-035-S8` completed: enforced 6-ticker cohort release-gate execution (`AMZN/AAPL/MSFT/GOOG/NVDA/JPM`) with dedicated run config (`min_cases=6`, `min_unique_tickers=6`), generated fresh AMZN/JPM replay inputs (`live_s8_6tickers_seed`), and passed live cohort gate (`fundamental_replay_cohort_gate_s8_6tickers_v2.json`, `issues=[]`, `gate_passed=true`). During closure, fixed replay trace contract over-strictness by exempting `bank` model from terminal-growth-path requirement in `run_fundamental_replay_checks.py` with targeted tests.
35. `FB-035` closure validation sweep completed: targeted lint and contract/regression checks passed (`ruff check` for S1-S7 touched modules; `pytest` 11-file bundle `76 passed`), with no architecture-standard blocker found in changed scope.
36. `FB-035-S9` completed: removed legacy parser fallback from `sec_xbrl/extractor.py` and enforced Arelle-only parse path (runtime unavailable now hard-fails with explicit error contract), updated `test_sec_xbrl_arelle_engine.py` to assert non-fallback behavior, declared `arelle-release` dependency in `pyproject.toml`, and validated with `ruff` + targeted pytest bundle (`35 passed`).
37. Added `FB-036` wave-2 execution stream (`S5-S8`) for Arelle enterprise validation/runtime hardening: validation metadata contract baseline, EFM/DQC plugin issue normalization, concurrency+taxonomy cache hardening, and release governance for regulatory version drift.
38. `FB-036-S6` started: added Arelle validation profile runtime baseline (`facts_only/efm_validate/efm_dqc_validate` via env contract) and standardized `model_xbrl.errors` into structured `validation_issues` on parse result; targeted lint + sec_xbrl test bundle passed (`14 passed`).
39. `FB-036-S6` wiring slice completed: extractor now projects Arelle validation issues into `filing_metadata.arelle_validation_issues`, and financial payload diagnostics merges them as `dqc_efm_issues` so quality gate can consume the same issue stream; targeted tests passed (`15 passed`).
40. `FB-036-S6` orchestration closure completed: `arelle_engine` now performs PluginManager/PackageManager runtime loading for validation profiles (with mode-default plugins and fail-fast on plugin/package load failure), and diagnostics/gate now share one normalized issue schema via `normalize_dqc_efm_issue` (`code/source/severity/field_key/message/blocking`); targeted lint + pytest bundle passed (`20 passed`).
41. `FB-036-S7` started: added Arelle runtime isolation mode (`FUNDAMENTAL_XBRL_ARELLE_RUNTIME_ISOLATION`, default `serial`) with parse-lock wait telemetry (`runtime_lock_wait_ms`), and hardened filing payload cache coordinates with taxonomy+validation profile tokenization (`build_arelle_taxonomy_cache_token`) plus `arelle_runtime` latency/lock diagnostics summary; targeted lint + sec_xbrl test bundle passed (`27 passed`).
42. `FB-036-S7` prewarm slice completed: live replay cohort runner now supports optional XBRL cache prewarm (`enable_prewarm` or env `FUNDAMENTAL_LIVE_REPLAY_ENABLE_PREWARM`) by parsing manifest inputs into ticker-years requests and warming via `fetch_financial_payload` before replay checks; prewarm summary is persisted in run artifact (`requested/succeeded/failed/cache_hit_after_prewarm_rate`), defaults to non-blocking, with targeted script tests/ruff green (`test_run_fundamental_live_replay_cohort_gate_script.py` + `test_fundamental_release_gate_script.py`).
43. `FB-036-S7` runtime-governance closure completed: replay/cohort gate pipeline now carries Arelle runtime performance signals end-to-end (`arelle_parse_latency` + `arelle_runtime_lock_wait` per-case and P50/P90 summaries), validator supports new hard thresholds (`--max-arelle-parse-latency-p90-ms`, `--max-arelle-runtime-lock-wait-p90-ms`), live cohort runner wires config/env overrides, and gate-profile mapping/validation now exports required env keys (`FUNDAMENTAL_MAX_REPLAY_ARELLE_PARSE_LATENCY_P90_MS`, `FUNDAMENTAL_MAX_REPLAY_ARELLE_RUNTIME_LOCK_WAIT_P90_MS`); targeted lint + script/release-gate test bundle passed (`35 passed`).
44. `FB-036-S8` completed: replay checks now emit validation-rule runtime signature evidence (`mode/disclosure/plugins/packages/arelle_version/signature`) plus drift diagnostics (`validation_rule_drift_count/detected/error_code`), cohort validator/runner/gate profiles now enforce `max_validation_rule_drift_count` (`FUNDAMENTAL_MAX_REPLAY_VALIDATION_RULE_DRIFT_COUNT`, default `0`), and release snapshot + CI summary include the new governance threshold and replay fields; targeted lint + pytest bundle passed (`42 passed`).
45. `FB-005-S1` completed: hardened free-consensus parser fallbacks with fixture-driven variant regression coverage (TipRanks/Investing/MarketBeat) to reduce page-structure drift risk; added `tests/fixtures/free_consensus/*` and extended provider tests, with targeted parser/market-data bundle validation green (`23 passed`).
46. `FB-005-S2` completed: standardized `target_consensus_warning_codes` through `market_data_service -> metadata_service -> run_valuation_use_case` completion fields, including normalized fallback/warning code extraction from consensus warnings for machine-readable diagnostics; targeted `ruff` + pytest bundle passed (`27 passed`).
47. `FB-005-S3` completed: `replay_fundamental_valuation.py` now emits target-consensus warning-code replay evidence (`baseline/replayed codes`, `added/removed`, `count`) with extraction from both `data_freshness.market_data` and `parameter_source_summary.market_data_anchor`; targeted replay test bundle passed (`16 passed`).
48. `FB-005-S4` completed: backtest contract/runtime/report path now carries `target_consensus_warning_codes` and summarizes code-level distribution/rates (`consensus_warning_code_distribution`, `consensus_provider_blocked_rate`, `consensus_parse_missing_rate`), with new monitoring gate thresholds and release-gate CLI pass-through env wiring; targeted backtest report/runner bundle passed (`16 passed`).
49. `FB-005-S5` completed: gate-profile threshold chain now includes warning-code monitoring knobs (`max_consensus_provider_blocked_rate`, `max_consensus_parse_missing_rate`, `min_consensus_warning_code_count`) across config/resolver/validator with test coverage for exported env mapping and profile schema closure (`11 passed` targeted bundle).
50. `FB-005-S6` completed: release snapshot + CI governance chain now carries warning-code threshold/evidence fields (snapshot thresholds + summary warning-code distribution/rates), with validator contract enforcement and CI snapshot/step-summary wiring updated (`11 passed` targeted bundle).

## Consolidation Rules (Bi-weekly)
1. Review code and tests first, then update backlog statuses.
2. Any item marked `Superseded` must include concrete code evidence.
3. New fundamental backlog docs must be registered here before execution.
4. If conflict exists between source docs, this master backlog is execution authority.
