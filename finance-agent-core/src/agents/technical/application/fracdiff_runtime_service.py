from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd

from src.agents.technical.application.fracdiff_runtime_contracts import (
    BollingerInput,
    FracdiffBacktestInputs,
    FracdiffRuntimeResult,
    ObvInput,
    StatisticalStrengthInput,
)
from src.agents.technical.subdomains.features.domain import (
    MacdIndicator,
    RollingFracdiffOutput,
    calculate_fd_bollinger,
    calculate_fd_macd,
    calculate_fd_obv,
    calculate_rolling_fracdiff,
    calculate_rolling_z_score,
    calculate_statistical_strength,
    compute_z_score,
    serialize_fracdiff_outputs,
)
from src.agents.technical.subdomains.signal_fusion import safe_float


@dataclass(frozen=True)
class TechnicalFracdiffRuntimeService:
    calculate_rolling_fracdiff_fn: Callable[
        [pd.Series, int, int], RollingFracdiffOutput
    ] = calculate_rolling_fracdiff
    compute_z_score_fn: Callable[[pd.Series, int], float] = compute_z_score
    calculate_rolling_z_score_fn: Callable[[pd.Series, int], pd.Series] = (
        calculate_rolling_z_score
    )
    calculate_fd_bollinger_fn: Callable[[pd.Series, int, float], BollingerInput] = (
        calculate_fd_bollinger
    )
    calculate_statistical_strength_fn: Callable[
        [pd.Series], StatisticalStrengthInput
    ] = calculate_statistical_strength
    calculate_fd_macd_fn: Callable[[pd.Series, int, int, int], MacdIndicator] = (
        calculate_fd_macd
    )
    calculate_fd_obv_fn: Callable[[pd.Series, pd.Series], ObvInput] = calculate_fd_obv

    def build_backtest_inputs(
        self,
        *,
        prices: pd.Series,
        volumes: pd.Series,
        fd_series: pd.Series,
        z_score_series: pd.Series,
    ) -> FracdiffBacktestInputs:
        return FracdiffBacktestInputs(
            stat_strength_dict=self.calculate_statistical_strength_fn(z_score_series),
            bollinger_dict=self.calculate_fd_bollinger_fn(fd_series),
            obv_dict=self.calculate_fd_obv_fn(prices, volumes),
        )

    def compute(
        self,
        *,
        prices: pd.Series,
        volumes: pd.Series,
    ) -> FracdiffRuntimeResult:
        fd_series, optimal_d, window_length, adf_stat, adf_pvalue = (
            self.calculate_rolling_fracdiff_fn(
                prices,
                lookback_window=252,
                recalc_step=5,
            )
        )

        z_score = self.compute_z_score_fn(fd_series, lookback=252)
        z_score_series = self.calculate_rolling_z_score_fn(fd_series, lookback=252)

        backtest_inputs = self.build_backtest_inputs(
            prices=prices,
            volumes=volumes,
            fd_series=fd_series,
            z_score_series=z_score_series,
        )
        bollinger_data = backtest_inputs.bollinger_dict
        stat_strength_data = backtest_inputs.stat_strength_dict
        macd_data = self.calculate_fd_macd_fn(fd_series)
        obv_data = backtest_inputs.obv_dict

        serialization = serialize_fracdiff_outputs(
            fd_series=fd_series,
            z_score_series=z_score_series,
            bollinger_data=bollinger_data,
            stat_strength_data=stat_strength_data,
            obv_data=obv_data,
        )

        chart_data = {
            "fracdiff_series": serialization.fracdiff_series,
            "z_score_series": serialization.z_score_series,
            "indicators": {
                "bollinger": serialization.bollinger.to_dict(),
                "obv": serialization.obv.to_dict(),
            },
        }

        latest_price = safe_float(prices.iloc[-1]) if not prices.empty else None
        return FracdiffRuntimeResult(
            latest_price=latest_price,
            optimal_d=safe_float(optimal_d),
            z_score_latest=safe_float(z_score),
            window_length=int(window_length),
            adf_statistic=safe_float(adf_stat),
            adf_pvalue=safe_float(adf_pvalue),
            bollinger=serialization.bollinger.to_dict(),
            statistical_strength_val=serialization.stat_strength.value,
            macd=macd_data,
            obv=serialization.obv.to_dict(),
            chart_data=chart_data,
        )
