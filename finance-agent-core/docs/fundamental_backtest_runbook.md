# Fundamental Backtest Runbook

This runbook covers the minimal backtest workflow for Sprint `FA-303`.

`FB-035` policy: release/replay governance now runs in Arelle-first mode only.
No legacy parser fallback path is considered in release gating.

## Files

- Dataset: `finance-agent-core/tests/fixtures/fundamental_backtest_cases.json`
- Baseline: `finance-agent-core/tests/fixtures/fundamental_backtest_baseline.json`
- Runner: `finance-agent-core/scripts/run_fundamental_backtest.py`
- Calibration validator: `finance-agent-core/scripts/validate_forward_signal_calibration_artifact.py`
- Reinvestment clamp profile validator:
  `finance-agent-core/scripts/validate_fundamental_reinvestment_clamp_profile.py`
- Reports VCS policy validator:
  `finance-agent-core/scripts/validate_reports_vcs_policy.py`
- Release gate script: `finance-agent-core/scripts/run_fundamental_release_gate.sh`
- Cohort stability report builder:
  `finance-agent-core/scripts/build_fundamental_cohort_stability_report.py`
- Report output: `finance-agent-core/reports/fundamental_backtest_report.json`
- Report VCS policy: `finance-agent-core/reports/README.md`

## Report Version-Control Policy

`finance-agent-core/reports` is a generated-artifact directory.

Commit only canonical release evidence files (snapshot/checklist/backtest/live
replay/cohort gate/stability/calibration pipeline report). Do not commit
`reports/fundamental_replay_inputs/` bundles or exploratory probe/debug outputs.
Use CI uploaded artifacts as retention for non-committed runtime outputs.

## Commands

1. Validate calibration artifact (release gate prerequisite):

```bash
UV_CACHE_DIR=/tmp/.uv-cache uv run --project finance-agent-core python finance-agent-core/scripts/validate_forward_signal_calibration_artifact.py
```

1. Validate reinvestment clamp profile artifact (release gate prerequisite):

```bash
UV_CACHE_DIR=/tmp/.uv-cache uv run --project finance-agent-core python finance-agent-core/scripts/validate_fundamental_reinvestment_clamp_profile.py \
  --path finance-agent-core/src/agents/fundamental/domain/valuation/parameterization/config/reinvestment_clamp_profile.default.json \
  --max-age-days 21 \
  --min-evidence-refs 1
```

2. Rebuild baseline from current engine outputs:

```bash
UV_CACHE_DIR=/tmp/.uv-cache uv run --project finance-agent-core python finance-agent-core/scripts/run_fundamental_backtest.py --update-baseline
```

3. Run comparison against baseline:

```bash
UV_CACHE_DIR=/tmp/.uv-cache uv run --project finance-agent-core python finance-agent-core/scripts/run_fundamental_backtest.py
```

Optional: override monitoring gates during release diagnostics:

```bash
UV_CACHE_DIR=/tmp/.uv-cache uv run --project finance-agent-core python finance-agent-core/scripts/run_fundamental_backtest.py \
  --max-extreme-upside-rate 0.30 \
  --min-guardrail-hit-rate 0.00 \
  --min-reinvestment-guardrail-hit-rate 0.00 \
  --max-shares-scope-mismatch-rate 1.00 \
  --max-consensus-gap-median-abs 0.15 \
  --max-consensus-gap-p90-abs 0.60 \
  --min-consensus-gap-count 20 \
  --max-consensus-degraded-rate 0.80 \
  --min-consensus-confidence-weight 0.30 \
  --min-consensus-quality-count 20 \
  --max-consensus-provider-blocked-rate 1.00 \
  --max-consensus-parse-missing-rate 1.00 \
  --min-consensus-warning-code-count 0
```

4. Run CI-equivalent release gate locally:

```bash
bash finance-agent-core/scripts/run_fundamental_release_gate.sh
```

Profile-driven execution (recommended):

```bash
FUNDAMENTAL_GATE_PROFILE=prod_cohort_v1 \
FUNDAMENTAL_GATE_PROFILES_PATH=finance-agent-core/config/fundamental_gate_profiles.json \
bash finance-agent-core/scripts/run_fundamental_release_gate.sh
```

