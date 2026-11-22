"""Exercise the smoke's completion gate with activity and artifact responses."""

import json
import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "status,pending,outputs,artifact_code,expected_error",
    [
        ("completed", [], True, "200", None),
        ("completed", [], False, "200", "missing_completed_output"),
        (
            "completed",
            [{"kind": "ticker_selection", "status": "pending"}],
            True,
            "200",
            "pending_workflow_interaction",
        ),
        ("completed", [], True, "403", "artifact_fetch_failed"),
        ("failed", [], True, "200", "run_status_failed"),
        ("waiting", [], True, "200", "completion_timeout_waiting"),
    ],
)
def test_completion_requires_finished_workflow_and_accessible_output(
    tmp_path, status, pending, outputs, artifact_code, expected_error
):
    snapshot = {
        "run_status": status,
        "cursor": 8,
        "pending_interactions": pending,
        "completed_outputs": [
            {"identity": {"run_id": "run-test"}, "artifact_id": "artifact-test"}
        ]
        if outputs
        else [],
    }
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot))
    source = (ROOT / "scripts/refactor_staging_smoke.sh").read_text()
    completion_function = source.split("\ncompletion() {", 1)[1].split(
        "\nif ! health_check;", 1
    )[0]
    command = r"""
set -euo pipefail
THREAD_ID=thread-test
CSRF_TOKEN=csrf-test
RETRY_ATTEMPTS=1
COMPLETION_WAIT_SECONDS=0
COMPLETION_POLL_SECONDS=0
response_body="$TEST_RESPONSE_PATH"
request() {
  REQUEST_ID=request-test
  REQUEST_LATENCY_MS=1
  case "$2" in
    */runs) REQUEST_CODE=202; printf '{"run_id":"run-test"}' > "$response_body" ;;
    */activities*) REQUEST_CODE=200; cp "$TEST_SNAPSHOT_PATH" "$response_body" ;;
    */artifacts/*) REQUEST_CODE="$TEST_ARTIFACT_CODE"; printf '{"data":{}}' > "$response_body" ;;
    *) return 2 ;;
  esac
}
record() { printf '%s %s %s\n' "$1" "$2" "${6:-}"; }
"""
    result = subprocess.run(
        [
            "bash",
            "-c",
            command + "\ncompletion() {" + completion_function + "\ncompletion",
        ],
        env={
            **os.environ,
            "TEST_SNAPSHOT_PATH": str(snapshot_path),
            "TEST_RESPONSE_PATH": str(tmp_path / "response.json"),
            "TEST_ARTIFACT_CODE": artifact_code,
        },
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if expected_error is None:
        assert result.returncode == 0, result.stderr
        assert "completion VERIFIED" in result.stdout
    else:
        assert result.returncode == 1, result.stderr
        assert f"completion NOT_VERIFIED {expected_error}" in result.stdout
