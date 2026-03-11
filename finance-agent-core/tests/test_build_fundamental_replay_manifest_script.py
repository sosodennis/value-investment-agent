from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from src.agents.fundamental.subdomains.core_valuation.interface.replay_contracts import (
    parse_valuation_replay_manifest_model,
)


def test_build_replay_manifest_from_v2_inputs(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = project_root / "scripts" / "build_fundamental_replay_manifest.py"
    fixture_dir = project_root / "tests" / "fixtures" / "fundamental_replay_inputs"
    output_path = tmp_path / "manifest.json"

    completed = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--inputs",
            str(fixture_dir / "aapl.replay.json"),
            str(fixture_dir / "nvda.replay.json"),
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
    manifest = parse_valuation_replay_manifest_model(
        payload,
        context="test.build_manifest",
    )
    assert manifest.schema_version == "valuation_replay_manifest_v1"
    assert len(manifest.cases) == 2
    case_ids = {case.case_id for case in manifest.cases}
    assert any(case_id.startswith("AAPL_") for case_id in case_ids)
    assert any(case_id.startswith("NVDA_") for case_id in case_ids)


def test_build_replay_manifest_stages_inputs_when_stage_dir_provided(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = project_root / "scripts" / "build_fundamental_replay_manifest.py"
    fixture_dir = project_root / "tests" / "fixtures" / "fundamental_replay_inputs"
    stage_dir = tmp_path / "staged_inputs"
    output_path = tmp_path / "manifest_staged.json"

    completed = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--inputs",
            str(fixture_dir / "aapl.replay.json"),
            str(fixture_dir / "nvda.replay.json"),
            "--stage-dir",
            str(stage_dir),
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
    manifest = parse_valuation_replay_manifest_model(
        payload,
        context="test.build_manifest_staged",
    )
    assert len(manifest.cases) == 2
    for case in manifest.cases:
        assert not Path(case.input_path).is_absolute()
        resolved = (output_path.parent / case.input_path).resolve()
        assert resolved.exists()
        assert stage_dir.resolve() in resolved.parents


def test_build_replay_manifest_discovers_inputs_from_directory(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = project_root / "scripts" / "build_fundamental_replay_manifest.py"
    fixture_dir = project_root / "tests" / "fixtures" / "fundamental_replay_inputs"
    discover_dir = tmp_path / "discover"
    discover_dir.mkdir(parents=True, exist_ok=True)
    output_path = tmp_path / "manifest_discovered.json"

    for name in ("aapl.replay.json", "nvda.replay.json"):
        (discover_dir / name).write_text(
            (fixture_dir / name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )

    completed = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--discover-root",
            str(discover_dir),
            "--discover-glob",
            "*.replay.json",
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
    manifest = parse_valuation_replay_manifest_model(
        payload,
        context="test.build_manifest_discovered",
    )
    assert len(manifest.cases) == 2


def test_build_replay_manifest_keeps_latest_per_ticker_when_enabled(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = project_root / "scripts" / "build_fundamental_replay_manifest.py"
    fixture_dir = project_root / "tests" / "fixtures" / "fundamental_replay_inputs"
    discover_dir = tmp_path / "discover_latest"
    discover_dir.mkdir(parents=True, exist_ok=True)
    output_path = tmp_path / "manifest_latest.json"

    older_aapl = discover_dir / "aapl_older.replay.json"
    newer_aapl = discover_dir / "aapl_newer.replay.json"
    nvda = discover_dir / "nvda.replay.json"
    older_aapl.write_text(
        (fixture_dir / "aapl.replay.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    nvda.write_text(
        (fixture_dir / "nvda.replay.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    newer_aapl.write_text(
        (fixture_dir / "aapl.replay.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    os.utime(older_aapl, (1_700_000_000, 1_700_000_000))
    os.utime(newer_aapl, (1_800_000_000, 1_800_000_000))
    os.utime(nvda, (1_800_000_001, 1_800_000_001))

    completed = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--discover-root",
            str(discover_dir),
            "--discover-glob",
            "*.replay.json",
            "--ticker-allowlist",
            "AAPL,NVDA",
            "--latest-per-ticker",
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
    manifest = parse_valuation_replay_manifest_model(
        payload,
        context="test.build_manifest_latest",
    )
    assert len(manifest.cases) == 2
    input_paths = [case.input_path for case in manifest.cases]
    assert any("aapl_newer.replay.json" in item for item in input_paths)
    assert all("aapl_older.replay.json" not in item for item in input_paths)


def test_build_replay_manifest_skips_invalid_inputs_by_default(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = project_root / "scripts" / "build_fundamental_replay_manifest.py"
    fixture_dir = project_root / "tests" / "fixtures" / "fundamental_replay_inputs"
    discover_dir = tmp_path / "discover_invalid"
    discover_dir.mkdir(parents=True, exist_ok=True)
    output_path = tmp_path / "manifest_skip_invalid.json"

    (discover_dir / "aapl.replay.json").write_text(
        (fixture_dir / "aapl.replay.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (discover_dir / "broken.replay.json").write_text(
        '{"schema_version":"valuation_replay_input_v1"}\n',
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--discover-root",
            str(discover_dir),
            "--discover-glob",
            "*.replay.json",
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
    manifest = parse_valuation_replay_manifest_model(
        payload,
        context="test.build_manifest_skip_invalid",
    )
    assert len(manifest.cases) == 1