Optional dataset override (for prod-like cohort validation):

```bash
FUNDAMENTAL_BACKTEST_DATASET_PATH=tests/fixtures/fundamental_backtest_cases_prod_cohort.json \
FUNDAMENTAL_BACKTEST_BASELINE_PATH=tests/fixtures/fundamental_backtest_baseline_prod_cohort.json \
FUNDAMENTAL_GATE_PROFILE=prod_cohort_v1 \
FUNDAMENTAL_GATE_PROFILES_PATH=finance-agent-core/config/fundamental_gate_profiles.json \
bash finance-agent-core/scripts/run_fundamental_release_gate.sh
```

Validate staged report files before commit:

```bash
UV_CACHE_DIR=/tmp/.uv-cache uv run --project finance-agent-core python finance-agent-core/scripts/validate_reports_vcs_policy.py
```

Release gate now runs canonical live replay cohort checks only (no legacy
`FUNDAMENTAL_REPLAY_MANIFEST_PATH` path):

```bash
FUNDAMENTAL_LIVE_REPLAY_COHORT_CONFIG_PATH=finance-agent-core/config/fundamental_live_replay_cohort_config_ci.json \
FUNDAMENTAL_LIVE_REPLAY_DISCOVER_ROOT=finance-agent-core/tests/fixtures/fundamental_replay_inputs \
bash finance-agent-core/scripts/run_fundamental_release_gate.sh
```

Run replay checks standalone:

```bash
UV_CACHE_DIR=/tmp/.uv-cache uv run --project finance-agent-core python finance-agent-core/scripts/run_fundamental_replay_checks.py \
  --manifest finance-agent-core/tests/fixtures/fundamental_replay_manifest_ci.json \
  --report finance-agent-core/reports/fundamental_replay_checks_report_ci.json
```

Replay contract gate now hard-checks terminal-growth and forward-signal trace fields
for each successful case:

1. `replayed_terminal_growth_fallback_mode`
2. `replayed_terminal_growth_anchor_source`
3. `replayed_forward_signal.calibration_applied`
4. `replayed_forward_signal.mapping_version`
5. `replayed_forward_signal.{raw_,}growth|margin_adjustment_basis_points`
6. `replayed_forward_signal.calibration_degraded_reason` (key required, value can be `null`)

Missing fields are reported as `error_code=terminal_growth_path_missing` or
`error_code=forward_signal_trace_missing` and will fail live replay cohort gate with
exit code `8` in release-gate flow.

For FB-034 governance hardening, market consensus now follows two hard rules:

1. Single-source consensus must be degraded (`fallback_reason=single_source_consensus`,
   `target_consensus_quality_bucket=degraded`, low confidence weight).
2. Canonical market datum fields are normalized before snapshot persistence:
   - `target_mean_price.horizon` defaults to `12m` when missing.
   - `shares_outstanding.shares_scope` defaults to `unknown` when missing.

## CI Integration

- Workflow: `.github/workflows/monorepo-contract-gates.yml`
- Job: `fundamental-release-gate`
- Output artifact: `fundamental-backtest-report` (`finance-agent-core/reports/fundamental_backtest_report_ci.json`)
- Output artifact: `fundamental-release-gate-snapshot` (`finance-agent-core/reports/fundamental_release_gate_snapshot_ci.json`)
- Snapshot validator: `finance-agent-core/scripts/validate_fundamental_release_gate_snapshot.py`
- Checklist builder: `finance-agent-core/scripts/build_fundamental_cohort_release_checklist.py`
- Gate profile config: `finance-agent-core/config/fundamental_gate_profiles.json`
- Gate profile resolver: `finance-agent-core/scripts/resolve_fundamental_gate_profile.py`
- Gate profile validator: `finance-agent-core/scripts/validate_fundamental_gate_profiles.py`
- Replay trace gate validator: `finance-agent-core/scripts/validate_fundamental_replay_trace_gate.py`
- Cohort stability report validator: `finance-agent-core/scripts/validate_fundamental_cohort_stability_report.py`
- Note: release gate script still attempts backtest report generation even when calibration validator fails, so CI can upload a diagnostic report.

## Exit Codes

