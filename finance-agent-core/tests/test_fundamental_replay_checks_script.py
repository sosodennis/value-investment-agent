from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import pytest


def _load_script_module():
    project_root = Path(__file__).resolve().parents[1]
    script_path = project_root / "scripts" / "run_fundamental_replay_checks.py"
    spec = importlib.util.spec_from_file_location(
        "run_fundamental_replay_checks", script_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load run_fundamental_replay_checks.py module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_load_manifest_uses_machine_readable_error_code_for_missing_path() -> None:
    module = _load_script_module()
    missing_path = Path("/tmp/replay-manifest-missing.json")
    if missing_path.exists():
        missing_path.unlink()

    with pytest.raises(module.ReplayChecksError) as exc_info:
        module._load_manifest(missing_path)

    assert (
        exc_info.value.error_code
        == module.ReplayChecksErrorCode.MANIFEST_FILE_NOT_FOUND.value
    )


def test_run_replay_checks_generates_error_code_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script_module()
    manifest_path = tmp_path / "manifest.json"
    input_path = tmp_path / "case.json"
    input_path.write_text("{}", encoding="utf-8")
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "valuation_replay_manifest_v1",
                "cases": [{"case_id": "CASE_1", "input_path": "case.json"}],
            }
        ),
        encoding="utf-8",
    )
    report_path = tmp_path / "report.json"

    monkeypatch.setattr(
        module,
        "_run_replay_case",
        lambda **_: (
            1,
            {
                "status": "error",
                "error_code": "legacy_payload_not_supported",
                "error": "legacy payload",
            },
        ),
    )
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: argparse.Namespace(
            manifest=manifest_path,
            report=report_path,
            abs_tol=1e-6,
            rel_tol=1e-4,
        ),
    )

    exit_code = module.main()
    assert exit_code == 5

    report = json.loads(report_path.read_text(encoding="utf-8"))
    summary = report.get("summary")
    assert isinstance(summary, dict)
    assert summary.get("failed_cases") == 1
    assert summary.get("error_code_counts") == {"legacy_payload_not_supported": 1}


def test_run_replay_checks_returns_zero_when_all_cases_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script_module()
    manifest_path = tmp_path / "manifest.json"
    input_path = tmp_path / "case.json"
    input_path.write_text("{}", encoding="utf-8")
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "valuation_replay_manifest_v1",
                "cases": [{"case_id": "CASE_1", "input_path": "case.json"}],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        module,
        "_run_replay_case",
        lambda **_: (
            0,
            {
                "ticker": "AAPL",
                "intrinsic_delta": 0.0,
                "replayed_terminal_growth_fallback_mode": "default_only",
                "replayed_terminal_growth_anchor_source": "default",
            },
        ),
    )
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: argparse.Namespace(
            manifest=manifest_path,
            report=None,
            abs_tol=1e-6,
            rel_tol=1e-4,
        ),
    )

    exit_code = module.main()
    assert exit_code == 0


def test_run_replay_checks_fails_when_terminal_growth_path_fields_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script_module()
    manifest_path = tmp_path / "manifest.json"
    input_path = tmp_path / "case.json"
    input_path.write_text("{}", encoding="utf-8")
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "valuation_replay_manifest_v1",
                "cases": [{"case_id": "CASE_1", "input_path": "case.json"}],
            }
        ),
        encoding="utf-8",
    )
    report_path = tmp_path / "report.json"

    monkeypatch.setattr(
        module,
        "_run_replay_case",
        lambda **_: (0, {"ticker": "AAPL", "intrinsic_delta": 0.0}),
    )
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: argparse.Namespace(
            manifest=manifest_path,
            report=report_path,
            abs_tol=1e-6,
            rel_tol=1e-4,
        ),
    )

    exit_code = module.main()
    assert exit_code == 5
    report = json.loads(report_path.read_text(encoding="utf-8"))
    summary = report.get("summary")
    assert isinstance(summary, dict)
    assert summary.get("failed_cases") == 1
    assert summary.get("error_code_counts") == {"terminal_growth_path_missing": 1}
