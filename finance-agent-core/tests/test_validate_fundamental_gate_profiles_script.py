from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_validate_gate_profiles_passes_for_valid_config() -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = project_root / "scripts" / "validate_fundamental_gate_profiles.py"
    config_path = project_root / "config" / "fundamental_gate_profiles.json"

    completed = subprocess.run(
        [sys.executable, str(script_path), "--path", str(config_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["gate_passed"] is True
    assert payload["issues"] == []


def test_validate_gate_profiles_fails_for_missing_required_thresholds(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = project_root / "scripts" / "validate_fundamental_gate_profiles.py"
    invalid_config_path = tmp_path / "invalid_gate_profiles.json"
    invalid_config_path.write_text(
        json.dumps(
            {
                "schema_version": "fundamental_gate_profiles_v1",
                "default_profile": "ci_cohort_v1",
                "profiles": {
                    "ci_cohort_v1": {
                        "description": "invalid profile",
                        "thresholds": {"max_extreme_upside_rate": 0.3},
                    }
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
        [sys.executable, str(script_path), "--path", str(invalid_config_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    assert payload["gate_passed"] is False
    assert any(
        issue.startswith("profile_threshold_missing:ci_cohort_v1.")
        for issue in payload["issues"]
    )
