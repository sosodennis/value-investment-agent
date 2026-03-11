from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_validate_release_gate_snapshot_passes_for_valid_payload(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = (
        project_root / "scripts" / "validate_fundamental_release_gate_snapshot.py"
    )
    snapshot_path = tmp_path / "snapshot_valid.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-03-09T10:00:00+00:00",
                "gate_profile": "ci_cohort_v1",
                "release_gate_exit_code": 0,
                "gate_error_codes": [],
                "report_path": "reports/fundamental_backtest_report_ci.json",
                "report_available": True,
                "replay_report_path": "reports/fundamental_replay_checks_report_ci.json",
                "replay_report_available": True,
                "live_replay_run_path": "reports/fundamental_live_replay_cohort_run_ci.json",
                "live_replay_run_available": True,
                "thresholds": {
                    "max_consensus_gap_median_abs": 0.15,
                    "max_consensus_gap_p90_abs": 0.60,
                    "min_replay_trace_contract_pass_rate": 1.0,
                },
                "summary": {
                    "total_cases": 4,
                    "ok": 4,
                    "errors": 0,
                    "issue_count": 0,
                    "consensus_degraded_rate": 0.25,
                    "consensus_confidence_weight_avg": 0.7,
                    "shares_scope_mismatch_rate": 0.0,
                    "guardrail_hit_rate": 0.5,
                    "consensus_provider_blocked_rate": 0.25,
                    "consensus_parse_missing_rate": 0.0,
                    "consensus_gap_distribution": {
                        "available_count": 4,
                        "median": 0.12,
                        "p90_abs": 0.55,
                    },
                    "consensus_warning_code_distribution": {
                        "available_count": 4,
                        "code_case_counts": {
                            "provider_blocked": 1,
                            "single_source_consensus": 2,
                        },
                        "code_case_rates": {
                            "provider_blocked": 0.25,
                            "single_source_consensus": 0.5,
                        },
                    },
                    "replay_checks": {
                        "total_cases": 2,
                        "passed_cases": 2,
                        "failed_cases": 0,
                        "trace_contract_pass_rate": 1.0,
                        "quality_block_rate": 0.0,
                        "validation_block_rate": 0.0,
                        "cache_hit_rate": 0.5,
                        "warm_latency_p90_ms": 120.0,
                        "cold_latency_p90_ms": 450.0,
                        "error_code_counts": {},
                    },
                    "live_replay": {
                        "gate_passed": True,
                        "issues": [],
                    },
                },
                "issues": [],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [sys.executable, str(script_path), "--path", str(snapshot_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    output = json.loads(completed.stdout)
    assert output["gate_passed"] is True
    assert output["issues"] == []


def test_validate_release_gate_snapshot_fails_for_missing_required_fields(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = (
        project_root / "scripts" / "validate_fundamental_release_gate_snapshot.py"
    )
    snapshot_path = tmp_path / "snapshot_invalid.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-03-09T10:00:00+00:00",
                "gate_profile": "ci_cohort_v1",
                "release_gate_exit_code": 4,
                "gate_error_codes": [],
                "report_path": "reports/fundamental_backtest_report_ci.json",
                "report_available": True,
                "thresholds": {},
                "summary": {
                    "total_cases": 4,
                    "ok": 4,
                    "errors": 0,
                    "issue_count": 1,
                    "consensus_degraded_rate": 0.25,
                    "consensus_confidence_weight_avg": 0.7,
                    "shares_scope_mismatch_rate": 0.0,
                    "guardrail_hit_rate": 0.5,
                    "consensus_gap_distribution": {"available_count": 3},
                },
                "issues": [],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [sys.executable, str(script_path), "--path", str(snapshot_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 1
    output = json.loads(completed.stdout)
    assert output["gate_passed"] is False
    assert (
        "summary.consensus_gap_distribution.median_missing_or_invalid"
        in output["issues"]
    )
    assert (
        "summary.consensus_gap_distribution.p90_abs_missing_or_invalid"
        in output["issues"]
    )


def test_validate_release_gate_snapshot_fails_when_replay_summary_missing(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = (
        project_root / "scripts" / "validate_fundamental_release_gate_snapshot.py"
    )
    snapshot_path = tmp_path / "snapshot_invalid_replay.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-03-09T10:00:00+00:00",
                "gate_profile": "ci_cohort_v1",
                "release_gate_exit_code": 0,
                "gate_error_codes": [],
                "report_path": "reports/fundamental_backtest_report_ci.json",
                "report_available": True,
                "replay_report_path": "reports/fundamental_replay_checks_report_ci.json",
                "replay_report_available": True,
                "thresholds": {},
                "summary": {
                    "total_cases": 4,
                    "ok": 4,
                    "errors": 0,
                    "issue_count": 0,
                    "consensus_degraded_rate": 0.0,
                    "consensus_confidence_weight_avg": 0.7,
                    "shares_scope_mismatch_rate": 0.0,
                    "guardrail_hit_rate": 0.5,
                    "consensus_gap_distribution": {
                        "available_count": 4,
                        "median": 0.0,
                        "p90_abs": 0.1,
                    },
                },
                "issues": [],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [sys.executable, str(script_path), "--path", str(snapshot_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 1
    output = json.loads(completed.stdout)
    assert output["gate_passed"] is False
    assert "summary.replay_checks_missing_or_invalid" in output["issues"]


def test_validate_release_gate_snapshot_fails_when_live_replay_summary_missing(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = (
        project_root / "scripts" / "validate_fundamental_release_gate_snapshot.py"
    )
    snapshot_path = tmp_path / "snapshot_invalid_live_replay.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-03-09T10:00:00+00:00",
                "gate_profile": "ci_cohort_v1",
                "release_gate_exit_code": 0,
                "gate_error_codes": [],
                "report_path": "reports/fundamental_backtest_report_ci.json",
                "report_available": True,
                "replay_report_path": "reports/fundamental_replay_checks_report_ci.json",
                "replay_report_available": True,
                "live_replay_run_path": "reports/fundamental_live_replay_cohort_run_ci.json",
                "live_replay_run_available": True,
                "thresholds": {},
                "summary": {
                    "total_cases": 4,
                    "ok": 4,
                    "errors": 0,
                    "issue_count": 0,
                    "consensus_degraded_rate": 0.0,
                    "consensus_confidence_weight_avg": 0.7,
                    "shares_scope_mismatch_rate": 0.0,
                    "guardrail_hit_rate": 0.5,
                    "consensus_gap_distribution": {
                        "available_count": 4,
                        "median": 0.0,
                        "p90_abs": 0.1,
                    },
                    "replay_checks": {
                        "total_cases": 2,
                        "passed_cases": 2,
                        "failed_cases": 0,
                        "trace_contract_pass_rate": 1.0,
                    },
                },
                "issues": [],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [sys.executable, str(script_path), "--path", str(snapshot_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 1
    output = json.loads(completed.stdout)
    assert output["gate_passed"] is False
    assert "summary.live_replay_missing_or_invalid" in output["issues"]


def test_validate_release_gate_snapshot_fails_when_reinvestment_profile_summary_missing(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = (
        project_root / "scripts" / "validate_fundamental_release_gate_snapshot.py"
    )
    snapshot_path = tmp_path / "snapshot_invalid_reinvestment_profile.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-03-09T10:00:00+00:00",
                "gate_profile": "ci_cohort_v1",
                "release_gate_exit_code": 0,
                "gate_error_codes": [],
                "report_path": "reports/fundamental_backtest_report_ci.json",
                "report_available": True,
                "replay_report_path": "reports/fundamental_replay_checks_report_ci.json",
                "replay_report_available": True,
                "live_replay_run_path": "reports/fundamental_live_replay_cohort_run_ci.json",
                "live_replay_run_available": True,
                "reinvestment_clamp_profile_report_path": "reports/fundamental_reinvestment_clamp_profile_validation_report_ci.json",
                "reinvestment_clamp_profile_report_available": True,
                "thresholds": {},
                "summary": {
                    "total_cases": 4,
                    "ok": 4,
                    "errors": 0,
                    "issue_count": 0,
                    "consensus_degraded_rate": 0.0,
                    "consensus_confidence_weight_avg": 0.7,
                    "shares_scope_mismatch_rate": 0.0,
                    "guardrail_hit_rate": 0.5,
                    "consensus_gap_distribution": {
                        "available_count": 4,
                        "median": 0.0,
                        "p90_abs": 0.1,
                    },
                    "replay_checks": {
                        "total_cases": 2,
                        "passed_cases": 2,
                        "failed_cases": 0,
                        "trace_contract_pass_rate": 1.0,
                    },
                    "live_replay": {
                        "gate_passed": True,
                        "issues": [],
                    },
                },
                "issues": [],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [sys.executable, str(script_path), "--path", str(snapshot_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 1
    output = json.loads(completed.stdout)
    assert output["gate_passed"] is False
    assert "summary.reinvestment_clamp_profile_missing_or_invalid" in output["issues"]
