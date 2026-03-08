from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
from pathlib import Path

import pytest


def _load_script_module():
    project_root = Path(__file__).resolve().parents[1]
    script_path = project_root / "scripts" / "replay_fundamental_valuation.py"
    spec = importlib.util.spec_from_file_location(
        "replay_fundamental_valuation", script_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load replay_fundamental_valuation.py module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_fixture_input() -> dict[str, object]:
    project_root = Path(__file__).resolve().parents[1]
    fixture_path = (
        project_root
        / "tests"
        / "fixtures"
        / "fundamental_replay_inputs"
        / "aapl.replay.json"
    )
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("fixture payload must be object")
    return payload


def test_load_replay_input_uses_machine_readable_error_code_for_missing_path() -> None:
    module = _load_script_module()
    missing_path = Path("/tmp/replay-missing-input.json")
    if missing_path.exists():
        missing_path.unlink()

    with pytest.raises(module.ReplayContractError) as exc_info:
        module._load_replay_input(missing_path)

    assert (
        exc_info.value.error_code
        == module.ReplayErrorCode.REPLAY_INPUT_FILE_NOT_FOUND.value
    )


def test_load_replay_input_uses_machine_readable_error_code_for_invalid_schema(
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    invalid_path = tmp_path / "invalid_replay_input.json"
    invalid_path.write_text(
        json.dumps({"schema_version": "valuation_replay_input_v2", "ticker": "AAPL"}),
        encoding="utf-8",
    )

    with pytest.raises(module.ReplayContractError) as exc_info:
        module._load_replay_input(invalid_path)

    assert (
        exc_info.value.error_code
        == module.ReplayErrorCode.INVALID_REPLAY_INPUT_SCHEMA.value
    )


def test_extract_guardrail_from_assumptions_parses_growth_payload() -> None:
    module = _load_script_module()
    assumptions = [
        (
            "base_growth_guardrail applied "
            "(version=base_assumption_guardrail_v1, profile=dcf_growth, "
            "raw_year1=0.668000, raw_yearN=0.014000, "
            "guarded_year1=0.500000, guarded_yearN=0.014000, "
            "reasons=year1_growth_cap|terminal_bound)"
        )
    ]

    parsed = module._extract_guardrail_from_assumptions(assumptions, kind="growth")
    assert parsed is not None
    assert parsed["version"] == "base_assumption_guardrail_v1"
    assert parsed["profile"] == "dcf_growth"
    assert parsed["raw_year1"] == 0.668
    assert parsed["guarded_year1"] == 0.5
    assert parsed["reasons"] == ["year1_growth_cap", "terminal_bound"]


def test_extract_reinvestment_guardrail_from_assumptions_parses_capex_payload() -> None:
    module = _load_script_module()
    assumptions = [
        (
            "base_reinvestment_guardrail applied "
            "(version=base_assumption_guardrail_v1, profile=dcf_growth, "
            "metric=capex_rates, raw_year1=0.420000, raw_yearN=0.420000, "
            "guarded_year1=0.320000, guarded_yearN=0.160000, "
            "anchor=0.225000, anchor_samples=2, "
            "reasons=capex_series_clamped_to_bounds|capex_terminal_converged_to_historical_anchor)"
        )
    ]

    parsed = module._extract_reinvestment_guardrail_from_assumptions(
        assumptions,
        metric="capex_rates",
    )
    assert parsed is not None
    assert parsed["profile"] == "dcf_growth"
    assert parsed["metric"] == "capex_rates"
    assert parsed["raw_year1"] == pytest.approx(0.42)
    assert parsed["guarded_yearN"] == pytest.approx(0.16)
    assert parsed["anchor"] == pytest.approx(0.225)
    assert parsed["anchor_samples"] == 2


def test_build_report_includes_parameter_drift_summaries() -> None:
    module = _load_script_module()

    replay_input_raw = _load_fixture_input()
    replay_input_raw["baseline"] = {
        "params_dump": {
            "wacc": 0.12,
            "terminal_growth": 0.014,
            "growth_rates": [0.50, 0.40, 0.014],
            "operating_margins": [0.59, 0.59, 0.59],
            "capex_rates": [0.20, 0.19, 0.18],
            "wc_rates": [0.05, 0.04, 0.03],
        },
        "calculation_metrics": {"intrinsic_value": 280.0},
        "assumptions": ["baseline assumption"],
        "build_metadata": {
            "forward_signal": {
                "growth_adjustment_basis_points": -80.0,
                "margin_adjustment_basis_points": -90.0,
                "raw_growth_adjustment_basis_points": -120.0,
                "raw_margin_adjustment_basis_points": -150.0,
                "calibration_applied": True,
                "mapping_version": "v1",
            }
        },
        "diagnostics": {"growth_consensus_window_years": 3},
    }
    replay_input = module.parse_valuation_replay_input_model(
        replay_input_raw,
        context="test.replay_input",
    )

    replay_params = {
        "wacc": 0.12,
        "terminal_growth": 0.014,
        "growth_rates": [0.45, 0.35, 0.014],
        "operating_margins": [0.57, 0.57, 0.57],
        "capex_rates": [0.16, 0.15, 0.14],
        "wc_rates": [0.03, 0.025, 0.02],
    }
    replay_metrics = {"intrinsic_value": 250.0}
    replay_assumptions = [
        (
            "consensus_growth_rate decayed into near-term DCF growth path "
            "(horizon=short_term, window_years=4, weights=1.00|0.75|0.50|0.25)"
        ),
        (
            "base_reinvestment_guardrail applied "
            "(version=base_assumption_guardrail_v1, profile=dcf_growth, "
            "metric=capex_rates, raw_year1=0.200000, raw_yearN=0.180000, "
            "guarded_year1=0.160000, guarded_yearN=0.140000, "
            "anchor=0.170000, anchor_samples=3, reasons=capex_series_clamped_to_bounds)"
        ),
        (
            "base_reinvestment_guardrail applied "
            "(version=base_assumption_guardrail_v1, profile=dcf_growth, "
            "metric=wc_rates, raw_year1=0.050000, raw_yearN=0.030000, "
            "guarded_year1=0.030000, guarded_yearN=0.020000, "
            "anchor=0.020000, anchor_samples=3, reasons=wc_terminal_converged_to_historical_anchor)"
        ),
    ]
    replay_metadata = {
        "forward_signal": {
            "growth_adjustment_basis_points": -90.0,
            "margin_adjustment_basis_points": -95.0,
            "raw_growth_adjustment_basis_points": -130.0,
            "raw_margin_adjustment_basis_points": -155.0,
            "calibration_applied": True,
            "mapping_version": "v1",
        }
    }

    report = module._build_report(
        replay_input=replay_input,
        replay_params_dump=replay_params,
        replay_calculation_metrics=replay_metrics,
        replay_assumptions=replay_assumptions,
        replay_metadata=replay_metadata,
        override_payload={"market_snapshot": {"long_run_growth_anchor": 0.02}},
        abs_tol=1e-6,
        rel_tol=1e-4,
    )

    assert report["intrinsic_delta"] == -30.0
    assert report["growth_year1_delta"] == pytest.approx(-0.05)
    assert report["margin_year1_delta"] == pytest.approx(-0.02)
    assert report["capex_year1_delta"] == pytest.approx(-0.04)
    assert report["wc_year1_delta"] == pytest.approx(-0.02)
    assert report["forward_signal_growth_bp_delta"] == -10.0
    assert report["forward_signal_margin_bp_delta"] == -5.0
    assert report["replayed_capex_guardrail"]["applied"] is True
    assert report["replayed_wc_guardrail"]["applied"] is True
    assert report["baseline_forward_signal"]["calibration_applied"] is True
    assert report["replayed_forward_signal"]["mapping_version"] == "v1"
    assert report["baseline_growth_consensus_window_years"] == 3
    assert report["replayed_growth_consensus_window_years"] == 4
    assert report["override_applied"] is True
    assert report["override_keys"] == ["market_snapshot"]
    assert report["replay_staleness_mode"] == "snapshot"
    assert report["baseline_terminal_growth_fallback_mode"] is None
    assert report["replayed_terminal_growth_fallback_mode"] is None
    assert report["baseline_terminal_growth_anchor_source"] is None
    assert report["replayed_terminal_growth_anchor_source"] is None


def test_extract_forward_signal_bp_does_not_fallback_to_legacy_calibration_block() -> (
    None
):
    module = _load_script_module()
    metadata = {
        "forward_signal": {
            "growth_adjustment_basis_points": -80.0,
            "margin_adjustment_basis_points": -90.0,
            "raw_growth_adjustment_basis_points": -120.0,
            "raw_margin_adjustment_basis_points": -150.0,
        },
        "forward_signal_calibration": {
            "calibration_applied": True,
            "mapping_version": "legacy-v0",
        },
    }

    with pytest.raises(ValueError, match="legacy payload is not supported"):
        module._extract_forward_signal_bp(metadata)


def test_main_emits_machine_readable_error_code_for_contract_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load_script_module()

    async def _fake_run() -> int:
        raise module.ReplayContractError(
            "forward_signal.mapping_version missing or invalid; legacy payload is not supported",
            error_code="legacy_payload_not_supported",
        )

    monkeypatch.setattr(module, "_run", _fake_run)
    exit_code = module.main()
    captured = capsys.readouterr()

    assert exit_code == 1
    assert '"error_code": "legacy_payload_not_supported"' in captured.out


def test_main_emits_runtime_error_code_for_unhandled_exception(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load_script_module()

    async def _fake_run() -> int:
        raise RuntimeError("boom")

    monkeypatch.setattr(module, "_run", _fake_run)
    exit_code = module.main()
    captured = capsys.readouterr()

    assert exit_code == 1
    assert '"error_code": "replay_runtime_error"' in captured.out


def test_run_reads_input_path_argument(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_script_module()
    replay_input_path = tmp_path / "input.json"
    replay_input_path.write_text(json.dumps(_load_fixture_input()), encoding="utf-8")

    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: argparse.Namespace(
            input=replay_input_path,
            override_json=None,
            abs_tol=1e-6,
            rel_tol=1e-4,
            report=None,
        ),
    )

    exit_code = asyncio.run(module._run())
    assert exit_code == 0


def test_effective_override_payload_merges_contract_and_cli_override() -> None:
    module = _load_script_module()
    replay_input_raw = _load_fixture_input()
    replay_input_raw["override"] = {
        "market_snapshot": {"long_run_growth_anchor": 0.02, "market_stale_max_days": 5}
    }
    replay_input = module.parse_valuation_replay_input_model(
        replay_input_raw,
        context="test.replay_input",
    )
    payload = module._effective_override_payload(
        replay_input,
        cli_override={"market_snapshot": {"market_stale_max_days": 7}},
    )
    assert payload == {
        "market_snapshot": {"long_run_growth_anchor": 0.02, "market_stale_max_days": 7}
    }


def test_recompute_market_staleness_updates_datum_staleness() -> None:
    module = _load_script_module()
    snapshot = {
        "as_of": "2026-03-08T00:00:00Z",
        "market_stale_max_days": 5,
        "market_datums": {
            "shares_outstanding": {
                "value": 100.0,
                "as_of": "2026-02-20T00:00:00Z",
                "update_cadence_days": 1,
                "quality_flags": [],
            }
        },
    }
    recomputed = module._recompute_market_staleness(snapshot)
    assert isinstance(recomputed, dict)
    datum = recomputed["market_datums"]["shares_outstanding"]
    assert datum["staleness"]["is_stale"] is True
    assert "stale" in datum["quality_flags"]
    assert recomputed["shares_outstanding_is_stale"] is True


def test_build_report_includes_terminal_growth_path_fields() -> None:
    module = _load_script_module()
    replay_input_raw = _load_fixture_input()
    replay_input_raw["baseline"] = {
        "params_dump": {"terminal_growth": 0.02},
        "calculation_metrics": {"intrinsic_value": 100.0},
        "assumptions": [],
        "build_metadata": {
            "data_freshness": {
                "terminal_growth_path": {
                    "terminal_growth_fallback_mode": "default_only",
                    "terminal_growth_anchor_source": "default",
                }
            },
            "forward_signal": {
                "growth_adjustment_basis_points": -10.0,
                "margin_adjustment_basis_points": -12.0,
                "raw_growth_adjustment_basis_points": -10.0,
                "raw_margin_adjustment_basis_points": -12.0,
                "calibration_applied": True,
                "mapping_version": "v1",
            },
        },
    }
    replay_input = module.parse_valuation_replay_input_model(
        replay_input_raw,
        context="test.replay_input",
    )
    report = module._build_report(
        replay_input=replay_input,
        replay_params_dump={"terminal_growth": 0.03},
        replay_calculation_metrics={"intrinsic_value": 105.0},
        replay_assumptions=[
            "unrelated assumption",
        ],
        replay_metadata={
            "data_freshness": {
                "terminal_growth_path": {
                    "terminal_growth_fallback_mode": "filing_first_then_default",
                    "terminal_growth_anchor_source": "filing",
                }
            },
            "forward_signal": {
                "growth_adjustment_basis_points": -10.0,
                "margin_adjustment_basis_points": -12.0,
                "raw_growth_adjustment_basis_points": -10.0,
                "raw_margin_adjustment_basis_points": -12.0,
                "calibration_applied": True,
                "mapping_version": "v1",
            },
        },
        override_payload={},
        abs_tol=1e-6,
        rel_tol=1e-4,
    )
    assert report["baseline_terminal_growth_fallback_mode"] == "default_only"
    assert report["replayed_terminal_growth_fallback_mode"] == (
        "filing_first_then_default"
    )
    assert report["baseline_terminal_growth_anchor_source"] == "default"
    assert report["replayed_terminal_growth_anchor_source"] == "filing"


def test_build_report_includes_shares_path_fields_from_metadata() -> None:
    module = _load_script_module()
    replay_input_raw = _load_fixture_input()
    replay_input_raw["baseline"] = {
        "params_dump": {"shares_outstanding": 1000.0},
        "calculation_metrics": {"intrinsic_value": 100.0},
        "assumptions": [],
        "build_metadata": {
            "data_freshness": {
                "shares_path": {
                    "selected_source": "filing_conservative_dilution",
                    "shares_scope": "filing_consolidated",
                    "equity_value_scope": "mixed_price_filing_shares",
                    "scope_mismatch_detected": True,
                    "scope_mismatch_ratio": 0.5,
                }
            },
            "forward_signal": {
                "growth_adjustment_basis_points": -10.0,
                "margin_adjustment_basis_points": -12.0,
                "raw_growth_adjustment_basis_points": -10.0,
                "raw_margin_adjustment_basis_points": -12.0,
                "calibration_applied": True,
                "mapping_version": "v1",
            },
        },
    }
    replay_input = module.parse_valuation_replay_input_model(
        replay_input_raw,
        context="test.replay_input",
    )
    report = module._build_report(
        replay_input=replay_input,
        replay_params_dump={"shares_outstanding": 900.0},
        replay_calculation_metrics={"intrinsic_value": 105.0},
        replay_assumptions=[],
        replay_metadata={
            "data_freshness": {
                "shares_path": {
                    "selected_source": "market_data",
                    "shares_scope": "market_class",
                    "equity_value_scope": "market_class",
                    "scope_mismatch_detected": False,
                    "scope_mismatch_ratio": 0.0,
                }
            },
            "forward_signal": {
                "growth_adjustment_basis_points": -10.0,
                "margin_adjustment_basis_points": -12.0,
                "raw_growth_adjustment_basis_points": -10.0,
                "raw_margin_adjustment_basis_points": -12.0,
                "calibration_applied": True,
                "mapping_version": "v1",
            },
        },
        override_payload={},
        abs_tol=1e-6,
        rel_tol=1e-4,
    )

    baseline_shares_path = report["baseline_shares_path"]
    replayed_shares_path = report["replayed_shares_path"]
    assert isinstance(baseline_shares_path, dict)
    assert isinstance(replayed_shares_path, dict)
    assert baseline_shares_path["shares_scope"] == "filing_consolidated"
    assert baseline_shares_path["scope_mismatch_detected"] is True
    assert replayed_shares_path["shares_scope"] == "market_class"
    assert replayed_shares_path["scope_mismatch_detected"] is False
