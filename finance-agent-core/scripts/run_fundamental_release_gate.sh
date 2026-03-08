#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

REPORT_PATH="${1:-reports/fundamental_backtest_report_ci.json}"
PIPELINE_REPORT_PATH="${2:-reports/forward_signal_calibration_pipeline_report.json}"

# Keep local runs sandbox-friendly; CI can override this env var.
export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/.uv-cache}"

cd "${PROJECT_ROOT}"

uv run pytest tests/test_fundamental_backtest_runner.py::test_fixture_dataset_matches_fixture_baseline -q

validator_status=0
uv run python scripts/validate_forward_signal_calibration_artifact.py || validator_status=$?

pipeline_validator_status=0
if [[ "${FUNDAMENTAL_REQUIRE_CALIBRATION_PIPELINE_REPORT:-0}" == "1" ]]; then
  uv run python scripts/validate_forward_signal_calibration_pipeline_report.py \
    --path "${PIPELINE_REPORT_PATH}" || pipeline_validator_status=$?
fi

backtest_status=0
uv run python scripts/run_fundamental_backtest.py --report "${REPORT_PATH}" || backtest_status=$?

replay_status=0
if [[ -n "${FUNDAMENTAL_REPLAY_MANIFEST_PATH:-}" ]]; then
  replay_report_path="${FUNDAMENTAL_REPLAY_REPORT_PATH:-reports/fundamental_replay_checks_report.json}"
  replay_output=""
  replay_command_status=0
  set +e
  replay_output="$(uv run python scripts/run_fundamental_replay_checks.py --manifest "${FUNDAMENTAL_REPLAY_MANIFEST_PATH}" --report "${replay_report_path}" 2>&1)"
  replay_command_status=$?
  set -e
  if [[ "${replay_command_status}" -ne 0 ]]; then
    replay_error_code="$(printf '%s\n' "${replay_output}" | sed -n 's/.*"error_code"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | tail -n 1)"
    if [[ -z "${replay_error_code}" ]]; then
      replay_error_code="replay_runtime_error"
    fi
    echo "fundamental_release_gate replay_manifest_check_failed manifest_path=${FUNDAMENTAL_REPLAY_MANIFEST_PATH} error_code=${replay_error_code}" >&2
    replay_status=5
  fi
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

if [[ "${replay_status}" -ne 0 ]]; then
  exit "${replay_status}"
fi
