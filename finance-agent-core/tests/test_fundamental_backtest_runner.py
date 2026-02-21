from __future__ import annotations

import json
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


def test_load_cases_reads_fixture_dataset() -> None:
    fixture_path = (
        Path(__file__).resolve().parent / "fixtures" / "fundamental_backtest_cases.json"
    )
    cases = load_cases(fixture_path)
    assert len(cases) >= 3
    assert all(case.case_id for case in cases)


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