- `0`: all cases pass, no drifts, no issues.
- `1`: one or more case execution errors.
- `2`: drift detected or baseline consistency issues detected.
- `3`: calibration artifact gate failed (runner degraded to embedded default mapping).
- `4`: monitoring gate failed (`extreme_upside_rate` / `guardrail_hit_rate` / `reinvestment_guardrail_hit_rate` / `shares_scope_mismatch_rate` / `consensus_gap_distribution`).
- `6`: gate profile resolution failed (`FUNDAMENTAL_GATE_PROFILE` / `FUNDAMENTAL_GATE_PROFILES_PATH` invalid).
- `8`: live replay cohort gate failed (`FUNDAMENTAL_LIVE_REPLAY_COHORT_CONFIG_PATH` enabled run failed).
- `9`: reinvestment clamp profile gate failed (`FUNDAMENTAL_REINVESTMENT_CLAMP_PROFILE_PATH` missing/invalid/stale or insufficient evidence refs).

## Report Fields

- `summary.total_cases`: total cases in dataset.
- `summary.ok`: successful valuation cases.
- `summary.errors`: failed valuation cases.
- `summary.drift_count`: number of numeric drift points.
- `summary.issue_count`: missing baseline/model mismatch issues.
- `summary.calibration_gate_passed`: whether calibration artifact gate passed.
- `summary.extreme_upside_rate`: fraction of cases where `upside_potential > +80%`.
- `summary.guardrail_hit_rate`: fraction of cases where base guardrail was applied (`guardrail_hit` or component flags).
- `summary.reinvestment_guardrail_hit_rate`: fraction of cases where reinvestment guardrail was applied (`base_capex_guardrail_applied` or `base_wc_guardrail_applied`).
- `summary.shares_scope_mismatch_rate`: fraction of cases with unresolved share-scope mismatch (`shares_scope_mismatch_detected=true` and not resolved).
- `summary.consensus_gap_distribution`: aggregate distribution stats (`available_count`, `median`, `p10`, `p90`, `mean`, `mean_abs`, `p90_abs`, `max_abs`) when consensus anchors exist.
- `summary.consensus_quality_distribution`: consensus quality coverage stats (`available_count`, `high_rate`, `medium_rate`, `low_rate`, `degraded_rate`).
- `summary.consensus_warning_code_distribution`: warning-code coverage stats (`available_count`, `code_case_counts`, `code_case_rates`).
- `summary.consensus_degraded_rate`: aggregate degraded ratio across cases with quality coverage.
- `summary.consensus_confidence_weight_avg`: average consensus confidence weight across covered cases.
- `summary.consensus_provider_blocked_rate`: warning-code ratio for provider-blocked scenarios (`provider_blocked`).
- `summary.consensus_parse_missing_rate`: warning-code ratio for parse-missing scenarios (`provider_parse_missing`).
- `calibration.mapping_version`: loaded mapping version.
- `calibration.mapping_source`: `env_path` / `default_artifact` / `embedded_default`.
- `calibration.mapping_path`: artifact path attempted by loader.
- `calibration.degraded_reason`: populated when artifact load/parse failed.
- `reports/fundamental_reinvestment_clamp_profile_validation_report*.json`:
  profile gate artifact (`profile_version`, `as_of_date`, `age_days`, `evidence_ref_count`, `issues`).
- replay report `delta_by_parameter_group`: one-at-a-time parameter attribution (`growth|margin|reinvestment|terminal`) with `delta_vs_replay` and `intrinsic_if_reverted_to_baseline`.
- replay checks summary `quality_block_rate`: cohort ratio of replay cases marked as XBRL quality blocked.
- replay checks summary `validation_block_rate`: canonical validation blocker ratio (alias of quality blocker ratio for release governance).
- replay checks summary `cache_hit_rate`: cohort ratio of replay cases with cache-hit classification.
- replay checks summary `warm_latency_p90_ms` / `cold_latency_p90_ms`: cohort p90 latency split by warm (`cache_hit=true`) vs cold path.
- replay checks summary `validation_rule_runtime`: runtime rule snapshot (`validation_mode` / `disclosure_system` / `plugins` / `packages` / `arelle_version` / `signature`).
- replay checks summary `validation_rule_drift_count`: expected-vs-actual rule-signature drift count (`0` means no drift).
- `results[]`: per-case status and extracted key metrics.
- `drifts[]`: metric-level baseline vs current differences.

