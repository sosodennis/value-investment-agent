# Fundamental Cohort Report Artifact Spec

## Purpose

Define a stable artifact contract for cohort-based release decisions in
fundamental valuation.

This spec is used by:

1. CI release gate (`.github/workflows/monorepo-contract-gates.yml`)
2. Local release diagnostics (`scripts/run_fundamental_release_gate.sh`)
3. Manual release checklist (`docs/fundamental_cohort_release_checklist_template.md`)

## Canonical Artifact Paths

1. Backtest report: `finance-agent-core/reports/fundamental_backtest_report_ci.json`
2. Replay checks report: `finance-agent-core/reports/fundamental_replay_checks_report_ci.json`
3. Release gate snapshot: `finance-agent-core/reports/fundamental_release_gate_snapshot_ci.json`
4. Calibration pipeline report:
   `finance-agent-core/reports/forward_signal_calibration_pipeline_report_<version>.json`
5. Rolling cohort stability report:
   `finance-agent-core/reports/fundamental_cohort_stability_report_<cycle>.json`
6. Live replay cohort manifest:
   `finance-agent-core/reports/fundamental_replay_manifest_live_<cycle>.json`
7. Live replay checks report:
   `finance-agent-core/reports/fundamental_replay_checks_report_live_<cycle>.json`
8. Live replay cohort gate evaluation:
   `finance-agent-core/reports/fundamental_replay_cohort_gate_<cycle>.json`
9. Live replay cohort run summary:
   `finance-agent-core/reports/fundamental_live_replay_cohort_run_<cycle>.json`
10. Release checklist artifact:
   `finance-agent-core/reports/fundamental_cohort_release_checklist_<cycle>.md`
11. Reinvestment clamp profile validation report:
   `finance-agent-core/reports/fundamental_reinvestment_clamp_profile_validation_report_<cycle>.json`

## Required Backtest Report Fields

The release artifact must include these `summary` fields:

1. `total_cases`
2. `ok`
3. `errors`
4. `consensus_gap_distribution.available_count`
5. `consensus_gap_distribution.median`
6. `consensus_gap_distribution.p90_abs`
7. `consensus_degraded_rate`
8. `consensus_confidence_weight_avg`
9. `shares_scope_mismatch_rate`
10. `guardrail_hit_rate`
11. `consensus_provider_blocked_rate`
12. `consensus_parse_missing_rate`
13. `consensus_warning_code_distribution.available_count`
14. `consensus_warning_code_distribution.code_case_counts`
15. `consensus_warning_code_distribution.code_case_rates`

## Required Release Gate Snapshot Fields

1. `generated_at`
2. `gate_profile`
3. `release_gate_exit_code`
4. `gate_error_codes`
5. `report_path`
6. `report_available`
7. `replay_report_path`
8. `replay_report_available`
9. `live_replay_run_path`
10. `live_replay_run_available`
11. `thresholds`
12. `summary`
13. `issues`
14. `reinvestment_clamp_profile_report_path`
15. `reinvestment_clamp_profile_report_available`

When `replay_report_available=true`, snapshot `summary` must include:

1. `replay_checks.total_cases`
2. `replay_checks.passed_cases`
3. `replay_checks.failed_cases`
4. `replay_checks.trace_contract_pass_rate`
5. `replay_checks.quality_block_rate`
6. `replay_checks.cache_hit_rate`
7. `replay_checks.warm_latency_p90_ms`
8. `replay_checks.cold_latency_p90_ms`

When `live_replay_run_available=true`, snapshot `summary` must include:

1. `live_replay.gate_passed`

When `reinvestment_clamp_profile_report_available=true`, snapshot `summary` must include:

1. `reinvestment_clamp_profile.gate_passed`
2. `reinvestment_clamp_profile.profile_version`
3. `reinvestment_clamp_profile.as_of_date`
4. `reinvestment_clamp_profile.age_days`
5. `reinvestment_clamp_profile.evidence_ref_count`

## Gate Profile Fields (CI)

The CI workflow must provide explicit gate thresholds via environment variables:

