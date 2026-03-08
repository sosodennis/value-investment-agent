from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def test_release_gate_script_generates_report(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = project_root / "scripts" / "run_fundamental_release_gate.sh"
    report_path = tmp_path / "release_gate_report.json"

    env = os.environ.copy()
    env["UV_CACHE_DIR"] = "/tmp/.uv-cache"
    env.pop("FUNDAMENTAL_FORWARD_SIGNAL_CALIBRATION_MAPPING_PATH", None)

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
    assert summary.get("calibration_gate_passed") is True
    assert summary.get("drift_count") == 0


def test_release_gate_script_fails_on_degraded_calibration(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = project_root / "scripts" / "run_fundamental_release_gate.sh"
    report_path = tmp_path / "release_gate_report.json"

    env = os.environ.copy()
    env["UV_CACHE_DIR"] = "/tmp/.uv-cache"
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

    env = os.environ.copy()
    env["UV_CACHE_DIR"] = "/tmp/.uv-cache"
    env["FUNDAMENTAL_REQUIRE_CALIBRATION_PIPELINE_REPORT"] = "1"
    env.pop("FUNDAMENTAL_FORWARD_SIGNAL_CALIBRATION_MAPPING_PATH", None)

    completed = subprocess.run(
        ["bash", str(script_path), str(report_path), str(pipeline_report_path)],
        check=False,
        capture_output=True,
        text=True,
        cwd=project_root,
        env=env,
    )

    assert completed.returncode == 4


def test_release_gate_script_fails_on_missing_replay_manifest(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = project_root / "scripts" / "run_fundamental_release_gate.sh"
    report_path = tmp_path / "release_gate_report.json"

    env = os.environ.copy()
    env["UV_CACHE_DIR"] = "/tmp/.uv-cache"
    env["FUNDAMENTAL_REPLAY_MANIFEST_PATH"] = str(tmp_path / "missing_manifest.json")
    env.pop("FUNDAMENTAL_FORWARD_SIGNAL_CALIBRATION_MAPPING_PATH", None)

    completed = subprocess.run(
        ["bash", str(script_path), str(report_path)],
        check=False,
        capture_output=True,
        text=True,
        cwd=project_root,
        env=env,
    )

    assert completed.returncode == 5
    assert "replay_manifest_check_failed" in completed.stderr
    assert "error_code=manifest_file_not_found" in completed.stderr


def test_release_gate_script_reports_replay_manifest_error_code(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = project_root / "scripts" / "run_fundamental_release_gate.sh"
    report_path = tmp_path / "release_gate_report.json"
    invalid_manifest_path = tmp_path / "invalid_manifest.json"
    invalid_manifest_path.write_text(
        json.dumps({"schema_version": "valuation_replay_manifest_v1", "cases": []}),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["UV_CACHE_DIR"] = "/tmp/.uv-cache"
    env["FUNDAMENTAL_REPLAY_MANIFEST_PATH"] = str(invalid_manifest_path)
    env.pop("FUNDAMENTAL_FORWARD_SIGNAL_CALIBRATION_MAPPING_PATH", None)

    completed = subprocess.run(
        ["bash", str(script_path), str(report_path)],
        check=False,
        capture_output=True,
        text=True,
        cwd=project_root,
        env=env,
    )

    assert completed.returncode == 5
    assert "replay_manifest_check_failed" in completed.stderr
    assert "error_code=manifest_invalid_schema" in completed.stderr
