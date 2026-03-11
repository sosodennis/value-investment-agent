from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_build_release_gate_snapshot_with_report(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = (
        project_root / "scripts" / "build_fundamental_release_gate_snapshot.py"
    )
    report_path = tmp_path / "backtest_report.json"
    replay_report_path = tmp_path / "replay_checks_report.json"
    live_replay_run_path = tmp_path / "live_replay_run.json"
    reinvestment_profile_report_path = tmp_path / "reinvestment_profile_report.json"
    output_path = tmp_path / "gate_snapshot.json"

    report_path.write_text(
        json.dumps(
            {
                "summary": {
                    "total_cases": 4,
                    "ok": 4,
                    "errors": 0,
                    "issue_count": 1,
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
                },
                "issues": ["monitoring_gate_failed:consensus_gap_median_abs=0.1200"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    replay_report_path.write_text(
        json.dumps(
            {
                "summary": {
                    "total_cases": 2,
                    "passed_cases": 2,
                    "failed_cases": 0,
                    "trace_contract_pass_rate": 1.0,
                    "intrinsic_delta_available_cases": 2,
                    "intrinsic_delta_p90_abs": 12.5,
                    "quality_block_rate": 0.0,
                    "validation_block_rate": 0.0,
                    "cache_hit_rate": 0.5,
                    "warm_latency_p90_ms": 120.0,
                    "cold_latency_p90_ms": 450.0,
                    "validation_rule_drift_count": 0,
                    "validation_rule_drift_detected": False,
                    "validation_rule_actual_signature": "actual-signature",
                    "validation_rule_expected_signature": "actual-signature",
                    "validation_rule_runtime": {
                        "validation_mode": "efm_validate",
                        "signature": "actual-signature",
                    },
                    "error_code_counts": {},
                }
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    live_replay_run_path.write_text(
        json.dumps(
            {
                "profile": "live_cohort_ci_v1",
                "cycle_tag": "ci",
                "issues": [],
                "gate_passed": True,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    reinvestment_profile_report_path.write_text(
        json.dumps(
            {
                "gate_passed": True,
                "profile_version": "reinvestment_clamp_profile_v1_2026_03_09",
                "as_of_date": "2026-03-09",
                "age_days": 0,
                "evidence_ref_count": 4,
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
        [
            sys.executable,
            str(script_path),
            "--report",
            str(report_path),
            "--output",
            str(output_path),
            "--exit-code",
            "4",
            "--gate-profile",
            "ci_cohort_v1",
            "--gate-error-codes",
            "terminal_growth_path_missing,replay_runtime_error",
            "--replay-report",
            str(replay_report_path),
            "--live-replay-run-report",
            str(live_replay_run_path),
            "--reinvestment-clamp-profile-report",
            str(reinvestment_profile_report_path),
            "--max-consensus-gap-median-abs",
            "0.15",
            "--max-consensus-gap-p90-abs",
            "0.60",
            "--min-consensus-gap-count",
            "2",
            "--max-consensus-provider-blocked-rate",
            "1.0",
            "--max-consensus-parse-missing-rate",
            "1.0",
            "--min-consensus-warning-code-count",
            "0",
            "--min-replay-trace-contract-pass-rate",
            "1.0",
            "--max-replay-intrinsic-delta-p90-abs",
            "450.0",
            "--max-replay-quality-block-rate",
            "0.0",
            "--min-replay-cache-hit-rate",
            "0.0",
            "--max-replay-warm-latency-p90-ms",
            "120000.0",
            "--max-replay-cold-latency-p90-ms",
            "120000.0",
            "--max-replay-validation-rule-drift-count",
            "0",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["gate_profile"] == "ci_cohort_v1"
    assert payload["release_gate_exit_code"] == 4
    assert payload["report_available"] is True
    assert payload["replay_report_available"] is True
    assert payload["live_replay_run_available"] is True
    assert payload["reinvestment_clamp_profile_report_available"] is True
    assert payload["gate_error_codes"] == [
        "terminal_growth_path_missing",
        "replay_runtime_error",
    ]
    assert payload["thresholds"]["max_consensus_gap_median_abs"] == 0.15
    assert payload["thresholds"]["min_replay_trace_contract_pass_rate"] == 1.0
    assert payload["thresholds"]["max_replay_intrinsic_delta_p90_abs"] == 450.0
    assert payload["thresholds"]["max_replay_quality_block_rate"] == 0.0
    assert payload["thresholds"]["min_replay_cache_hit_rate"] == 0.0
    assert payload["thresholds"]["max_consensus_provider_blocked_rate"] == 1.0
    assert payload["thresholds"]["max_consensus_parse_missing_rate"] == 1.0
    assert payload["thresholds"]["min_consensus_warning_code_count"] == 0
    assert payload["thresholds"]["max_replay_validation_rule_drift_count"] == 0
    assert payload["summary"]["consensus_provider_blocked_rate"] == 0.25
    assert payload["summary"]["consensus_parse_missing_rate"] == 0.0
    assert payload["summary"]["consensus_gap_distribution"]["median"] == 0.12
    warning_distribution = payload["summary"]["consensus_warning_code_distribution"]
    assert warning_distribution["available_count"] == 4
    assert warning_distribution["code_case_counts"]["provider_blocked"] == 1
    assert warning_distribution["code_case_rates"]["provider_blocked"] == 0.25
    replay_checks = payload["summary"]["replay_checks"]
    assert replay_checks["total_cases"] == 2
    assert replay_checks["trace_contract_pass_rate"] == 1.0
    assert replay_checks["intrinsic_delta_available_cases"] == 2
    assert replay_checks["intrinsic_delta_p90_abs"] == 12.5
    assert replay_checks["quality_block_rate"] == 0.0
    assert replay_checks["validation_block_rate"] == 0.0
    assert replay_checks["cache_hit_rate"] == 0.5
    assert replay_checks["validation_rule_drift_count"] == 0
    assert replay_checks["validation_rule_drift_detected"] is False
    live_replay = payload["summary"]["live_replay"]
    assert live_replay["gate_passed"] is True
    assert live_replay["profile"] == "live_cohort_ci_v1"
    reinvestment_profile = payload["summary"]["reinvestment_clamp_profile"]
    assert reinvestment_profile["gate_passed"] is True
    assert (
        reinvestment_profile["profile_version"]
        == "reinvestment_clamp_profile_v1_2026_03_09"
    )
    assert payload["issues"] == [
        "monitoring_gate_failed:consensus_gap_median_abs=0.1200"
    ]


def test_build_release_gate_snapshot_handles_missing_report(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = (
        project_root / "scripts" / "build_fundamental_release_gate_snapshot.py"
    )
    missing_report_path = tmp_path / "missing_report.json"
    output_path = tmp_path / "gate_snapshot_missing_report.json"

    completed = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--report",
            str(missing_report_path),
            "--output",
            str(output_path),
            "--exit-code",
            "5",
            "--gate-profile",
            "ci_cohort_v1",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["release_gate_exit_code"] == 5
    assert payload["report_available"] is False
    assert payload["replay_report_available"] is False
    assert payload["reinvestment_clamp_profile_report_available"] is False
    assert payload["summary"] == {}
    assert payload["issues"] == []
