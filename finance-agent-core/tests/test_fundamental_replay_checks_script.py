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
    assert summary.get("trace_contract_passed_cases") == 0
    assert summary.get("trace_contract_pass_rate") == 0.0
    assert summary.get("error_code_counts") == {"legacy_payload_not_supported": 1}
    assert summary.get("intrinsic_delta_available_cases") == 0
    assert summary.get("intrinsic_delta_p90_abs") is None


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
                "replayed_forward_signal": {
                    "calibration_applied": False,
                    "mapping_version": "forward_signal_calibration_v1",
                    "growth_adjustment_basis_points": 0.0,
                    "margin_adjustment_basis_points": 0.0,
                    "raw_growth_adjustment_basis_points": 0.0,
                    "raw_margin_adjustment_basis_points": 0.0,
                    "calibration_degraded_reason": None,
                },
                "delta_by_parameter_group": {
                    "method": "one_at_a_time_revert_to_baseline",
                    "groups": {},
                },
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


def test_run_replay_checks_carries_delta_by_parameter_group_in_case_output(
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
            0,
            {
                "ticker": "AAPL",
                "intrinsic_delta": 0.0,
                "replayed_terminal_growth_fallback_mode": "default_only",
                "replayed_terminal_growth_anchor_source": "default",
                "replayed_forward_signal": {
                    "calibration_applied": False,
                    "mapping_version": "forward_signal_calibration_v1",
                    "growth_adjustment_basis_points": 0.0,
                    "margin_adjustment_basis_points": 0.0,
                    "raw_growth_adjustment_basis_points": 0.0,
                    "raw_margin_adjustment_basis_points": 0.0,
                    "calibration_degraded_reason": None,
                },
                "delta_by_parameter_group": {
                    "method": "one_at_a_time_revert_to_baseline",
                    "groups": {"growth": {"status": "ok"}},
                },
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
    assert exit_code == 0

    report = json.loads(report_path.read_text(encoding="utf-8"))
    results = report.get("results")
    assert isinstance(results, list)
    first = results[0]
    assert first.get("status") == "ok"
    assert first.get("delta_by_parameter_group") == {
        "method": "one_at_a_time_revert_to_baseline",
        "groups": {"growth": {"status": "ok"}},
    }


def test_run_replay_checks_reports_intrinsic_delta_p90_abs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script_module()
    manifest_path = tmp_path / "manifest.json"
    input_path_1 = tmp_path / "case-1.json"
    input_path_2 = tmp_path / "case-2.json"
    input_path_1.write_text("{}", encoding="utf-8")
    input_path_2.write_text("{}", encoding="utf-8")
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "valuation_replay_manifest_v1",
                "cases": [
                    {"case_id": "CASE_1", "input_path": "case-1.json"},
                    {"case_id": "CASE_2", "input_path": "case-2.json"},
                ],
            }
        ),
        encoding="utf-8",
    )
    report_path = tmp_path / "report.json"
    payloads = [
        {
            "ticker": "AAPL",
            "intrinsic_delta": 10.0,
            "replayed_terminal_growth_fallback_mode": "default_only",
            "replayed_terminal_growth_anchor_source": "default",
            "replayed_forward_signal": {
                "calibration_applied": False,
                "mapping_version": "forward_signal_calibration_v1",
                "growth_adjustment_basis_points": 0.0,
                "margin_adjustment_basis_points": 0.0,
                "raw_growth_adjustment_basis_points": 0.0,
                "raw_margin_adjustment_basis_points": 0.0,
                "calibration_degraded_reason": None,
            },
        },
        {
            "ticker": "NVDA",
            "intrinsic_delta": -30.0,
            "replayed_terminal_growth_fallback_mode": "default_only",
            "replayed_terminal_growth_anchor_source": "default",
            "replayed_forward_signal": {
                "calibration_applied": False,
                "mapping_version": "forward_signal_calibration_v1",
                "growth_adjustment_basis_points": 0.0,
                "margin_adjustment_basis_points": 0.0,
                "raw_growth_adjustment_basis_points": 0.0,
                "raw_margin_adjustment_basis_points": 0.0,
                "calibration_degraded_reason": None,
            },
        },
    ]

    def _fake_run_replay_case(**_: object) -> tuple[int, dict[str, object]]:
        if not payloads:
            raise RuntimeError("unexpected replay invocation count")
        return 0, payloads.pop(0)

    monkeypatch.setattr(module, "_run_replay_case", _fake_run_replay_case)
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
    assert exit_code == 0

    report = json.loads(report_path.read_text(encoding="utf-8"))
    summary = report.get("summary")
    assert isinstance(summary, dict)
    assert summary.get("intrinsic_delta_available_cases") == 2
    assert summary.get("intrinsic_delta_p90_abs") == pytest.approx(28.0)


