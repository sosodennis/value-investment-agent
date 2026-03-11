from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_resolve_gate_profile_emits_env_pairs() -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = project_root / "scripts" / "resolve_fundamental_gate_profile.py"
    config_path = project_root / "config" / "fundamental_gate_profiles.json"

    completed = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--profile",
            "ci_cohort_v1",
            "--path",
            str(config_path),
            "--format",
            "env",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0

    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    mapping = dict(line.split("=", maxsplit=1) for line in lines if "=" in line)
    assert mapping["FUNDAMENTAL_GATE_PROFILE"] == "ci_cohort_v1"
    assert mapping["FUNDAMENTAL_MAX_CONSENSUS_GAP_MEDIAN_ABS"] == "0.15"
    assert mapping["FUNDAMENTAL_MIN_CONSENSUS_GAP_COUNT"] == "2"
    assert mapping["FUNDAMENTAL_MAX_CONSENSUS_PROVIDER_BLOCKED_RATE"] == "1.0"
    assert mapping["FUNDAMENTAL_MAX_CONSENSUS_PARSE_MISSING_RATE"] == "1.0"
    assert mapping["FUNDAMENTAL_MIN_CONSENSUS_WARNING_CODE_COUNT"] == "0"
    assert mapping["FUNDAMENTAL_MIN_REPLAY_TRACE_CONTRACT_PASS_RATE"] == "1.0"
    assert mapping["FUNDAMENTAL_MAX_REPLAY_INTRINSIC_DELTA_P90_ABS"] == "1000.0"
    assert mapping["FUNDAMENTAL_MAX_REPLAY_QUALITY_BLOCK_RATE"] == "0.0"
    assert mapping["FUNDAMENTAL_MIN_REPLAY_CACHE_HIT_RATE"] == "0.0"
    assert mapping["FUNDAMENTAL_MAX_REPLAY_ARELLE_PARSE_LATENCY_P90_MS"] == "120000.0"
    assert (
        mapping["FUNDAMENTAL_MAX_REPLAY_ARELLE_RUNTIME_LOCK_WAIT_P90_MS"] == "120000.0"
    )
    assert mapping["FUNDAMENTAL_MAX_REPLAY_VALIDATION_RULE_DRIFT_COUNT"] == "0"


def test_resolve_gate_profile_fails_for_unknown_profile(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = project_root / "scripts" / "resolve_fundamental_gate_profile.py"
    config_path = tmp_path / "gate_profiles.json"
    config_path.write_text(
        json.dumps(
            {
                "schema_version": "fundamental_gate_profiles_v1",
                "profiles": {},
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
            "--profile",
            "missing_profile",
            "--path",
            str(config_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 0
    assert "profile not found" in completed.stderr.lower()
