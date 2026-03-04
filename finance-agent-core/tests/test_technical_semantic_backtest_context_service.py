from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import patch

import pandas as pd
import pytest

from src.agents.technical.application.fracdiff_runtime_contracts import (
    FracdiffBacktestInputs,
)
from src.agents.technical.application.ports import TechnicalRiskFreeRateFetchResult
from src.agents.technical.application.semantic_backtest_context_service import (
    assemble_backtest_context,
)
from src.interface.artifacts.artifact_data_models import (
    PriceSeriesArtifactData,
    TechnicalChartArtifactData,
)


@dataclass
class _FakeBacktester:
    label: str = "fake-backtester"


@dataclass
class _FakeWfaOptimizer:
    label: str = "fake-wfa"


class _FakeTechnicalPort:
    async def load_price_and_chart_data(
        self,
        price_artifact_id: str | None,
        chart_artifact_id: str | None,
    ) -> tuple[PriceSeriesArtifactData | None, TechnicalChartArtifactData | None]:
        _ = (price_artifact_id, chart_artifact_id)
        return (
            PriceSeriesArtifactData(
                price_series={"2025-01-01": 100.0, "2025-01-02": 101.0},
                volume_series={"2025-01-01": 1000.0, "2025-01-02": 1200.0},
            ),
            TechnicalChartArtifactData(
                fracdiff_series={"2025-01-01": 0.1, "2025-01-02": 0.2},
                z_score_series={"2025-01-01": 1.5, "2025-01-02": 1.6},
                indicators={},
            ),
        )


class _FakeFracdiffRuntime:
    def build_backtest_inputs(
        self,
        *,
        prices: pd.Series,
        volumes: pd.Series,
        fd_series: pd.Series,
        z_score_series: pd.Series,
    ) -> FracdiffBacktestInputs:
        _ = (prices, volumes, fd_series, z_score_series)
        return FracdiffBacktestInputs(
            stat_strength_dict={"value": 70.0, "series_value": pd.Series([70.0, 72.0])},
            bollinger_dict={
                "upper": 1.0,
                "middle": 0.0,
                "lower": -1.0,
                "state": "INSIDE",
                "bandwidth": 0.2,
                "series_upper": pd.Series([1.0, 1.1]),
                "series_lower": pd.Series([-1.0, -1.1]),
            },
            obv_dict={
                "raw_obv_val": 10.0,
                "fd_obv_z": 0.4,
                "optimal_d": 0.5,
                "state": "BULLISH",
                "series_z": pd.Series([0.4, 0.5]),
            },
        )


class _FakeMarketDataProvider:
    def fetch_risk_free_series(
        self, period: str = "5y"
    ) -> TechnicalRiskFreeRateFetchResult:
        _ = period
        return TechnicalRiskFreeRateFetchResult(
            data=pd.Series(
                [0.02, 0.021],
                index=pd.to_datetime(["2025-01-01", "2025-01-02"]),
            )
        )


class _FakeBacktestRuntime:
    def create_backtester(self, **kwargs: object) -> _FakeBacktester:
        _ = kwargs
        return _FakeBacktester()

    def run_backtest(
        self,
        backtester: _FakeBacktester,
        transaction_cost: float = 0.0005,
    ) -> dict[str, object]:
        _ = (backtester, transaction_cost)
        return {"sharpe": 1.2}

    def format_backtest_for_llm(self, backtest_result: dict[str, object]) -> str:
        _ = backtest_result
        return "backtest-context"

    def create_wfa_optimizer(self, backtester: _FakeBacktester) -> _FakeWfaOptimizer:
        _ = backtester
        return _FakeWfaOptimizer()

    def run_wfa(
        self,
        wfa_optimizer: _FakeWfaOptimizer,
        train_window: int = 252,
        test_window: int = 63,
    ) -> dict[str, object]:
        _ = (wfa_optimizer, train_window, test_window)
        return {"wfe": 0.6}

    def format_wfa_for_llm(self, wfa_result: dict[str, object] | None) -> str:
        _ = wfa_result
        return "wfa-context"


@pytest.mark.asyncio
async def test_assemble_backtest_context_offloads_backtest_and_wfa_to_thread() -> None:
    offloaded_calls: list[str] = []

    async def _fake_to_thread(func: object, *args: object, **kwargs: object) -> object:
        name = getattr(func, "__name__", type(func).__name__)
        offloaded_calls.append(str(name))
        return func(*args, **kwargs)  # type: ignore[misc]

    with patch(
        "src.agents.technical.application.semantic_backtest_context_service.asyncio.to_thread",
        side_effect=_fake_to_thread,
    ):
        result = await assemble_backtest_context(
            technical_port=_FakeTechnicalPort(),
            price_artifact_id="price-artifact",
            chart_artifact_id="chart-artifact",
            fracdiff_runtime=_FakeFracdiffRuntime(),
            market_data_provider=_FakeMarketDataProvider(),
            backtest_runtime=_FakeBacktestRuntime(),
        )

    assert result.backtest_context == "backtest-context"
    assert result.wfa_context == "wfa-context"
    assert "run_backtest" in offloaded_calls
    assert "run_wfa" in offloaded_calls