def test_run_replay_checks_reports_arelle_runtime_latency_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script_module()
    manifest_path = tmp_path / "manifest.json"
    input_path_1 = tmp_path / "case-1.json"
    input_path_2 = tmp_path / "case-2.json"
    input_path_1.write_text("{}", encoding="utf-8")
    input_path_2.write_text("{}", encoding="utf-8")
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "valuation_replay_manifest_v1",
                "cases": [
                    {"case_id": "CASE_1", "input_path": "case-1.json"},
                    {"case_id": "CASE_2", "input_path": "case-2.json"},
                ],
            }
        ),
        encoding="utf-8",
    )
    report_path = tmp_path / "report.json"
    payloads = [
        {
            "ticker": "AAPL",
            "intrinsic_delta": 10.0,
            "replayed_terminal_growth_fallback_mode": "default_only",
            "replayed_terminal_growth_anchor_source": "default",
            "replayed_forward_signal": {
                "calibration_applied": False,
                "mapping_version": "forward_signal_calibration_v1",
                "growth_adjustment_basis_points": 0.0,
                "margin_adjustment_basis_points": 0.0,
                "raw_growth_adjustment_basis_points": 0.0,
                "raw_margin_adjustment_basis_points": 0.0,
                "calibration_degraded_reason": None,
            },
            "xbrl_diagnostics": {
                "arelle_runtime": {
                    "parse_latency_ms_avg": 100.0,
                    "runtime_lock_wait_ms_avg": 2.0,
                    "isolation_modes": ["serial"],
                }
            },
        },
        {
            "ticker": "NVDA",
            "intrinsic_delta": -30.0,
            "replayed_terminal_growth_fallback_mode": "default_only",
            "replayed_terminal_growth_anchor_source": "default",
            "replayed_forward_signal": {
                "calibration_applied": False,
                "mapping_version": "forward_signal_calibration_v1",
                "growth_adjustment_basis_points": 0.0,
                "margin_adjustment_basis_points": 0.0,
                "raw_growth_adjustment_basis_points": 0.0,
                "raw_margin_adjustment_basis_points": 0.0,
                "calibration_degraded_reason": None,
            },
            "xbrl_diagnostics": {
                "arelle_runtime": {
                    "parse_latency_ms_avg": 200.0,
                    "runtime_lock_wait_ms_avg": 6.0,
                    "isolation_modes": ["serial"],
                }
            },
        },
    ]

    def _fake_run_replay_case(**_: object) -> tuple[int, dict[str, object]]:
        if not payloads:
            raise RuntimeError("unexpected replay invocation count")
        return 0, payloads.pop(0)

    monkeypatch.setattr(module, "_run_replay_case", _fake_run_replay_case)
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
    assert exit_code == 0

    report = json.loads(report_path.read_text(encoding="utf-8"))
    summary = report.get("summary")
    assert isinstance(summary, dict)
    assert summary.get("arelle_parse_latency_available_cases") == 2
    assert summary.get("arelle_parse_latency_p90_ms") == pytest.approx(190.0)
    assert summary.get("arelle_runtime_lock_wait_available_cases") == 2
    assert summary.get("arelle_runtime_lock_wait_p90_ms") == pytest.approx(5.6)
    assert summary.get("arelle_runtime_isolation_mode_counts") == {"serial": 2}


