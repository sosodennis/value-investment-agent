from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_validate_cohort_stability_report_passes_for_valid_stable_payload(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = (
        project_root / "scripts" / "validate_fundamental_cohort_stability_report.py"
    )
    report_path = tmp_path / "stability_report_valid.json"
    report_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-03-09T07:00:00+00:00",
                "expected_profile": "prod_cohort_v1",
                "window_size": 2,
                "min_runs": 2,
                "input_count": 2,
                "considered_count": 2,
                "thresholds": {
                    "max_consensus_gap_median_abs": 0.15,
                    "min_consensus_gap_count": 20,
                },
                "runs": [
                    {
                        "snapshot_path": "reports/snapshot_1.json",
                        "snapshot_available": True,
                        "run_passed": True,
                        "kpi_passed": True,
                        "failed_checks": [],
                    },
                    {
                        "snapshot_path": "reports/snapshot_2.json",
                        "snapshot_available": True,
                        "run_passed": True,
                        "kpi_passed": True,
                        "failed_checks": [],
                    },
                ],
                "summary": {
                    "considered_runs": 2,
                    "run_passed_count": 2,
                    "kpi_passed_count": 2,
                    "run_pass_rate": 1.0,
                    "kpi_pass_rate": 1.0,
                    "median_abs_consensus_gap_median": 0.09,
                    "median_consensus_gap_p90_abs": 0.20,
                    "min_consensus_gap_count": 20,
                    "min_consensus_quality_count": 20,
                    "stable": True,
                    "stability_reasons": [],
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
            "--path",
            str(report_path),
            "--require-stable",
            "--min-considered-runs",
            "2",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["gate_passed"] is True
    assert payload["issues"] == []


def test_validate_cohort_stability_report_fails_when_stability_not_met(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = (
        project_root / "scripts" / "validate_fundamental_cohort_stability_report.py"
    )
    report_path = tmp_path / "stability_report_unstable.json"
    report_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-03-09T07:00:00+00:00",
                "expected_profile": "prod_cohort_v1",
                "window_size": 2,
                "min_runs": 2,
                "input_count": 2,
                "considered_count": 1,
                "thresholds": {},
                "runs": [
                    {
                        "snapshot_path": "reports/snapshot_1.json",
                        "snapshot_available": True,
                        "run_passed": False,
                        "kpi_passed": False,
                        "failed_checks": ["consensus_gap_count_below_min"],
                    }
                ],
                "summary": {
                    "considered_runs": 1,
                    "run_passed_count": 0,
                    "kpi_passed_count": 0,
                    "run_pass_rate": 0.0,
                    "kpi_pass_rate": 0.0,
                    "stable": False,
                    "stability_reasons": ["insufficient_runs", "kpi_failures_present"],
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
            "--path",
            str(report_path),
            "--require-stable",
            "--min-considered-runs",
            "2",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    assert payload["gate_passed"] is False
    assert "summary.stable_required_but_false" in payload["issues"]
    assert "summary.considered_runs_below_min" in payload["issues"]
