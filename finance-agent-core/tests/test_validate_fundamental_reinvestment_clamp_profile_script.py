from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


def test_validate_reinvestment_clamp_profile_passes_for_valid_payload(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = (
        project_root / "scripts" / "validate_fundamental_reinvestment_clamp_profile.py"
    )
    profile_path = tmp_path / "profile_valid.json"
    report_path = tmp_path / "validation_report.json"
    as_of = datetime.now(timezone.utc).date().isoformat()
    profile_path.write_text(
        json.dumps(
            {
                "schema_version": "fundamental_reinvestment_clamp_profile_v1",
                "profile_version": "reinvestment_clamp_profile_v1_test",
                "as_of_date": as_of,
                "dcf_growth": {
                    "severe_scope_mismatch_ratio_threshold": 0.45,
                    "severe_mismatch_capex_terminal_lower_min": 0.14,
                    "severe_mismatch_capex_terminal_lower_year1_ratio": 1.25,
                    "severe_mismatch_wc_terminal_lower_min": 0.025,
                    "severe_mismatch_wc_terminal_lower_year1_ratio": 0.35,
                },
                "evidence_refs": ["https://example.com/a"],
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--path",
            str(profile_path),
            "--max-age-days",
            "21",
            "--min-evidence-refs",
            "1",
            "--output",
            str(report_path),
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
    report_payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert report_payload["gate_passed"] is True


def test_validate_reinvestment_clamp_profile_fails_for_stale_date(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = (
        project_root / "scripts" / "validate_fundamental_reinvestment_clamp_profile.py"
    )
    profile_path = tmp_path / "profile_stale.json"
    stale_date = (datetime.now(timezone.utc).date() - timedelta(days=40)).isoformat()
    profile_path.write_text(
        json.dumps(
            {
                "schema_version": "fundamental_reinvestment_clamp_profile_v1",
                "profile_version": "reinvestment_clamp_profile_v1_test_stale",
                "as_of_date": stale_date,
                "dcf_growth": {
                    "severe_scope_mismatch_ratio_threshold": 0.45,
                    "severe_mismatch_capex_terminal_lower_min": 0.14,
                    "severe_mismatch_capex_terminal_lower_year1_ratio": 1.25,
                    "severe_mismatch_wc_terminal_lower_min": 0.025,
                    "severe_mismatch_wc_terminal_lower_year1_ratio": 0.35,
                },
                "evidence_refs": ["https://example.com/a"],
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--path",
            str(profile_path),
            "--max-age-days",
            "21",
            "--min-evidence-refs",
            "1",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=project_root,
    )
    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    assert payload["gate_passed"] is False
    assert any(item.startswith("profile_stale:") for item in payload["issues"])


def test_validate_reinvestment_clamp_profile_fails_for_missing_evidence_refs(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = (
        project_root / "scripts" / "validate_fundamental_reinvestment_clamp_profile.py"
    )
    profile_path = tmp_path / "profile_no_evidence.json"
    as_of = datetime.now(timezone.utc).date().isoformat()
    profile_path.write_text(
        json.dumps(
            {
                "schema_version": "fundamental_reinvestment_clamp_profile_v1",
                "profile_version": "reinvestment_clamp_profile_v1_test_no_evidence",
                "as_of_date": as_of,
                "dcf_growth": {
                    "severe_scope_mismatch_ratio_threshold": 0.45,
                    "severe_mismatch_capex_terminal_lower_min": 0.14,
                    "severe_mismatch_capex_terminal_lower_year1_ratio": 1.25,
                    "severe_mismatch_wc_terminal_lower_min": 0.025,
                    "severe_mismatch_wc_terminal_lower_year1_ratio": 0.35,
                },
                "evidence_refs": [],
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--path",
            str(profile_path),
            "--max-age-days",
            "21",
            "--min-evidence-refs",
            "1",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=project_root,
    )
    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    assert payload["gate_passed"] is False
    assert any(
        item.startswith("evidence_refs_insufficient:") for item in payload["issues"]
    )
