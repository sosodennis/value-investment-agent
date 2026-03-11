from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_build_reinvestment_clamp_profile_script_success(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = (
        project_root / "scripts" / "build_fundamental_reinvestment_clamp_profile.py"
    )
    input_path = tmp_path / "profile_input.json"
    output_path = tmp_path / "profile_output.json"

    input_path.write_text(
        json.dumps(
            {
                "schema_version": "fundamental_reinvestment_clamp_profile_input_v1",
                "profile_version": "reinvestment_clamp_profile_v1_2026_03_10",
                "as_of_date": "2026-03-10",
                "dcf_growth": {
                    "severe_scope_mismatch_ratio_threshold": 0.46,
                    "severe_mismatch_capex_terminal_lower_min": 0.15,
                    "severe_mismatch_capex_terminal_lower_year1_ratio": 1.2,
                    "severe_mismatch_wc_terminal_lower_min": 0.03,
                    "severe_mismatch_wc_terminal_lower_year1_ratio": 0.37,
                },
                "evidence_refs": [
                    "https://www.sec.gov/Archives/edgar/data/1652044/000165204425000014/goog-20241231.htm"
                ],
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=project_root,
    )
    assert completed.returncode == 0

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "fundamental_reinvestment_clamp_profile_v1"
    assert payload["profile_version"] == "reinvestment_clamp_profile_v1_2026_03_10"
    dcf_growth = payload["dcf_growth"]
    assert dcf_growth["severe_scope_mismatch_ratio_threshold"] == 0.46
    assert dcf_growth["severe_mismatch_capex_terminal_lower_min"] == 0.15


def test_build_reinvestment_clamp_profile_script_rejects_invalid_input(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = (
        project_root / "scripts" / "build_fundamental_reinvestment_clamp_profile.py"
    )
    input_path = tmp_path / "profile_input_invalid.json"
    output_path = tmp_path / "profile_output_invalid.json"

    input_path.write_text(
        json.dumps(
            {
                "schema_version": "fundamental_reinvestment_clamp_profile_input_v1",
                "profile_version": "broken",
                "as_of_date": "2026-03-10",
                "dcf_growth": {
                    "severe_scope_mismatch_ratio_threshold": 0.46,
                    "severe_mismatch_capex_terminal_lower_min": 0.15,
                    "severe_mismatch_capex_terminal_lower_year1_ratio": 1.2,
                    "severe_mismatch_wc_terminal_lower_min": 0.03,
                },
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=project_root,
    )
    assert completed.returncode != 0
    assert not output_path.exists()
