from __future__ import annotations

from .contracts import (
    BacktestCase,
    BacktestConfig,
    BaselineCase,
    CaseResult,
    MetricDrift,
)
from .drift_service import compare_backtest_results_with_baseline
from .io_service import load_backtest_baseline, load_backtest_cases
from .report_service import (
    build_backtest_baseline_payload,
    build_backtest_report_payload,
)
from .runtime_service import run_backtest_cases

load_cases = load_backtest_cases
load_baseline = load_backtest_baseline
run_cases = run_backtest_cases
compare_with_baseline = compare_backtest_results_with_baseline
build_baseline_payload = build_backtest_baseline_payload
build_report_payload = build_backtest_report_payload

__all__ = [
    "BacktestCase",
    "BacktestConfig",
    "BaselineCase",
    "CaseResult",
    "MetricDrift",
    "build_baseline_payload",
    "build_report_payload",
    "compare_with_baseline",
    "load_baseline",
    "load_cases",
    "run_cases",
]
