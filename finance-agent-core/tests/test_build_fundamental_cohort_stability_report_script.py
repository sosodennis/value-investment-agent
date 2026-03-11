from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_cohort_stability_report_detects_unstable_recent_runs(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = (
        project_root / "scripts" / "build_fundamental_cohort_stability_report.py"
    )
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    output_path = tmp_path / "stability_report.json"

    _write_backtest_report(reports_dir / "backtest_s13.json", quality_count=2)
    _write_backtest_report(reports_dir / "backtest_s14.json", quality_count=20)
    _write_snapshot(
        reports_dir / "snapshot_s13.json",
        generated_at="2026-03-09T06:37:24+00:00",
        gate_profile="prod_cohort_v1",
        exit_code=4,
        report_path="reports/backtest_s13.json",
        gap_count=2,
        gap_median=-0.09,
        gap_p90_abs=0.18,
        confidence_weight=0.0,
    )
    _write_snapshot(
        reports_dir / "snapshot_s14.json",
        generated_at="2026-03-09T06:47:22+00:00",
        gate_profile="prod_cohort_v1",
        exit_code=0,
        report_path="reports/backtest_s14.json",
        gap_count=20,
        gap_median=-0.09,
        gap_p90_abs=0.20,
        confidence_weight=0.6,
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--snapshots",
            str(reports_dir / "snapshot_s13.json"),
            str(reports_dir / "snapshot_s14.json"),
            "--output",
            str(output_path),
            "--expected-profile",
            "prod_cohort_v1",
            "--window-size",
            "2",
            "--min-runs",
            "2",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=project_root,
    )

    assert completed.returncode == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    summary = payload["summary"]
    assert summary["considered_runs"] == 2
    assert summary["stable"] is False
    assert "kpi_failures_present" in summary["stability_reasons"]
    assert summary["kpi_passed_count"] == 1
    assert summary["run_passed_count"] == 1


def test_cohort_stability_report_marks_stable_when_recent_runs_all_pass(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = (
        project_root / "scripts" / "build_fundamental_cohort_stability_report.py"
    )
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    output_path = tmp_path / "stability_report_pass.json"

    _write_backtest_report(reports_dir / "backtest_s14.json", quality_count=20)
    _write_backtest_report(reports_dir / "backtest_s15.json", quality_count=24)
    _write_snapshot(
        reports_dir / "snapshot_s14.json",
        generated_at="2026-03-09T06:47:22+00:00",
        gate_profile="prod_cohort_v1",
        exit_code=0,
        report_path="reports/backtest_s14.json",
        gap_count=20,
        gap_median=-0.09,
        gap_p90_abs=0.20,
        confidence_weight=0.6,
    )
    _write_snapshot(
        reports_dir / "snapshot_s15.json",
        generated_at="2026-03-09T08:47:22+00:00",
        gate_profile="prod_cohort_v1",
        exit_code=0,
        report_path="reports/backtest_s15.json",
        gap_count=24,
        gap_median=-0.08,
        gap_p90_abs=0.18,
        confidence_weight=0.7,
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--snapshots",
            str(reports_dir / "snapshot_s14.json"),
            str(reports_dir / "snapshot_s15.json"),
            "--output",
            str(output_path),
            "--expected-profile",
            "prod_cohort_v1",
            "--window-size",
            "2",
            "--min-runs",
            "2",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=project_root,
    )

    assert completed.returncode == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    summary = payload["summary"]
    assert summary["considered_runs"] == 2
    assert summary["stable"] is True
    assert summary["stability_reasons"] == []
    assert summary["kpi_passed_count"] == 2
    assert summary["run_passed_count"] == 2
    assert summary["min_consensus_quality_count"] == 20
    assert summary["min_consensus_gap_count"] == 20


def _write_backtest_report(path: Path, quality_count: int) -> None:
    path.write_text(
        json.dumps(
            {
                "summary": {
                    "consensus_quality_distribution": {
                        "available_count": quality_count,
                    }
                }
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_snapshot(
    path: Path,
    *,
    generated_at: str,
    gate_profile: str,
    exit_code: int,
    report_path: str,
    gap_count: int,
    gap_median: float,
    gap_p90_abs: float,
    confidence_weight: float,
) -> None:
    path.write_text(
        json.dumps(
            {
                "generated_at": generated_at,
                "gate_profile": gate_profile,
                "release_gate_exit_code": exit_code,
                "report_path": report_path,
                "summary": {
                    "consensus_degraded_rate": 0.0,
                    "consensus_confidence_weight_avg": confidence_weight,
                    "consensus_gap_distribution": {
                        "available_count": gap_count,
                        "median": gap_median,
                        "p90_abs": gap_p90_abs,
                    },
                    "replay_checks": {"trace_contract_pass_rate": 1.0},
                },
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