def test_run_replay_checks_uses_baseline_arelle_runtime_hints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script_module()
    project_root = Path(__file__).resolve().parents[1]
    fixture_path = (
        project_root
        / "tests"
        / "fixtures"
        / "fundamental_replay_inputs"
        / "aapl.replay.json"
    )
    replay_input = json.loads(fixture_path.read_text(encoding="utf-8"))
    replay_input["baseline"] = {
        "diagnostics": {
            "arelle_runtime": {
                "parse_latency_ms_avg": 321.0,
                "runtime_lock_wait_ms_avg": 8.0,
                "isolation_modes": ["serial"],
            }
        }
    }

    input_path = tmp_path / "case.json"
    input_path.write_text(
        json.dumps(replay_input, ensure_ascii=False),
        encoding="utf-8",
    )
    manifest_path = tmp_path / "manifest.json"
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
            0,
            {
                "ticker": "AAPL",
                "intrinsic_delta": 0.0,
                "replayed_terminal_growth_fallback_mode": "default_only",
                "replayed_terminal_growth_anchor_source": "default",
                "replayed_forward_signal": {
                    "calibration_applied": False,
                    "mapping_version": "forward_signal_calibration_v1",
                    "growth_adjustment_basis_points": 0.0,
                    "margin_adjustment_basis_points": 0.0,
                    "raw_growth_adjustment_basis_points": 0.0,
                    "raw_margin_adjustment_basis_points": 0.0,
                    "calibration_degraded_reason": None,
                },
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
    assert exit_code == 0

    report = json.loads(report_path.read_text(encoding="utf-8"))
    summary = report.get("summary")
    assert isinstance(summary, dict)
    assert summary.get("arelle_parse_latency_available_cases") == 1
    assert summary.get("arelle_parse_latency_p90_ms") == pytest.approx(321.0)
    assert summary.get("arelle_runtime_lock_wait_p90_ms") == pytest.approx(8.0)
    assert summary.get("arelle_runtime_isolation_mode_counts") == {"serial": 1}


def test_run_replay_checks_emits_validation_rule_drift_summary(
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

    monkeypatch.setenv("FUNDAMENTAL_XBRL_ARELLE_VALIDATION_MODE", "efm_validate")
    monkeypatch.setenv("FUNDAMENTAL_XBRL_ARELLE_DISCLOSURE_SYSTEM", "efm")
    monkeypatch.setenv("FUNDAMENTAL_XBRL_ARELLE_PLUGINS", "validate/EFM")
    monkeypatch.setenv(
        "FUNDAMENTAL_XBRL_EXPECTED_RULE_SIGNATURE",
        "mismatch-signature",
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
                "replayed_forward_signal": {
                    "calibration_applied": False,
                    "mapping_version": "forward_signal_calibration_v1",
                    "growth_adjustment_basis_points": 0.0,
                    "margin_adjustment_basis_points": 0.0,
                    "raw_growth_adjustment_basis_points": 0.0,
                    "raw_margin_adjustment_basis_points": 0.0,
                    "calibration_degraded_reason": None,
                },
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
    assert exit_code == 0

    report = json.loads(report_path.read_text(encoding="utf-8"))
    summary = report.get("summary")
    assert isinstance(summary, dict)
    assert summary.get("validation_block_rate") == pytest.approx(0.0)
    assert summary.get("validation_rule_drift_count") == 1
    assert summary.get("validation_rule_drift_detected") is True
    assert (
        summary.get("validation_rule_drift_error_code")
        == "validation_rule_version_drift"
    )
    assert isinstance(summary.get("validation_rule_actual_signature"), str)
    assert summary.get("validation_rule_expected_signature") == "mismatch-signature"


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
    assert summary.get("trace_contract_passed_cases") == 0
    assert summary.get("trace_contract_pass_rate") == 0.0
    assert summary.get("error_code_counts") == {"terminal_growth_path_missing": 1}


def test_run_replay_checks_skips_terminal_growth_path_validation_for_bank_model(
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
            0,
            {
                "ticker": "JPM",
                "model_type": "bank",
                "intrinsic_delta": 0.0,
                "replayed_forward_signal": {
                    "calibration_applied": False,
                    "mapping_version": "forward_signal_calibration_v1",
                    "growth_adjustment_basis_points": 0.0,
                    "margin_adjustment_basis_points": 0.0,
                    "raw_growth_adjustment_basis_points": 0.0,
                    "raw_margin_adjustment_basis_points": 0.0,
                    "calibration_degraded_reason": None,
                },
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
    assert exit_code == 0

    report = json.loads(report_path.read_text(encoding="utf-8"))
    summary = report.get("summary")
    assert isinstance(summary, dict)
    assert summary.get("failed_cases") == 0
    assert summary.get("trace_contract_passed_cases") == 1
    assert summary.get("trace_contract_pass_rate") == 1.0


def test_run_replay_checks_fails_when_forward_signal_trace_fields_missing(
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
            0,
            {
                "ticker": "AAPL",
                "intrinsic_delta": 0.0,
                "replayed_terminal_growth_fallback_mode": "default_only",
                "replayed_terminal_growth_anchor_source": "default",
                "replayed_forward_signal": {
                    "calibration_applied": False,
                    "mapping_version": "",
                    "growth_adjustment_basis_points": 0.0,
                    "margin_adjustment_basis_points": 0.0,
                    "raw_growth_adjustment_basis_points": 0.0,
                    "raw_margin_adjustment_basis_points": 0.0,
                },
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
    assert summary.get("trace_contract_passed_cases") == 0
    assert summary.get("trace_contract_pass_rate") == 0.0
    assert summary.get("error_code_counts") == {"forward_signal_trace_missing": 1}
