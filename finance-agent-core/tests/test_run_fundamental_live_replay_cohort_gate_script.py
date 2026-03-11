from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path


def test_run_live_replay_cohort_gate_end_to_end(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = (
        project_root / "scripts" / "run_fundamental_live_replay_cohort_gate.py"
    )
    fixture_dir = project_root / "tests" / "fixtures" / "fundamental_replay_inputs"

    discover_root = tmp_path / "discover"
    discover_root.mkdir(parents=True, exist_ok=True)
    for name in ("aapl.replay.json", "nvda.replay.json"):
        (discover_root / f"{name}.replay-input.v2.json").write_text(
            (fixture_dir / name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )

    output_dir = tmp_path / "reports"
    config_path = tmp_path / "live_config.json"
    config_path.write_text(
        json.dumps(
            {
                "schema_version": "fundamental_live_replay_cohort_config_v1",
                "profile": "test_live_cohort",
                "discover_root": str(discover_root),
                "discover_glob": "*.replay-input.v2.json",
                "discover_recursive": False,
                "ticker_allowlist": ["AAPL", "NVDA"],
                "latest_per_ticker": True,
                "min_cases": 2,
                "min_unique_tickers": 2,
                "min_pass_rate": 1.0,
                "stage_root": str(tmp_path / "stage"),
                "stage_prefix": "live_test",
                "require_relative_input_paths": True,
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
            "--config",
            str(config_path),
            "--output-dir",
            str(output_dir),
            "--cycle-tag",
            "s22test",
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
    assert payload["max_intrinsic_delta_p90_abs"] is None

    manifest_path = Path(payload["manifest_path"])
    replay_report_path = Path(payload["replay_report_path"])
    gate_path = Path(payload["cohort_gate_path"])
    run_path = Path(payload["run_path"])
    assert manifest_path.exists()
    assert replay_report_path.exists()
    assert gate_path.exists()
    assert run_path.exists()

    gate_payload = json.loads(gate_path.read_text(encoding="utf-8"))
    assert gate_payload["gate_passed"] is True
    assert gate_payload["manifest_cases"] == 2


def test_run_live_replay_cohort_gate_uses_discover_root_env_key(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = (
        project_root / "scripts" / "run_fundamental_live_replay_cohort_gate.py"
    )
    fixture_dir = project_root / "tests" / "fixtures" / "fundamental_replay_inputs"

    discover_root = tmp_path / "discover"
    discover_root.mkdir(parents=True, exist_ok=True)
    for name in ("aapl.replay.json", "nvda.replay.json"):
        (discover_root / f"{name}.replay-input.v2.json").write_text(
            (fixture_dir / name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )

    output_dir = tmp_path / "reports"
    config_path = tmp_path / "live_config_env.json"
    config_path.write_text(
        json.dumps(
            {
                "schema_version": "fundamental_live_replay_cohort_config_v1",
                "profile": "test_live_cohort",
                "discover_root": str(tmp_path / "fallback_discover_root"),
                "discover_root_env_key": "LIVE_REPLAY_DISCOVER_ROOT",
                "require_discover_root_env": True,
                "discover_glob": "*.replay-input.v2.json",
                "discover_recursive": False,
                "ticker_allowlist": ["AAPL", "NVDA"],
                "latest_per_ticker": True,
                "min_cases": 2,
                "min_unique_tickers": 2,
                "min_pass_rate": 1.0,
                "stage_root": str(tmp_path / "stage"),
                "stage_prefix": "live_test",
                "require_relative_input_paths": True,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    env = dict(os.environ)
    env["LIVE_REPLAY_DISCOVER_ROOT"] = str(discover_root)

    completed = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--config",
            str(config_path),
            "--output-dir",
            str(output_dir),
            "--cycle-tag",
            "s24env",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=project_root,
        env=env,
    )
    assert completed.returncode == 0

    payload = json.loads(completed.stdout)
    assert payload["gate_passed"] is True
    assert Path(payload["discover_root"]) == discover_root
    assert Path(payload["run_path"]).exists()


def test_run_live_replay_cohort_gate_fails_when_required_discover_root_env_missing(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = (
        project_root / "scripts" / "run_fundamental_live_replay_cohort_gate.py"
    )

    output_dir = tmp_path / "reports"
    config_path = tmp_path / "live_config_env_required.json"
    config_path.write_text(
        json.dumps(
            {
                "schema_version": "fundamental_live_replay_cohort_config_v1",
                "profile": "test_live_cohort",
                "discover_root": str(tmp_path / "fallback_discover_root"),
                "discover_root_env_key": "LIVE_REPLAY_DISCOVER_ROOT",
                "require_discover_root_env": True,
                "discover_glob": "*.replay-input.v2.json",
                "discover_recursive": False,
                "ticker_allowlist": ["AAPL", "NVDA"],
                "latest_per_ticker": True,
                "min_cases": 2,
                "min_unique_tickers": 2,
                "min_pass_rate": 1.0,
                "stage_root": str(tmp_path / "stage"),
                "stage_prefix": "live_test",
                "require_relative_input_paths": True,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    env = dict(os.environ)
    env.pop("LIVE_REPLAY_DISCOVER_ROOT", None)

    completed = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--config",
            str(config_path),
            "--output-dir",
            str(output_dir),
            "--cycle-tag",
            "s24envmissing",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=project_root,
        env=env,
    )
    assert completed.returncode != 0
    assert "discover root environment variable required but missing" in completed.stderr


def _load_script_module():
    project_root = Path(__file__).resolve().parents[1]
    script_path = (
        project_root / "scripts" / "run_fundamental_live_replay_cohort_gate.py"
    )
    spec = importlib.util.spec_from_file_location(
        "run_fundamental_live_replay_cohort_gate", script_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(
            "failed to load run_fundamental_live_replay_cohort_gate.py module"
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_run_live_replay_cohort_gate_prefers_env_intrinsic_delta_threshold(
    monkeypatch,
) -> None:
    module = _load_script_module()
    config: Mapping[str, object] = {"max_intrinsic_delta_p90_abs": 450.0}

    monkeypatch.setenv("FUNDAMENTAL_MAX_REPLAY_INTRINSIC_DELTA_P90_ABS", "300.0")
    result = module._resolve_optional_gate_float(
        config=config,
        config_key="max_intrinsic_delta_p90_abs",
        env_key="FUNDAMENTAL_MAX_REPLAY_INTRINSIC_DELTA_P90_ABS",
    )

    assert result == 300.0


def test_build_prewarm_requests_from_manifest_aggregates_tickers(
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    inputs_dir = tmp_path / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)

    (inputs_dir / "aapl_1.json").write_text(
        json.dumps({"ticker": "AAPL", "reports": [{}, {}]}),
        encoding="utf-8",
    )
    (inputs_dir / "aapl_2.json").write_text(
        json.dumps({"ticker": "aapl", "reports": [{}, {}, {}, {}]}),
        encoding="utf-8",
    )
    (inputs_dir / "nvda.json").write_text(
        json.dumps({"ticker": "NVDA", "reports": []}),
        encoding="utf-8",
    )

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "valuation_replay_manifest_v1",
                "cases": [
                    {"case_id": "a1", "input_path": "inputs/aapl_1.json"},
                    {"case_id": "a2", "input_path": "inputs/aapl_2.json"},
                    {"case_id": "n1", "input_path": "inputs/nvda.json"},
                ],
            }
        ),
        encoding="utf-8",
    )

    requests = module._build_prewarm_requests_from_manifest(
        manifest_path=manifest_path,
        default_years=5,
    )
    assert requests == {"AAPL": 4, "NVDA": 5}


def test_run_xbrl_prewarm_from_manifest_uses_injected_fetch_fn(tmp_path: Path) -> None:
    module = _load_script_module()
    inputs_dir = tmp_path / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)

    (inputs_dir / "aapl.json").write_text(
        json.dumps({"ticker": "AAPL", "reports": [{}, {}, {}]}),
        encoding="utf-8",
    )
    (inputs_dir / "nvda.json").write_text(
        json.dumps({"ticker": "NVDA", "reports": [{}, {}]}),
        encoding="utf-8",
    )

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "valuation_replay_manifest_v1",
                "cases": [
                    {"case_id": "a1", "input_path": "inputs/aapl.json"},
                    {"case_id": "n1", "input_path": "inputs/nvda.json"},
                ],
            }
        ),
        encoding="utf-8",
    )

    calls: list[tuple[str, int]] = []

    def _fake_fetch(ticker: str, years: int) -> Mapping[str, object]:
        calls.append((ticker, years))
        hit = ticker == "NVDA"
        return {"diagnostics": {"cache": {"cache_hit": hit}}}

    summary = module._run_xbrl_prewarm_from_manifest(
        manifest_path=manifest_path,
        default_years=5,
        enabled=True,
        fetch_payload_fn=_fake_fetch,
    )
    assert calls == [("AAPL", 3), ("NVDA", 2)]
    assert summary["enabled"] is True
    assert summary["requested_tickers"] == 2
    assert summary["succeeded_tickers"] == 2
    assert summary["failed_tickers"] == 0
    assert summary["cache_hit_after_prewarm_rate"] == 0.5


def test_resolve_optional_gate_int_prefers_env_override(monkeypatch) -> None:
    module = _load_script_module()
    config: Mapping[str, object] = {"max_validation_rule_drift_count": 3}

    monkeypatch.setenv("FUNDAMENTAL_MAX_REPLAY_VALIDATION_RULE_DRIFT_COUNT", "1")
    result = module._resolve_optional_gate_int(
        config=config,
        config_key="max_validation_rule_drift_count",
        env_key="FUNDAMENTAL_MAX_REPLAY_VALIDATION_RULE_DRIFT_COUNT",
    )

    assert result == 1
