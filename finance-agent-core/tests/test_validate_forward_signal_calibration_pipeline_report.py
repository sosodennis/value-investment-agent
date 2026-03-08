from __future__ import annotations

import json
import subprocess
from pathlib import Path


def test_validate_calibration_pipeline_report_passes(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = (
        project_root
        / "scripts"
        / "validate_forward_signal_calibration_pipeline_report.py"
    )
    report_path = tmp_path / "pipeline_report.json"
    report_path.write_text(
        json.dumps(
            {
                "row_count": 10,
                "usable_row_count": 8,
                "anchor_stats": {"resolved_count": 8},
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            "python",
            str(script_path),
            "--path",
            str(report_path),
            "--min-usable-rows",
            "6",
            "--min-anchor-coverage",
            "0.7",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=project_root,
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["gate_passed"] is True


def test_validate_calibration_pipeline_report_fails_on_threshold(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = (
        project_root
        / "scripts"
        / "validate_forward_signal_calibration_pipeline_report.py"
    )
    report_path = tmp_path / "pipeline_report.json"
    report_path.write_text(
        json.dumps(
            {
                "row_count": 10,
                "usable_row_count": 3,
                "anchor_stats": {"resolved_count": 4},
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            "python",
            str(script_path),
            "--path",
            str(report_path),
            "--min-usable-rows",
            "5",
            "--min-anchor-coverage",
            "0.6",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=project_root,
    )

    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    assert payload["gate_passed"] is False
    issues = payload.get("issues")
    assert isinstance(issues, list)
    assert any("usable_row_count_below_threshold" in item for item in issues)
    assert any("anchor_coverage_below_threshold" in item for item in issues)