## Default Monitoring Gates

- `max_extreme_upside_rate=0.30`
- `min_guardrail_hit_rate=0.00`
- `min_reinvestment_guardrail_hit_rate=0.00`
- `max_shares_scope_mismatch_rate=1.00`
- `max_consensus_gap_median_abs=0.15`
- `max_consensus_gap_p90_abs=0.60`
- `min_consensus_gap_count=2` (set to `20+` for production-like cohort gates)
- `max_consensus_degraded_rate=1.00` (tighten for cohort release, e.g. `0.80`)
- `min_consensus_confidence_weight=0.00` (tighten for cohort release, e.g. `0.30`)
- `min_consensus_quality_count=0` (set to `20+` for production-like cohort gates)
- `max_consensus_provider_blocked_rate=1.00` (profile can tighten for free-provider stability governance)
- `max_consensus_parse_missing_rate=1.00` (profile can tighten for parser drift governance)
- `min_consensus_warning_code_count=0` (set higher only when warning-code coverage is expected)
- `min_replay_trace_contract_pass_rate=1.00` (strict contract gate; should normally stay at `1.00`)
- `max_replay_intrinsic_delta_p90_abs=1000.0` (CI baseline; tighten for prod-like profile, e.g. `450.0`)
- `max_replay_quality_block_rate=0.0` (hard quality blocker: no blocked cases allowed)
- `min_replay_cache_hit_rate=0.0` (profile can tighten this for high-throughput runs)
- `max_replay_warm_latency_p90_ms=120000.0` (profile can tighten to environment budget)
- `max_replay_cold_latency_p90_ms=120000.0` (profile can tighten to environment budget)
- `max_replay_validation_rule_drift_count=0` (hard governance default: no rule-version drift allowed when expected signature is configured)

## Cohort Release Checklist

Use this checklist before promoting new calibration/profile artifacts:

1. Run release gate with explicit cohort thresholds.
2. Confirm `summary.consensus_gap_distribution.available_count` meets cohort minimum.
3. Confirm `|summary.consensus_gap_distribution.median| <= threshold`.
4. Confirm `summary.consensus_gap_distribution.p90_abs <= threshold`.
5. Confirm `summary.consensus_degraded_rate <= threshold`.
6. Confirm `summary.consensus_confidence_weight_avg >= threshold`.
7. Record report path and artifact version in release note.

Template: `finance-agent-core/docs/fundamental_cohort_release_checklist_template.md`.
Artifact spec: `finance-agent-core/docs/fundamental_cohort_report_artifact_spec.md`.

## Rolling Stability Report (FB-034-S15)

Use the latest release-gate snapshots to evaluate rolling cohort stability:

```bash
UV_CACHE_DIR=/tmp/.uv-cache uv run --project finance-agent-core python finance-agent-core/scripts/build_fundamental_cohort_stability_report.py \
  --snapshots \
    finance-agent-core/reports/fundamental_release_gate_snapshot_s14_prod.json \
    finance-agent-core/reports/fundamental_release_gate_snapshot_s17_prod.json \
  --output finance-agent-core/reports/fundamental_cohort_stability_report_s17_prod.json \
  --expected-profile prod_cohort_v1 \
  --window-size 2 \
  --min-runs 2
```

Interpretation:

1. `summary.stable=true` means the rolling window passed all KPI checks.
2. `summary.stability_reasons` lists exact blockers when unstable.
3. `runs[].failed_checks` gives per-run failure reasons for threshold tuning.

Validate rolling stability gate:

```bash
UV_CACHE_DIR=/tmp/.uv-cache uv run --project finance-agent-core python finance-agent-core/scripts/validate_fundamental_cohort_stability_report.py \
  --path finance-agent-core/reports/fundamental_cohort_stability_report_s17_prod.json \
  --require-stable \
  --min-considered-runs 2
```

## Live Replay Cohort Gate (FB-034-S21)

Use user-provided replay inputs (AAPL/MSFT/GOOG/NVDA etc.) to run a broader
non-fixture replay cohort gate:

```bash
UV_CACHE_DIR=/tmp/.uv-cache uv run --project finance-agent-core python finance-agent-core/scripts/build_fundamental_replay_manifest.py \
  --discover-root /tmp/fundamental-replay-inputs \
  --discover-glob '*.replay-input*.json' \
  --ticker-allowlist 'AAPL,MSFT,GOOG,NVDA' \
  --latest-per-ticker \
  --stage-dir finance-agent-core/reports/fundamental_replay_inputs/live_s21 \
  --output finance-agent-core/reports/fundamental_replay_manifest_live_s21.json
```

Note: builder now enforces `valuation_replay_input_v2` and automatically skips
non-v2/legacy replay inputs discovered in the directory.

```bash
UV_CACHE_DIR=/tmp/.uv-cache uv run --project finance-agent-core python finance-agent-core/scripts/run_fundamental_replay_checks.py \
  --manifest finance-agent-core/reports/fundamental_replay_manifest_live_s21.json \
  --report finance-agent-core/reports/fundamental_replay_checks_report_live_s21.json
```

```bash
UV_CACHE_DIR=/tmp/.uv-cache uv run --project finance-agent-core python finance-agent-core/scripts/validate_fundamental_replay_cohort_gate.py \
  --manifest finance-agent-core/reports/fundamental_replay_manifest_live_s21.json \
  --report finance-agent-core/reports/fundamental_replay_checks_report_live_s21.json \
  --min-cases 4 \
  --min-unique-tickers 4 \
  --min-pass-rate 1.0 \
  --max-intrinsic-delta-p90-abs 450.0 \
  --require-relative-input-paths \
  --require-input-root finance-agent-core/reports/fundamental_replay_inputs/live_s21
```

One-command mode via config/env (FB-034-S22):

```bash
UV_CACHE_DIR=/tmp/.uv-cache uv run --project finance-agent-core python finance-agent-core/scripts/run_fundamental_live_replay_cohort_gate.py \
  --config finance-agent-core/config/fundamental_live_replay_cohort_config.json \
  --cycle-tag s22_live
```

Env overrides:

1. `FUNDAMENTAL_LIVE_REPLAY_DISCOVER_ROOT`
2. `FUNDAMENTAL_LIVE_REPLAY_TICKER_ALLOWLIST`
3. `FUNDAMENTAL_MAX_REPLAY_INTRINSIC_DELTA_P90_ABS`

Config-driven discover root binding (FB-034-S24):

1. `discover_root_env_key`: explicit env var key used to resolve `discover_root`.
2. `require_discover_root_env`: when `true`, gate run fails if the keyed env var is missing.
3. Discover root resolution order:
   - CLI `--discover-root`
   - config `discover_root_env_key` (if set)
   - legacy env `FUNDAMENTAL_LIVE_REPLAY_DISCOVER_ROOT`
   - config `discover_root`

CI integration (FB-034-S23):

1. workflow step runs:
   `scripts/run_fundamental_live_replay_cohort_gate.py --config config/fundamental_live_replay_cohort_config_ci.json --cycle-tag ci`
2. uploaded artifacts:
   - `reports/fundamental_cohort_release_checklist_ci.md`
   - `reports/fundamental_live_replay_cohort_run_ci.json`
   - `reports/fundamental_replay_manifest_live_ci.json`
   - `reports/fundamental_replay_checks_report_live_ci.json`
   - `reports/fundamental_replay_cohort_gate_ci.json`

Release-gate main flow integration (FB-034-S25):

1. `run_fundamental_release_gate.sh` can run live replay cohort gate directly when
   `FUNDAMENTAL_LIVE_REPLAY_COHORT_CONFIG_PATH` is set.
2. Recommended env set:
   - `FUNDAMENTAL_LIVE_REPLAY_COHORT_CONFIG_PATH`
   - `FUNDAMENTAL_LIVE_REPLAY_COHORT_OUTPUT_DIR`
   - `FUNDAMENTAL_LIVE_REPLAY_COHORT_CYCLE_TAG`
   - `FUNDAMENTAL_LIVE_REPLAY_COHORT_RUN_PATH`
   - `FUNDAMENTAL_LIVE_REPLAY_DISCOVER_ROOT` (when config requires env binding)
3. On failure, script emits `error_code=live_replay_cohort_gate_failed|live_replay_cohort_runtime_error`
   and exits with code `8`.
