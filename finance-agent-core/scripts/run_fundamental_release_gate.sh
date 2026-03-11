#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

REPORT_PATH="${1:-reports/fundamental_backtest_report_ci.json}"
PIPELINE_REPORT_PATH="${2:-reports/forward_signal_calibration_pipeline_report.json}"
BACKTEST_DATASET_PATH="${FUNDAMENTAL_BACKTEST_DATASET_PATH:-tests/fixtures/fundamental_backtest_cases.json}"
BACKTEST_BASELINE_PATH="${FUNDAMENTAL_BACKTEST_BASELINE_PATH:-tests/fixtures/fundamental_backtest_baseline.json}"

# Keep local runs sandbox-friendly; CI can override this env var.
export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/.uv-cache}"

cd "${PROJECT_ROOT}"

if [[ -n "${FUNDAMENTAL_GATE_PROFILE:-}" ]]; then
  gate_profiles_path="${FUNDAMENTAL_GATE_PROFILES_PATH:-config/fundamental_gate_profiles.json}"
  profile_output=""
  profile_status=0
  set +e
  profile_output="$(
    uv run python scripts/resolve_fundamental_gate_profile.py \
      --profile "${FUNDAMENTAL_GATE_PROFILE}" \
      --path "${gate_profiles_path}" \
      --format env 2>&1
  )"
  profile_status=$?
  set -e
  if [[ "${profile_status}" -ne 0 ]]; then
    echo "fundamental_release_gate gate_profile_resolve_failed profile=${FUNDAMENTAL_GATE_PROFILE} path=${gate_profiles_path} details=${profile_output}" >&2
    exit 6
  fi

  while IFS='=' read -r key value; do
    if [[ -z "${key}" ]]; then
      continue
    fi
    if [[ -z "${!key:-}" ]]; then
      export "${key}=${value}"
    fi
  done <<< "${profile_output}"
fi

uv run pytest tests/test_fundamental_backtest_runner.py::test_fixture_dataset_matches_fixture_baseline -q

validator_status=0
uv run python scripts/validate_forward_signal_calibration_artifact.py || validator_status=$?

reinvestment_profile_status=0
reinvestment_profile_path="${FUNDAMENTAL_REINVESTMENT_CLAMP_PROFILE_PATH:-src/agents/fundamental/core_valuation/domain/parameterization/config/reinvestment_clamp_profile.default.json}"
reinvestment_profile_validation_report_path="${FUNDAMENTAL_REINVESTMENT_CLAMP_PROFILE_VALIDATION_REPORT_PATH:-reports/fundamental_reinvestment_clamp_profile_validation_report.json}"
export FUNDAMENTAL_REINVESTMENT_CLAMP_PROFILE_VALIDATION_REPORT_PATH="${reinvestment_profile_validation_report_path}"
uv run python scripts/validate_fundamental_reinvestment_clamp_profile.py \
  --path "${reinvestment_profile_path}" \
  --max-age-days "${FUNDAMENTAL_REINVESTMENT_CLAMP_PROFILE_MAX_AGE_DAYS:-21}" \
  --min-evidence-refs "${FUNDAMENTAL_REINVESTMENT_CLAMP_PROFILE_MIN_EVIDENCE_REFS:-1}" \
  --output "${reinvestment_profile_validation_report_path}" \
  || reinvestment_profile_status=$?
if [[ "${reinvestment_profile_status}" -ne 0 ]]; then
  echo "fundamental_release_gate reinvestment_clamp_profile_gate_failed path=${reinvestment_profile_path} error_code=reinvestment_clamp_profile_gate_failed" >&2
fi

pipeline_validator_status=0
if [[ "${FUNDAMENTAL_REQUIRE_CALIBRATION_PIPELINE_REPORT:-0}" == "1" ]]; then
  uv run python scripts/validate_forward_signal_calibration_pipeline_report.py \
    --path "${PIPELINE_REPORT_PATH}" || pipeline_validator_status=$?
fi

