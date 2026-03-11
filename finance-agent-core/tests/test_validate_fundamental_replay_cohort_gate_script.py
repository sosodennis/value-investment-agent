from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_validate_replay_cohort_gate_passes_for_valid_cohort(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = (
        project_root / "scripts" / "validate_fundamental_replay_cohort_gate.py"
    )
    fixture_dir = project_root / "tests" / "fixtures" / "fundamental_replay_inputs"

    _copy_fixture(fixture_dir / "aapl.replay.json", tmp_path / "aapl.replay.json")
    _copy_fixture(fixture_dir / "nvda.replay.json", tmp_path / "nvda.replay.json")

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "valuation_replay_manifest_v1",
                "cases": [
                    {"case_id": "AAPL_01", "input_path": "aapl.replay.json"},
                    {"case_id": "NVDA_01", "input_path": "nvda.replay.json"},
                ],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    report_path = tmp_path / "replay_report.json"
    report_path.write_text(
        json.dumps(
            {
                "schema_version": "fundamental_replay_checks_report_v1",
                "summary": {
                    "total_cases": 2,
                    "passed_cases": 2,
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
            "--manifest",
            str(manifest_path),
            "--report",
            str(report_path),
            "--min-cases",
            "2",
            "--min-unique-tickers",
            "2",
            "--min-pass-rate",
            "1.0",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=project_root,
    )
    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["gate_passed"] is True
    assert payload["issues"] == []


def test_validate_replay_cohort_gate_fails_on_unique_ticker_coverage(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = (
        project_root / "scripts" / "validate_fundamental_replay_cohort_gate.py"
    )
    fixture_dir = project_root / "tests" / "fixtures" / "fundamental_replay_inputs"

    _copy_fixture(fixture_dir / "aapl.replay.json", tmp_path / "aapl.replay.json")

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "valuation_replay_manifest_v1",
                "cases": [
                    {"case_id": "AAPL_01", "input_path": "aapl.replay.json"},
                    {"case_id": "AAPL_02", "input_path": "aapl.replay.json"},
                ],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    report_path = tmp_path / "replay_report.json"
    report_path.write_text(
        json.dumps(
            {
                "schema_version": "fundamental_replay_checks_report_v1",
                "summary": {
                    "total_cases": 2,
                    "passed_cases": 2,
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
            "--manifest",
            str(manifest_path),
            "--report",
            str(report_path),
            "--min-cases",
            "2",
            "--min-unique-tickers",
            "2",
            "--min-pass-rate",
            "1.0",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=project_root,
    )
    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    assert payload["gate_passed"] is False
    assert "manifest_unique_ticker_count_below_min" in payload["issues"]


def test_validate_replay_cohort_gate_fails_when_absolute_paths_disallowed(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = (
        project_root / "scripts" / "validate_fundamental_replay_cohort_gate.py"
    )
    fixture_dir = project_root / "tests" / "fixtures" / "fundamental_replay_inputs"

    _copy_fixture(fixture_dir / "aapl.replay.json", tmp_path / "aapl.replay.json")
    _copy_fixture(fixture_dir / "nvda.replay.json", tmp_path / "nvda.replay.json")

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "valuation_replay_manifest_v1",
                "cases": [
                    {
                        "case_id": "AAPL_01",
                        "input_path": str(tmp_path / "aapl.replay.json"),
                    },
                    {
                        "case_id": "NVDA_01",
                        "input_path": str(tmp_path / "nvda.replay.json"),
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    report_path = tmp_path / "replay_report.json"
    report_path.write_text(
        json.dumps(
            {
                "schema_version": "fundamental_replay_checks_report_v1",
                "summary": {
                    "total_cases": 2,
                    "passed_cases": 2,
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
            "--manifest",
            str(manifest_path),
            "--report",
            str(report_path),
            "--min-cases",
            "2",
            "--min-unique-tickers",
            "2",
            "--min-pass-rate",
            "1.0",
            "--require-relative-input-paths",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=project_root,
    )
    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    assert payload["gate_passed"] is False
    assert "manifest_input_path_absolute_disallowed" in payload["issues"]


def test_validate_replay_cohort_gate_fails_when_input_outside_required_root(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = (
        project_root / "scripts" / "validate_fundamental_replay_cohort_gate.py"
    )
    fixture_dir = project_root / "tests" / "fixtures" / "fundamental_replay_inputs"

    root_dir = tmp_path / "root"
    root_dir.mkdir(parents=True, exist_ok=True)
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir(parents=True, exist_ok=True)

    inside_input = root_dir / "aapl.replay.json"
    outside_input = outside_dir / "nvda.replay.json"
    _copy_fixture(fixture_dir / "aapl.replay.json", inside_input)
    _copy_fixture(fixture_dir / "nvda.replay.json", outside_input)

    manifest_path = root_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "valuation_replay_manifest_v1",
                "cases": [
                    {"case_id": "AAPL_01", "input_path": "aapl.replay.json"},
                    {
                        "case_id": "NVDA_01",
                        "input_path": str(Path("..") / "outside" / outside_input.name),
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    report_path = root_dir / "replay_report.json"
    report_path.write_text(
        json.dumps(
            {
                "schema_version": "fundamental_replay_checks_report_v1",
                "summary": {
                    "total_cases": 2,
                    "passed_cases": 2,
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
            "--manifest",
            str(manifest_path),
            "--report",
            str(report_path),
            "--min-cases",
            "2",
            "--min-unique-tickers",
            "2",
            "--min-pass-rate",
            "1.0",
            "--require-relative-input-paths",
            "--require-input-root",
            str(root_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=project_root,
    )
    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    assert payload["gate_passed"] is False
    assert "manifest_input_path_outside_required_root" in payload["issues"]


def test_validate_replay_cohort_gate_fails_when_intrinsic_delta_p90_abs_above_max(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = (
        project_root / "scripts" / "validate_fundamental_replay_cohort_gate.py"
    )
    fixture_dir = project_root / "tests" / "fixtures" / "fundamental_replay_inputs"

    _copy_fixture(fixture_dir / "aapl.replay.json", tmp_path / "aapl.replay.json")
    _copy_fixture(fixture_dir / "nvda.replay.json", tmp_path / "nvda.replay.json")

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "valuation_replay_manifest_v1",
                "cases": [
                    {"case_id": "AAPL_01", "input_path": "aapl.replay.json"},
                    {"case_id": "NVDA_01", "input_path": "nvda.replay.json"},
                ],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    report_path = tmp_path / "replay_report.json"
    report_path.write_text(
        json.dumps(
            {
                "schema_version": "fundamental_replay_checks_report_v1",
                "summary": {
                    "total_cases": 2,
                    "passed_cases": 2,
                    "failed_cases": 0,
                    "trace_contract_pass_rate": 1.0,
                    "intrinsic_delta_available_cases": 2,
                    "intrinsic_delta_p90_abs": 120.0,
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
            "--manifest",
            str(manifest_path),
            "--report",
            str(report_path),
            "--min-cases",
            "2",
            "--min-unique-tickers",
            "2",
            "--min-pass-rate",
            "1.0",
            "--max-intrinsic-delta-p90-abs",
            "100.0",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=project_root,
    )
    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    assert payload["gate_passed"] is False
    assert "replay_report_intrinsic_delta_p90_abs_above_max" in payload["issues"]


def test_validate_replay_cohort_gate_fails_on_quality_and_performance_thresholds(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = (
        project_root / "scripts" / "validate_fundamental_replay_cohort_gate.py"
    )
    fixture_dir = project_root / "tests" / "fixtures" / "fundamental_replay_inputs"

    _copy_fixture(fixture_dir / "aapl.replay.json", tmp_path / "aapl.replay.json")
    _copy_fixture(fixture_dir / "nvda.replay.json", tmp_path / "nvda.replay.json")

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "valuation_replay_manifest_v1",
                "cases": [
                    {"case_id": "AAPL_01", "input_path": "aapl.replay.json"},
                    {"case_id": "NVDA_01", "input_path": "nvda.replay.json"},
                ],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    report_path = tmp_path / "replay_report.json"
    report_path.write_text(
        json.dumps(
            {
                "schema_version": "fundamental_replay_checks_report_v1",
                "summary": {
                    "total_cases": 2,
                    "passed_cases": 2,
                    "failed_cases": 0,
                    "trace_contract_pass_rate": 1.0,
                    "quality_block_rate": 0.5,
                    "cache_hit_rate": 0.2,
                    "warm_latency_p90_ms": 220.0,
                    "cold_latency_p90_ms": 900.0,
                    "arelle_parse_latency_p90_ms": 1800.0,
                    "arelle_runtime_lock_wait_p90_ms": 450.0,
                    "validation_rule_drift_count": 2,
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
            "--manifest",
            str(manifest_path),
            "--report",
            str(report_path),
            "--min-cases",
            "2",
            "--min-unique-tickers",
            "2",
            "--min-pass-rate",
            "1.0",
            "--max-quality-block-rate",
            "0.0",
            "--min-cache-hit-rate",
            "0.8",
            "--max-warm-latency-p90-ms",
            "100.0",
            "--max-cold-latency-p90-ms",
            "500.0",
            "--max-arelle-parse-latency-p90-ms",
            "1000.0",
            "--max-arelle-runtime-lock-wait-p90-ms",
            "200.0",
            "--max-validation-rule-drift-count",
            "0",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=project_root,
    )
    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    assert payload["gate_passed"] is False
    assert "replay_report_quality_block_rate_above_max" in payload["issues"]
    assert "replay_report_cache_hit_rate_below_min" in payload["issues"]
    assert "replay_report_warm_latency_p90_ms_above_max" in payload["issues"]
    assert "replay_report_cold_latency_p90_ms_above_max" in payload["issues"]
    assert "replay_report_arelle_parse_latency_p90_ms_above_max" in payload["issues"]
    assert (
        "replay_report_arelle_runtime_lock_wait_p90_ms_above_max" in payload["issues"]
    )
    assert "replay_report_validation_rule_drift_count_above_max" in payload["issues"]


def _copy_fixture(src: Path, dst: Path) -> None:
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
