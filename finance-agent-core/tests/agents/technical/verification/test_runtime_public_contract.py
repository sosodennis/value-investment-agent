from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.agents.technical.subdomains.features.public import (
    BollingerIndicator,
    ObvIndicator,
    StatisticalStrengthSeries,
)
from src.agents.technical.subdomains.verification import (
    BacktestResult,
    BacktestResults,
    VerificationRuntimeRequest,
    VerificationRuntimeService,
    WalkForwardResult,
)


@dataclass
class _FakeBacktester:
    results: BacktestResults
    received_features: (
        tuple[StatisticalStrengthSeries, ObvIndicator, BollingerIndicator] | None
    ) = None

    def run(self, transaction_cost: float = 0.0005) -> BacktestResults:
        _ = transaction_cost
        return self.results


@dataclass
class _FailingWalkForwardOptimizer:
    def run(
        self, train_window: int = 252, test_window: int = 63
    ) -> WalkForwardResult | None:
        _ = (train_window, test_window)
        raise RuntimeError("walk-forward unavailable")


def test_runtime_accepts_public_feature_contract_and_degrades_on_wfa_error() -> None:
    dates = pd.date_range("2026-01-01", periods=3, freq="B")
    series = pd.Series([100.0, 101.0, 102.0], index=dates)
    stat_strength: StatisticalStrengthSeries = {
        "value": 55.0,
        "series_value": series,
    }
    obv: ObvIndicator = {
        "raw_obv_val": 100.0,
        "fd_obv_z": 0.4,
        "optimal_d": 0.3,
        "state": "NEUTRAL",
        "series_z": series,
    }
    bollinger: BollingerIndicator = {
        "upper": 105.0,
        "middle": 100.0,
        "lower": 95.0,
        "state": "INSIDE",
        "bandwidth": 0.1,
        "series_upper": series,
        "series_lower": series,
    }
    results = {
        "trend": BacktestResult(
            strategy_name="trend",
            strategy_description="trend strategy",
            total_return=0.12,
            win_rate=0.6,
            max_drawdown=-0.1,
            sharpe_ratio=0.9,
            total_trades=20,
            profit_factor=1.4,
            daily_returns=series.pct_change().fillna(0.0),
        )
    }
    backtester = _FakeBacktester(results=results)

    def build_backtester(
        *,
        price_series: pd.Series,
        z_score_series: pd.Series,
        stat_strength_dict: StatisticalStrengthSeries,
        obv_dict: ObvIndicator,
        bollinger_dict: BollingerIndicator,
        rf_series: pd.Series | None = None,
    ) -> _FakeBacktester:
        _ = (price_series, z_score_series, rf_series)
        backtester.received_features = (stat_strength_dict, obv_dict, bollinger_dict)
        return backtester

    def build_wfa_optimizer(
        _backtester: _FakeBacktester,
    ) -> _FailingWalkForwardOptimizer:
        return _FailingWalkForwardOptimizer()

    request = VerificationRuntimeRequest(
        ticker="AAPL",
        as_of="2026-01-05T00:00:00",
        price_series=series,
        z_score_series=series,
        stat_strength_dict=stat_strength,
        obv_dict=obv,
        bollinger_dict=bollinger,
    )
    runtime = VerificationRuntimeService(
        backtester_factory=build_backtester,
        wfa_optimizer_factory=build_wfa_optimizer,
    )

    result = runtime.compute(request)

    assert backtester.received_features == (stat_strength, obv, bollinger)
    assert result.backtest_summary is not None
    assert result.backtest_summary.strategy_name == "trend"
    assert result.backtest_summary.total_trades == 20
    assert result.wfa_summary is None
    assert result.baseline_gates.status == "warn"
    assert result.robustness_flags == ["WFA_MISSING"]
    assert result.degraded_reasons == ["WFA_MISSING"]
