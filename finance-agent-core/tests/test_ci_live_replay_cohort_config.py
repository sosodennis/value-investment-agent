from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml


def test_ci_live_replay_config_discovers_and_passes_fixture_cohort(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    workflow_path = (
        project_root.parent / ".github" / "workflows" / "monorepo-contract-gates.yml"
    )
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    release_gate_step = next(
        step
        for step in workflow["jobs"]["fundamental-release-gate"]["steps"]
        if step.get("name") == "Run fundamental release gate"
    )
    release_gate_env = release_gate_step["env"]
    profile_path = (
        project_root / release_gate_env["FUNDAMENTAL_REINVESTMENT_CLAMP_PROFILE_PATH"]
    )
    assert profile_path.is_file()

    output_dir = tmp_path / "reports"
    env = os.environ.copy()
    env["FUNDAMENTAL_LIVE_REPLAY_DISCOVER_ROOT"] = str(
        project_root / "tests" / "fixtures" / "fundamental_replay_inputs"
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(
                project_root / "scripts" / "run_fundamental_live_replay_cohort_gate.py"
            ),
            "--config",
            str(
                project_root
                / "config"
                / "fundamental_live_replay_cohort_config_ci.json"
            ),
            "--output-dir",
            str(output_dir),
            "--cycle-tag",
            "config_test",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=project_root,
        env=env,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["gate_passed"] is True
    assert result["issues"] == []
    manifest = json.loads(
        (output_dir / "fundamental_replay_manifest_live_config_test.json").read_text(
            encoding="utf-8"
        )
    )
    assert {case["case_id"].split("_")[0] for case in manifest["cases"]} == {
        "AAPL",
        "NVDA",
    }
