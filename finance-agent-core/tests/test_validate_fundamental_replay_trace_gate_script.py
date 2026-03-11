from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_validate_replay_trace_gate_passes_when_rate_meets_threshold(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = project_root / "scripts" / "validate_fundamental_replay_trace_gate.py"
    report_path = tmp_path / "replay_checks_report.json"
    report_path.write_text(
        json.dumps(
            {
                "schema_version": "fundamental_replay_checks_report_v1",
                "summary": {
                    "total_cases": 4,
                    "passed_cases": 4,
                    "failed_cases": 0,
                    "trace_contract_pass_rate": 1.0,
                },
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--report",
            str(report_path),
            "--min-pass-rate",
            "1.0",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["gate_passed"] is True
    assert payload["observed_pass_rate"] == 1.0


def test_validate_replay_trace_gate_fails_when_rate_below_threshold(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = project_root / "scripts" / "validate_fundamental_replay_trace_gate.py"
    report_path = tmp_path / "replay_checks_report.json"
    report_path.write_text(
        json.dumps(
            {
                "schema_version": "fundamental_replay_checks_report_v1",
                "summary": {
                    "total_cases": 4,
                    "passed_cases": 3,
                    "failed_cases": 1,
                    "trace_contract_pass_rate": 0.75,
                },
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--report",
            str(report_path),
            "--min-pass-rate",
            "0.8",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    assert payload["gate_passed"] is False
    assert payload["error_code"] == "replay_trace_contract_pass_rate_below_min"


def test_validate_replay_trace_gate_fails_when_total_cases_is_zero(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = project_root / "scripts" / "validate_fundamental_replay_trace_gate.py"
    report_path = tmp_path / "replay_checks_report.json"
    report_path.write_text(
        json.dumps(
            {
                "schema_version": "fundamental_replay_checks_report_v1",
                "summary": {
                    "total_cases": 0,
                    "passed_cases": 0,
                    "failed_cases": 0,
                },
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--report",
            str(report_path),
            "--min-pass-rate",
            "1.0",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    assert payload["gate_passed"] is False
    assert payload["error_code"] == "replay_trace_contract_case_count_invalid"
