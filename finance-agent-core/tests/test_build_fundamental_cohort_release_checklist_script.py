from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_build_release_checklist_from_snapshot(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = (
        project_root / "scripts" / "build_fundamental_cohort_release_checklist.py"
    )
    snapshot_path = tmp_path / "snapshot.json"
    output_path = tmp_path / "checklist.md"
    snapshot_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-03-09T12:00:00+00:00",
                "gate_profile": "ci_cohort_v1",
                "release_gate_exit_code": 0,
                "report_path": "reports/fundamental_backtest_report_ci.json",
                "replay_report_path": "reports/fundamental_replay_checks_report_ci.json",
                "live_replay_run_path": "reports/fundamental_live_replay_cohort_run_ci.json",
                "summary": {
                    "total_cases": 4,
                    "ok": 4,
                    "errors": 0,
                    "consensus_gap_distribution": {
                        "available_count": 4,
                        "median": 0.11,
                        "p90_abs": 0.18,
                    },
                    "replay_checks": {
                        "trace_contract_pass_rate": 1.0,
                    },
                    "live_replay": {
                        "gate_passed": True,
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
        [
            sys.executable,
            str(script_path),
            "--snapshot",
            str(snapshot_path),
            "--output",
            str(output_path),
            "--owner",
            "ci-bot",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    payload = output_path.read_text(encoding="utf-8")
    assert "Owner: ci-bot" in payload
    assert "Release decision: `Approve`" in payload
    assert "live_replay_gate_passed: true" in payload