1. `FUNDAMENTAL_MAX_CONSENSUS_GAP_MEDIAN_ABS`
2. `FUNDAMENTAL_MAX_CONSENSUS_GAP_P90_ABS`
3. `FUNDAMENTAL_MIN_CONSENSUS_GAP_COUNT`
4. `FUNDAMENTAL_MAX_CONSENSUS_DEGRADED_RATE`
5. `FUNDAMENTAL_MIN_CONSENSUS_CONFIDENCE_WEIGHT`
6. `FUNDAMENTAL_MIN_CONSENSUS_QUALITY_COUNT`
7. `FUNDAMENTAL_MIN_REPLAY_TRACE_CONTRACT_PASS_RATE`
8. `FUNDAMENTAL_MAX_REPLAY_QUALITY_BLOCK_RATE`
9. `FUNDAMENTAL_MIN_REPLAY_CACHE_HIT_RATE`
10. `FUNDAMENTAL_MAX_REPLAY_WARM_LATENCY_P90_MS`
11. `FUNDAMENTAL_MAX_REPLAY_COLD_LATENCY_P90_MS`
12. `FUNDAMENTAL_MAX_CONSENSUS_PROVIDER_BLOCKED_RATE`
13. `FUNDAMENTAL_MAX_CONSENSUS_PARSE_MISSING_RATE`
14. `FUNDAMENTAL_MIN_CONSENSUS_WARNING_CODE_COUNT`

`FUNDAMENTAL_GATE_PROFILE` identifies the active threshold bundle.
Profile source of truth: `config/fundamental_gate_profiles.json`.
Resolver: `scripts/resolve_fundamental_gate_profile.py`.
Validator: `scripts/validate_fundamental_gate_profiles.py`.

## Governance Rules

1. Single-source consensus must not be treated as high confidence.
2. Canonical market datum normalization must be present in snapshot payloads:
   - `target_mean_price.horizon=12m` when missing.
   - `shares_outstanding.shares_scope=unknown` when missing.
3. Release decision must reference both report path and gate profile.
4. Snapshot artifact must pass validator:
   `scripts/validate_fundamental_release_gate_snapshot.py`.
5. Live replay cohort manifests should use staged relative input paths and pass
   `validate_fundamental_replay_cohort_gate.py` with:
   - `--require-relative-input-paths`
   - `--require-input-root <staged_replay_input_dir>`
6. Replay manifest builder should prefer discovery mode for operational runs:
   - `--discover-root <export_dir>`
   - `--discover-glob '*.replay-input*.json'`
   - `--latest-per-ticker` + `--ticker-allowlist <cohort>`
   - replay input contract is `valuation_replay_input_v2` only (legacy schemas excluded)
7. For scheduled/automated runs, use:
   - `scripts/run_fundamental_live_replay_cohort_gate.py`
   - config: `config/fundamental_live_replay_cohort_config.json`
   - env overrides: `FUNDAMENTAL_LIVE_REPLAY_DISCOVER_ROOT`, `FUNDAMENTAL_LIVE_REPLAY_TICKER_ALLOWLIST`
   - config env binding knobs:
     - `discover_root_env_key`
     - `require_discover_root_env`
8. CI fixture-backed profile:
   - config: `config/fundamental_live_replay_cohort_config_ci.json`
   - cycle tag: `ci`
   - artifact bundle: `fundamental-live-replay-cohort-artifacts`
9. CI checklist artifact:
   - builder: `scripts/build_fundamental_cohort_release_checklist.py`
   - output: `reports/fundamental_cohort_release_checklist_ci.md`

## Evidence and Retention

For each release candidate, archive:

1. Backtest report artifact
2. Replay checks report artifact
3. Release gate snapshot artifact
4. Calibration pipeline report artifact
5. Completed checklist record (from template)

For bi-weekly governance cadence, also archive:

1. Rolling cohort stability report (`summary.stable`, `summary.stability_reasons`)
2. Per-run failed checks (`runs[].failed_checks`) for threshold tuning traceability

Version-control policy:

1. Treat `finance-agent-core/reports` as generated runtime output by default.
2. Commit only canonical release evidence artifacts listed in this spec.
3. Do not commit staged replay input bundles under
   `finance-agent-core/reports/fundamental_replay_inputs/`.
4. Source-of-truth policy file:
   `finance-agent-core/reports/README.md` + `.gitignore`.
5. CI artifact upload remains the default retention channel for non-committed
   runtime artifacts.

Validator:

- `finance-agent-core/scripts/validate_fundamental_cohort_stability_report.py`
  - optional strict mode: `--require-stable --min-considered-runs <N>`
- `finance-agent-core/scripts/validate_fundamental_replay_cohort_gate.py`
  - recommended strict mode:
    `--min-cases 4 --min-unique-tickers 4 --min-pass-rate 1.0`
    `--require-relative-input-paths --require-input-root <dir>`
- `finance-agent-core/scripts/validate_reports_vcs_policy.py`
  - staged commit gate for report file allowlist compliance
