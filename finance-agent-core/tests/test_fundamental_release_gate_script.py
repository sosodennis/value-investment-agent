from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _base_env(*, project_root: Path, tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["UV_CACHE_DIR"] = "/tmp/.uv-cache"
    env["FUNDAMENTAL_LIVE_REPLAY_COHORT_CONFIG_PATH"] = str(
        project_root / "config" / "fundamental_live_replay_cohort_config_ci.json"
    )
    env["FUNDAMENTAL_LIVE_REPLAY_COHORT_OUTPUT_DIR"] = str(tmp_path / "live_reports")
    env["FUNDAMENTAL_LIVE_REPLAY_COHORT_CYCLE_TAG"] = "release_gate_test"
    env["FUNDAMENTAL_LIVE_REPLAY_DISCOVER_ROOT"] = str(
        project_root / "tests" / "fixtures" / "fundamental_replay_inputs"
    )
    env.pop("FUNDAMENTAL_FORWARD_SIGNAL_CALIBRATION_MAPPING_PATH", None)
    env.pop("FUNDAMENTAL_REPLAY_MANIFEST_PATH", None)
    env.pop("FUNDAMENTAL_REPLAY_REPORT_PATH", None)
    env.pop("FUNDAMENTAL_MIN_REPLAY_TRACE_CONTRACT_PASS_RATE", None)
    env.pop("FUNDAMENTAL_MAX_REPLAY_INTRINSIC_DELTA_P90_ABS", None)
    env.pop("FUNDAMENTAL_MAX_REPLAY_QUALITY_BLOCK_RATE", None)
    env.pop("FUNDAMENTAL_MIN_REPLAY_CACHE_HIT_RATE", None)
    env.pop("FUNDAMENTAL_MAX_REPLAY_WARM_LATENCY_P90_MS", None)
    env.pop("FUNDAMENTAL_MAX_REPLAY_COLD_LATENCY_P90_MS", None)
    env.pop("FUNDAMENTAL_MAX_REPLAY_ARELLE_PARSE_LATENCY_P90_MS", None)
    env.pop("FUNDAMENTAL_MAX_REPLAY_ARELLE_RUNTIME_LOCK_WAIT_P90_MS", None)
    env.pop("FUNDAMENTAL_MAX_REPLAY_VALIDATION_RULE_DRIFT_COUNT", None)
    env.pop("FUNDAMENTAL_XBRL_EXPECTED_RULE_SIGNATURE", None)
    env.pop("FUNDAMENTAL_REINVESTMENT_CLAMP_PROFILE_PATH", None)
    env.pop("FUNDAMENTAL_REINVESTMENT_CLAMP_PROFILE_MAX_AGE_DAYS", None)
    env.pop("FUNDAMENTAL_REINVESTMENT_CLAMP_PROFILE_MIN_EVIDENCE_REFS", None)
    env.pop("FUNDAMENTAL_REINVESTMENT_CLAMP_PROFILE_VALIDATION_REPORT_PATH", None)
    return env


def test_release_gate_script_generates_report(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = project_root / "scripts" / "run_fundamental_release_gate.sh"
    report_path = tmp_path / "release_gate_report.json"

    completed = subprocess.run(
        ["bash", str(script_path), str(report_path)],
        check=False,
        capture_output=True,
        text=True,
        cwd=project_root,
        env=_base_env(project_root=project_root, tmp_path=tmp_path),
    )

    assert completed.returncode == 0
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    summary = payload.get("summary")
    assert isinstance(summary, dict)
    assert summary.get("calibration_gate_passed") is True
    assert summary.get("drift_count") == 0


def test_release_gate_script_ignores_legacy_manifest_env(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = project_root / "scripts" / "run_fundamental_release_gate.sh"
    report_path = tmp_path / "release_gate_report.json"
    env = _base_env(project_root=project_root, tmp_path=tmp_path)
    env["FUNDAMENTAL_REPLAY_MANIFEST_PATH"] = str(tmp_path / "missing_manifest.json")

    completed = subprocess.run(
        ["bash", str(script_path), str(report_path)],
        check=False,
        capture_output=True,
        text=True,
        cwd=project_root,
        env=env,
    )

    assert completed.returncode == 0


def test_release_gate_script_fails_on_degraded_calibration(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = project_root / "scripts" / "run_fundamental_release_gate.sh"
    report_path = tmp_path / "release_gate_report.json"
    env = _base_env(project_root=project_root, tmp_path=tmp_path)
    env["FUNDAMENTAL_FORWARD_SIGNAL_CALIBRATION_MAPPING_PATH"] = str(
        tmp_path / "missing_mapping.json"
    )

    completed = subprocess.run(
        ["bash", str(script_path), str(report_path)],
        check=False,
        capture_output=True,
        text=True,
        cwd=project_root,
        env=env,
    )

    assert completed.returncode == 3
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    summary = payload.get("summary")
    assert isinstance(summary, dict)
    assert summary.get("calibration_gate_passed") is False


def test_release_gate_script_fails_when_pipeline_report_gate_missing(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = project_root / "scripts" / "run_fundamental_release_gate.sh"
    report_path = tmp_path / "release_gate_report.json"
    pipeline_report_path = tmp_path / "missing_pipeline_report.json"
    env = _base_env(project_root=project_root, tmp_path=tmp_path)
    env["FUNDAMENTAL_REQUIRE_CALIBRATION_PIPELINE_REPORT"] = "1"

    completed = subprocess.run(
        ["bash", str(script_path), str(report_path), str(pipeline_report_path)],
        check=False,
        capture_output=True,
        text=True,
        cwd=project_root,
        env=env,
    )

    assert completed.returncode == 4


def test_release_gate_script_fails_when_gate_profile_resolution_fails(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = project_root / "scripts" / "run_fundamental_release_gate.sh"
    report_path = tmp_path / "release_gate_report.json"
    env = _base_env(project_root=project_root, tmp_path=tmp_path)
    env["FUNDAMENTAL_GATE_PROFILE"] = "missing_profile"
    env["FUNDAMENTAL_GATE_PROFILES_PATH"] = str(tmp_path / "missing_profiles.json")

    completed = subprocess.run(
        ["bash", str(script_path), str(report_path)],
        check=False,
        capture_output=True,
        text=True,
        cwd=project_root,
        env=env,
    )

    assert completed.returncode == 6
    assert "gate_profile_resolve_failed" in completed.stderr


def test_release_gate_script_supports_custom_backtest_dataset_paths(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = project_root / "scripts" / "run_fundamental_release_gate.sh"
    report_path = tmp_path / "release_gate_report_custom_dataset.json"
    dataset_path = tmp_path / "custom_dataset.json"
    baseline_path = tmp_path / "custom_baseline.json"

    dataset_path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "bank_override_custom_dataset",
                        "model": "bank",
                        "required_metrics": ["equity_value", "cost_of_equity"],
                        "params": {
                            "ticker": "BNK",
                            "rationale": "custom dataset gate path test",
                            "initial_net_income": 100.0,
                            "income_growth_rates": [0.05, 0.05, 0.05],
                            "rwa_intensity": 0.05,
                            "tier1_target_ratio": 0.12,
                            "initial_capital": 200.0,
                            "risk_free_rate": 0.04,
                            "beta": 1.1,
                            "market_risk_premium": 0.05,
                            "cost_of_equity_strategy": "override",
                            "cost_of_equity_override": 0.2,
                            "terminal_growth": 0.02,
                            "shares_outstanding": 100.0,
                        },
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    env = _base_env(project_root=project_root, tmp_path=tmp_path)
    env["FUNDAMENTAL_BACKTEST_DATASET_PATH"] = str(dataset_path)
    env["FUNDAMENTAL_BACKTEST_BASELINE_PATH"] = str(baseline_path)
    env["FUNDAMENTAL_MIN_CONSENSUS_GAP_COUNT"] = "0"
    env["FUNDAMENTAL_MIN_CONSENSUS_QUALITY_COUNT"] = "0"

    build_baseline = subprocess.run(
        [
            sys.executable,
            str(project_root / "scripts" / "run_fundamental_backtest.py"),
            "--dataset",
            str(dataset_path),
            "--baseline",
            str(baseline_path),
            "--report",
            str(tmp_path / "custom_backtest_baseline_build_report.json"),
            "--update-baseline",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=project_root,
        env=env,
    )
    assert build_baseline.returncode == 0

    completed = subprocess.run(
        ["bash", str(script_path), str(report_path)],
        check=False,
        capture_output=True,
        text=True,
        cwd=project_root,
        env=env,
    )

    assert completed.returncode == 0
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    summary = payload.get("summary")
    assert isinstance(summary, dict)
    assert summary.get("total_cases") == 1


def test_release_gate_script_fails_when_live_replay_cohort_runtime_error(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = project_root / "scripts" / "run_fundamental_release_gate.sh"
    report_path = tmp_path / "release_gate_report.json"
    live_config_path = tmp_path / "live_config_required_env.json"
    live_config_path.write_text(
        json.dumps(
            {
                "schema_version": "fundamental_live_replay_cohort_config_v1",
                "profile": "live_cohort_ci_v1",
                "discover_root_env_key": "LIVE_REPLAY_DISCOVER_ROOT",
                "require_discover_root_env": True,
                "discover_root": str(tmp_path / "unused"),
                "discover_glob": "*.replay-input*.json",
                "discover_recursive": True,
                "ticker_allowlist": ["AAPL", "NVDA"],
                "latest_per_ticker": True,
                "min_cases": 2,
                "min_unique_tickers": 2,
                "min_pass_rate": 1.0,
                "stage_root": str(tmp_path / "stage"),
                "stage_prefix": "live_ci",
                "require_relative_input_paths": True,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    env = _base_env(project_root=project_root, tmp_path=tmp_path)
    env["FUNDAMENTAL_LIVE_REPLAY_COHORT_CONFIG_PATH"] = str(live_config_path)
    env.pop("LIVE_REPLAY_DISCOVER_ROOT", None)

    completed = subprocess.run(
        ["bash", str(script_path), str(report_path)],
        check=False,
        capture_output=True,
        text=True,
        cwd=project_root,
        env=env,
    )

    assert completed.returncode == 8
    assert "live_replay_cohort_gate_failed" in completed.stderr
    assert "error_code=live_replay_cohort_runtime_error" in completed.stderr


def test_release_gate_script_runs_live_replay_cohort_gate_when_configured(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = project_root / "scripts" / "run_fundamental_release_gate.sh"
    report_path = tmp_path / "release_gate_report.json"
    live_output_dir = tmp_path / "live_reports"
    live_config_path = tmp_path / "live_config.json"
    fixture_dir = project_root / "tests" / "fixtures" / "fundamental_replay_inputs"
    live_config_path.write_text(
        json.dumps(
            {
                "schema_version": "fundamental_live_replay_cohort_config_v1",
                "profile": "live_cohort_ci_v1",
                "discover_root_env_key": "LIVE_REPLAY_DISCOVER_ROOT",
                "require_discover_root_env": False,
                "discover_root": str(fixture_dir),
                "discover_glob": "*.replay.json",
                "discover_recursive": False,
                "ticker_allowlist": ["AAPL", "NVDA"],
                "latest_per_ticker": True,
                "min_cases": 2,
                "min_unique_tickers": 2,
                "min_pass_rate": 1.0,
                "stage_root": str(tmp_path / "stage"),
                "stage_prefix": "live_ci",
                "require_relative_input_paths": True,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    env = _base_env(project_root=project_root, tmp_path=tmp_path)
    env["FUNDAMENTAL_LIVE_REPLAY_COHORT_CONFIG_PATH"] = str(live_config_path)
    env["FUNDAMENTAL_LIVE_REPLAY_COHORT_OUTPUT_DIR"] = str(live_output_dir)
    env["FUNDAMENTAL_LIVE_REPLAY_COHORT_CYCLE_TAG"] = "rgliveok"
    env.pop("LIVE_REPLAY_DISCOVER_ROOT", None)

    completed = subprocess.run(
        ["bash", str(script_path), str(report_path)],
        check=False,
        capture_output=True,
        text=True,
        cwd=project_root,
        env=env,
    )

    assert completed.returncode == 0
    run_path = live_output_dir / "fundamental_live_replay_cohort_run_rgliveok.json"
    assert run_path.exists()
    run_payload = json.loads(run_path.read_text(encoding="utf-8"))
    assert run_payload["gate_passed"] is True


def test_release_gate_script_fails_when_reinvestment_profile_gate_fails(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = project_root / "scripts" / "run_fundamental_release_gate.sh"
    report_path = tmp_path / "release_gate_report.json"
    env = _base_env(project_root=project_root, tmp_path=tmp_path)
    env["FUNDAMENTAL_REINVESTMENT_CLAMP_PROFILE_PATH"] = str(
        tmp_path / "missing_reinvestment_profile.json"
    )

    completed = subprocess.run(
        ["bash", str(script_path), str(report_path)],
        check=False,
        capture_output=True,
        text=True,
        cwd=project_root,
        env=env,
    )

    assert completed.returncode == 9
    assert "reinvestment_clamp_profile_gate_failed" in completed.stderr
