from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from src.agents.fundamental.domain.valuation.backtest import (
    BacktestCase,
    BacktestConfig,
    build_baseline_payload,
    compare_with_baseline,
    load_baseline,
    load_cases,
    run_cases,
)


def _write_deterministic_monitoring_fixture(tmp_path: Path) -> tuple[Path, Path]:
    dataset_path = tmp_path / "monitoring_dataset.json"
    baseline_path = tmp_path / "monitoring_baseline.json"
    dataset_path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "bank_override_monitoring",
                        "model": "bank",
                        "required_metrics": ["equity_value", "cost_of_equity"],
                        "params": {
                            "ticker": "BNK",
                            "rationale": "monitoring gate fixture",
                            "initial_net_income": 100.0,
                            "income_growth_rates": [0.05, 0.05, 0.05],
                            "rwa_intensity": 0.05,
                            "tier1_target_ratio": 0.12,
                            "initial_capital": 200.0,
                            "risk_free_rate": 0.04,
                            "beta": 1.1,
                            "market_risk_premium": 0.05,
                            "cost_of_equity_strategy": "override",
                            "cost_of_equity_override": 0.2,
                            "terminal_growth": 0.02,
                            "shares_outstanding": 100.0,
                        },
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return dataset_path, baseline_path


def test_load_cases_reads_fixture_dataset() -> None:
    fixture_path = (
        Path(__file__).resolve().parent / "fixtures" / "fundamental_backtest_cases.json"
    )
    cases = load_cases(fixture_path)
    assert len(cases) >= 3
    assert all(case.case_id for case in cases)


def test_fixture_dataset_matches_fixture_baseline() -> None:
    fixture_dir = Path(__file__).resolve().parent / "fixtures"
    dataset_path = fixture_dir / "fundamental_backtest_cases.json"
    baseline_path = fixture_dir / "fundamental_backtest_baseline.json"

    cases = load_cases(dataset_path)
    baseline = load_baseline(baseline_path)
    results = run_cases(cases)

    drifts, issues = compare_with_baseline(
        results,
        baseline,
        config=BacktestConfig(abs_tol=1e-6, rel_tol=1e-4),
    )
    assert drifts == []
    assert issues == []


def test_compare_with_baseline_has_no_drift_for_identical_payload(
    tmp_path: Path,
) -> None:
    cases = [
        BacktestCase(
            case_id="bank_override",
            model="bank",
            params={
                "ticker": "BNK",
                "rationale": "test",
                "initial_net_income": 100.0,
                "income_growth_rates": [0.05, 0.05, 0.05],
                "rwa_intensity": 0.05,
                "tier1_target_ratio": 0.12,
                "initial_capital": 200.0,
                "risk_free_rate": 0.04,
                "beta": 1.1,
                "market_risk_premium": 0.05,
                "cost_of_equity_strategy": "override",
                "cost_of_equity_override": 0.2,
                "terminal_growth": 0.02,
                "shares_outstanding": 100.0,
            },
            required_metrics=("equity_value", "cost_of_equity"),
        ),
        BacktestCase(
            case_id="reit_det",
            model="reit_ffo",
            params={
                "ticker": "REIT",
                "rationale": "test",
                "ffo": 100.0,
                "ffo_multiple": 10.0,
                "depreciation_and_amortization": 20.0,
                "maintenance_capex_ratio": 0.8,
                "cash": 10.0,
                "total_debt": 50.0,
                "preferred_stock": 0.0,
                "shares_outstanding": 10.0,
            },
            required_metrics=("intrinsic_value", "equity_value"),
        ),
    ]
    results = run_cases(cases)
    assert all(item.status == "ok" for item in results)

    baseline_payload = build_baseline_payload(results)
    baseline_cases = {}
    for case_id, raw in baseline_payload["cases"].items():
        assert isinstance(case_id, str)
        assert isinstance(raw, dict)
        model = raw.get("model")
        metrics = raw.get("metrics")
        assert isinstance(model, str)
        assert isinstance(metrics, dict)
        baseline_cases[case_id] = {"model": model, "metrics": metrics}

    baseline_path = tmp_path / "baseline_temp.json"
    baseline_path.write_text(json.dumps({"cases": baseline_cases}), encoding="utf-8")
    parsed_baseline = load_baseline(baseline_path)

    drifts, issues = compare_with_baseline(
        results,
        parsed_baseline,
        config=BacktestConfig(abs_tol=1e-9, rel_tol=1e-9),
    )
    assert drifts == []
    assert issues == []


