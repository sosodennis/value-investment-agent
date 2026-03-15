from __future__ import annotations

import statistics
import time
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.agents.technical.subdomains.verification import (
    BacktestResult,
    WalkForwardOptimizer,
)


@dataclass
class _FakeCombinedBacktester:
    prices: pd.Series
    daily_rf: pd.Series
    _results: dict[str, BacktestResult]

    def run(self) -> dict[str, BacktestResult]:
        return self._results


def _build_fixed_backtester() -> _FakeCombinedBacktester:
    dates = pd.date_range("2020-01-01", periods=756, freq="B")
    prices = pd.Series(np.linspace(100.0, 180.0, len(dates)), index=dates)
    daily_rf = pd.Series(0.00005, index=dates)

    def _strategy_returns(
        *,
        mean: float,
        amplitude: float,
        phase: float,
    ) -> pd.Series:
        x = np.linspace(0.0, 10.0, len(dates))
        returns = mean + amplitude * np.sin(x + phase)
        return pd.Series(returns, index=dates)

    results = {
        "trend": BacktestResult(
            strategy_name="trend",
            strategy_description="trend strategy",
            total_return=0.20,
            win_rate=0.55,
            max_drawdown=-0.12,
            sharpe_ratio=1.20,
            total_trades=50,
            profit_factor=1.50,
            daily_returns=_strategy_returns(mean=0.00045, amplitude=0.0008, phase=0.0),
        ),
        "mean_revert": BacktestResult(
            strategy_name="mean_revert",
            strategy_description="mean reversion strategy",
            total_return=0.16,
            win_rate=0.52,
            max_drawdown=-0.10,
            sharpe_ratio=1.00,
            total_trades=45,
            profit_factor=1.30,
            daily_returns=_strategy_returns(mean=0.00035, amplitude=0.0010, phase=0.6),
        ),
        "breakout": BacktestResult(
            strategy_name="breakout",
            strategy_description="breakout strategy",
            total_return=0.18,
            win_rate=0.53,
            max_drawdown=-0.11,
            sharpe_ratio=1.10,
            total_trades=42,
            profit_factor=1.40,
            daily_returns=_strategy_returns(mean=0.00040, amplitude=0.0009, phase=1.2),
        ),
    }
    return _FakeCombinedBacktester(prices=prices, daily_rf=daily_rf, _results=results)


def _run_fixed_wfa_case() -> None:
    optimizer = WalkForwardOptimizer(_build_fixed_backtester())  # type: ignore[arg-type]
    result = optimizer.run(train_window=252, test_window=63)
    assert result is not None
    assert len(result["selection_log"]) > 0


def test_technical_wfa_fixed_case_latency_budget() -> None:
    # Warmup avoids one-time initialization overhead in measured runs.
    for _ in range(2):
        _run_fixed_wfa_case()

    timings_ms: list[float] = []
    for _ in range(5):
        start = time.perf_counter()
        _run_fixed_wfa_case()
        timings_ms.append((time.perf_counter() - start) * 1000.0)

    p50_ms = statistics.median(timings_ms)
    assert p50_ms < 250.0
