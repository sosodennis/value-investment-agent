from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.agents.technical.subdomains.verification import (
    BacktestResult,
    VerificationRuntimeRequest,
    VerificationRuntimeService,
)


@dataclass
class _FakeBacktester:
    results: dict[str, BacktestResult]

    def run(self, transaction_cost: float = 0.0005) -> dict[str, BacktestResult]:
        _ = transaction_cost
        return self.results


@dataclass
class _FakeWfaOptimizer:
    result: dict[str, object] | None

    def run(
        self, train_window: int = 252, test_window: int = 63
    ) -> dict[str, object] | None:
        _ = (train_window, test_window)
        return self.result


def test_verification_runtime_service_computes_summary_and_gates() -> None:
    dates = pd.date_range("2024-01-01", periods=5, freq="B")
    daily_returns = pd.Series([0.001, 0.0008, 0.0012, 0.0009, 0.0011], index=dates)

    results = {
        "trend": BacktestResult(
            strategy_name="trend",
            strategy_description="trend strategy",
            total_return=0.25,
            win_rate=0.6,
            max_drawdown=-0.12,
            sharpe_ratio=1.3,
            total_trades=30,
            profit_factor=1.8,
            daily_returns=daily_returns,
        ),
        "mean_revert": BacktestResult(
            strategy_name="mean_revert",
            strategy_description="mean revert strategy",
            total_return=0.15,
            win_rate=0.55,
            max_drawdown=-0.15,
            sharpe_ratio=0.9,
            total_trades=20,
            profit_factor=1.4,
            daily_returns=daily_returns,
        ),
    }

    wfa_result = {
        "wfa_sharpe": 0.8,
        "wfa_total_return": 0.1,
        "wfa_max_drawdown": -0.1,
        "wfa_equity_curve": pd.Series([1.0, 1.01, 1.02], index=dates[:3]),
        "selection_log": [
            {"date": "2024-01-05", "selected": "trend", "train_sharpe": 1.2},
            {"date": "2024-02-05", "selected": "trend", "train_sharpe": 1.1},
            {"date": "2024-03-05", "selected": "trend", "train_sharpe": 1.0},
        ],
        "full_backtest_results": results,
    }

    def _backtester_factory(**_kwargs):
        return _FakeBacktester(results=results)

    def _wfa_factory(_backtester):
        _ = _backtester
        return _FakeWfaOptimizer(result=wfa_result)

    series = pd.Series([1.0, 1.1, 1.2], index=dates[:3])

    request = VerificationRuntimeRequest(
        ticker="AAPL",
        as_of="2026-03-12T00:00:00",
        price_series=series,
        z_score_series=series,
        stat_strength_dict={"value": 50.0, "series_value": series},
        obv_dict={
            "raw_obv_val": 1.0,
            "fd_obv_z": 0.2,
            "optimal_d": 0.4,
            "state": "NEUTRAL",
            "series_z": series,
        },
        bollinger_dict={
            "upper": 1.2,
            "middle": 1.1,
            "lower": 1.0,
            "state": "INSIDE",
            "bandwidth": 0.2,
            "series_upper": series,
            "series_lower": series,
        },
    )

    runtime = VerificationRuntimeService(
        backtester_factory=_backtester_factory,
        wfa_optimizer_factory=_wfa_factory,
    )

    result = runtime.compute(request)

    assert result.backtest_summary is not None
    assert result.backtest_summary.strategy_name == "trend"
    assert result.wfa_summary is not None
    assert result.baseline_gates.status == "pass"
    assert result.degraded_reasons == []