def test_compare_with_baseline_detects_drift(tmp_path: Path) -> None:
    cases = [
        BacktestCase(
            case_id="bank_override",
            model="bank",
            params={
                "ticker": "BNK",
                "rationale": "test",
                "initial_net_income": 100.0,
                "income_growth_rates": [0.05, 0.05, 0.05],
                "rwa_intensity": 0.05,
                "tier1_target_ratio": 0.12,
                "initial_capital": 200.0,
                "risk_free_rate": 0.04,
                "beta": 1.1,
                "market_risk_premium": 0.05,
                "cost_of_equity_strategy": "override",
                "cost_of_equity_override": 0.2,
                "terminal_growth": 0.02,
                "shares_outstanding": 100.0,
            },
            required_metrics=("cost_of_equity",),
        )
    ]
    results = run_cases(cases)
    assert len(results) == 1
    assert results[0].status == "ok"
    assert results[0].metrics is not None

    drifted_baseline = {
        "bank_override": {
            "model": "bank",
            "metrics": {
                "cost_of_equity": 0.15,
            },
        }
    }
    baseline_path = tmp_path / "baseline_temp_drift.json"
    baseline_path.write_text(json.dumps({"cases": drifted_baseline}), encoding="utf-8")
    parsed_baseline = load_baseline(baseline_path)

    drifts, issues = compare_with_baseline(
        results,
        parsed_baseline,
        config=BacktestConfig(abs_tol=1e-6, rel_tol=1e-6),
    )
    assert issues == []
    assert len(drifts) == 1
    assert drifts[0].metric_path == "cost_of_equity"


def test_backtest_runner_blocks_on_degraded_calibration_mapping(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = project_root / "scripts" / "run_fundamental_backtest.py"
    dataset_path = (
        project_root / "tests" / "fixtures" / "fundamental_backtest_cases.json"
    )
    baseline_path = (
        project_root / "tests" / "fixtures" / "fundamental_backtest_baseline.json"
    )
    report_path = tmp_path / "backtest_report.json"

    env = os.environ.copy()
    env["FUNDAMENTAL_FORWARD_SIGNAL_CALIBRATION_MAPPING_PATH"] = str(
        tmp_path / "missing_mapping.json"
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--dataset",
            str(dataset_path),
            "--baseline",
            str(baseline_path),
            "--report",
            str(report_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert completed.returncode == 3
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    summary = payload.get("summary")
    assert isinstance(summary, dict)
    assert summary.get("calibration_gate_passed") is False
    calibration = payload.get("calibration")
    assert isinstance(calibration, dict)
    assert calibration.get("mapping_artifact_name") == "missing_mapping.json"
    issues = payload.get("issues")
    assert isinstance(issues, list)
    assert issues
    assert any(
        isinstance(item, str) and item.startswith("calibration_mapping_degraded:")
        for item in issues
    )


def test_backtest_runner_blocks_on_monitoring_gate_breach(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = project_root / "scripts" / "run_fundamental_backtest.py"
    dataset_path, baseline_path = _write_deterministic_monitoring_fixture(tmp_path)
    report_path = tmp_path / "backtest_report_monitoring_gate.json"

    build_baseline = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--dataset",
            str(dataset_path),
            "--baseline",
            str(baseline_path),
            "--report",
            str(tmp_path / "backtest_report_baseline_build.json"),
            "--update-baseline",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert build_baseline.returncode == 0

    completed = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--dataset",
            str(dataset_path),
            "--baseline",
            str(baseline_path),
            "--report",
            str(report_path),
            "--max-extreme-upside-rate",
            "-0.1",
            "--min-consensus-gap-count",
            "0",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 4
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    summary = payload.get("summary")
    assert isinstance(summary, dict)
    assert summary.get("issue_count") == 1
    issues = payload.get("issues")
    assert isinstance(issues, list)
    assert any(
        isinstance(item, str)
        and item.startswith("monitoring_gate_failed:extreme_upside_rate=")
        for item in issues
    )


def test_backtest_runner_blocks_on_shares_scope_mismatch_gate_breach(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = project_root / "scripts" / "run_fundamental_backtest.py"
    dataset_path, baseline_path = _write_deterministic_monitoring_fixture(tmp_path)
    report_path = tmp_path / "backtest_report_shares_scope_gate.json"

    build_baseline = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--dataset",
            str(dataset_path),
            "--baseline",
            str(baseline_path),
            "--report",
            str(tmp_path / "backtest_report_shares_scope_baseline_build.json"),
            "--update-baseline",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert build_baseline.returncode == 0

    completed = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--dataset",
            str(dataset_path),
            "--baseline",
            str(baseline_path),
            "--report",
            str(report_path),
            "--max-shares-scope-mismatch-rate",
            "-0.1",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 4
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    issues = payload.get("issues")
    assert isinstance(issues, list)
    assert any(
        isinstance(item, str)
        and item.startswith("monitoring_gate_failed:shares_scope_mismatch_rate=")
        for item in issues
    )


def test_backtest_runner_blocks_on_reinvestment_guardrail_gate_breach(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = project_root / "scripts" / "run_fundamental_backtest.py"
    dataset_path, baseline_path = _write_deterministic_monitoring_fixture(tmp_path)
    report_path = tmp_path / "backtest_report_reinvestment_gate.json"

    build_baseline = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--dataset",
            str(dataset_path),
            "--baseline",
            str(baseline_path),
            "--report",
            str(tmp_path / "backtest_report_reinvestment_baseline_build.json"),
            "--update-baseline",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert build_baseline.returncode == 0

    completed = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--dataset",
            str(dataset_path),
            "--baseline",
            str(baseline_path),
            "--report",
            str(report_path),
            "--min-reinvestment-guardrail-hit-rate",
            "1.1",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 4
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    issues = payload.get("issues")
    assert isinstance(issues, list)
    assert any(
        isinstance(item, str)
        and item.startswith("monitoring_gate_failed:reinvestment_guardrail_hit_rate=")
        for item in issues
    )