backtest_status=0
uv run python scripts/run_fundamental_backtest.py \
  --dataset "${BACKTEST_DATASET_PATH}" \
  --baseline "${BACKTEST_BASELINE_PATH}" \
  --report "${REPORT_PATH}" \
  --max-extreme-upside-rate "${FUNDAMENTAL_MAX_EXTREME_UPSIDE_RATE:-0.30}" \
  --min-guardrail-hit-rate "${FUNDAMENTAL_MIN_GUARDRAIL_HIT_RATE:-0.00}" \
  --min-reinvestment-guardrail-hit-rate "${FUNDAMENTAL_MIN_REINVESTMENT_GUARDRAIL_HIT_RATE:-0.00}" \
  --max-shares-scope-mismatch-rate "${FUNDAMENTAL_MAX_SHARES_SCOPE_MISMATCH_RATE:-1.00}" \
  --max-consensus-gap-median-abs "${FUNDAMENTAL_MAX_CONSENSUS_GAP_MEDIAN_ABS:-0.15}" \
  --max-consensus-gap-p90-abs "${FUNDAMENTAL_MAX_CONSENSUS_GAP_P90_ABS:-0.60}" \
  --min-consensus-gap-count "${FUNDAMENTAL_MIN_CONSENSUS_GAP_COUNT:-2}" \
  --max-consensus-degraded-rate "${FUNDAMENTAL_MAX_CONSENSUS_DEGRADED_RATE:-1.00}" \
  --min-consensus-confidence-weight "${FUNDAMENTAL_MIN_CONSENSUS_CONFIDENCE_WEIGHT:-0.00}" \
  --min-consensus-quality-count "${FUNDAMENTAL_MIN_CONSENSUS_QUALITY_COUNT:-0}" \
  --max-consensus-provider-blocked-rate "${FUNDAMENTAL_MAX_CONSENSUS_PROVIDER_BLOCKED_RATE:-1.00}" \
  --max-consensus-parse-missing-rate "${FUNDAMENTAL_MAX_CONSENSUS_PARSE_MISSING_RATE:-1.00}" \
  --min-consensus-warning-code-count "${FUNDAMENTAL_MIN_CONSENSUS_WARNING_CODE_COUNT:-0}" \
  || backtest_status=$?

live_replay_status=0
live_replay_config_path="${FUNDAMENTAL_LIVE_REPLAY_COHORT_CONFIG_PATH:-config/fundamental_live_replay_cohort_config.json}"
live_replay_output_dir="${FUNDAMENTAL_LIVE_REPLAY_COHORT_OUTPUT_DIR:-reports}"
live_replay_cycle_tag="${FUNDAMENTAL_LIVE_REPLAY_COHORT_CYCLE_TAG:-release_gate}"
live_replay_run_path="${FUNDAMENTAL_LIVE_REPLAY_COHORT_RUN_PATH:-${live_replay_output_dir}/fundamental_live_replay_cohort_run_${live_replay_cycle_tag}.json}"
export FUNDAMENTAL_LIVE_REPLAY_COHORT_RUN_PATH="${live_replay_run_path}"

live_replay_output=""
live_replay_command_status=0
set +e
live_replay_output="$(
  uv run python scripts/run_fundamental_live_replay_cohort_gate.py \
    --config "${live_replay_config_path}" \
    --output-dir "${live_replay_output_dir}" \
    --cycle-tag "${live_replay_cycle_tag}" 2>&1
)"
live_replay_command_status=$?
set -e
if [[ "${live_replay_command_status}" -ne 0 ]]; then
  live_replay_error_code="live_replay_cohort_runtime_error"
  if printf '%s\n' "${live_replay_output}" | grep -q '"gate_passed"[[:space:]]*:[[:space:]]*false'; then
    live_replay_error_code="live_replay_cohort_gate_failed"
  fi
  echo "fundamental_release_gate live_replay_cohort_gate_failed config_path=${live_replay_config_path} error_code=${live_replay_error_code}" >&2
  live_replay_status=8
elif [[ ! -f "${live_replay_run_path}" ]]; then
  echo "fundamental_release_gate live_replay_cohort_gate_failed config_path=${live_replay_config_path} error_code=live_replay_cohort_run_artifact_missing" >&2
  live_replay_status=8
fi

if [[ "${backtest_status}" -ne 0 ]]; then
  exit "${backtest_status}"
fi

if [[ "${validator_status}" -ne 0 ]]; then
  exit "${validator_status}"
fi

if [[ "${pipeline_validator_status}" -ne 0 ]]; then
  exit 4
fi

if [[ "${reinvestment_profile_status}" -ne 0 ]]; then
  exit 9
fi

if [[ "${live_replay_status}" -ne 0 ]]; then
  exit "${live_replay_status}"
fi
