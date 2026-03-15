from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

from .contracts import BacktestResult, BacktestResults
from .strategy_registry import ALL_STRATEGIES, StrategyContext


class CombinedBacktester:
    def __init__(
        self,
        price_series: pd.Series,
        z_score_series: pd.Series,
        stat_strength_dict: dict,
        obv_dict: dict,
        bollinger_dict: dict,
        rf_series: pd.Series | None = None,
        *,
        strategies: Sequence[object] | None = None,
    ):
        self.prices = price_series
        self.returns = np.log(self.prices / self.prices.shift(1)).fillna(0)

        self.z = z_score_series
        self.stat_strength = stat_strength_dict.get(
            "series_value", pd.Series(50, index=self.prices.index)
        )
        self.obv_z = obv_dict.get("series_z", pd.Series(0, index=self.prices.index))
        self.bb_upper = bollinger_dict.get(
            "series_upper", pd.Series(float("inf"), index=self.prices.index)
        )
        self.bb_lower = bollinger_dict.get(
            "series_lower", pd.Series(float("-inf"), index=self.prices.index)
        )

        self.z = self.z.reindex(self.prices.index).ffill()
        self.stat_strength = self.stat_strength.reindex(self.prices.index).ffill()
        self.obv_z = self.obv_z.reindex(self.prices.index).ffill()
        self.bb_upper = self.bb_upper.reindex(self.prices.index).ffill()
        self.bb_lower = self.bb_lower.reindex(self.prices.index).ffill()

        self.ctx = StrategyContext(
            prices=self.prices,
            z_score=self.z,
            stat_strength=self.stat_strength,
            obv_z=self.obv_z,
            bb_upper=self.bb_upper,
            bb_lower=self.bb_lower,
        )

        self.strategies = (
            list(strategies) if strategies is not None else list(ALL_STRATEGIES)
        )

        if rf_series is not None:
            fallback_daily_rate = 0.04 / 252.0
            self.daily_rf = (
                rf_series.reindex(self.prices.index).ffill().fillna(fallback_daily_rate)
            )
        else:
            self.daily_rf = pd.Series(0.04 / 252.0, index=self.prices.index)

    def run(self, transaction_cost: float = 0.001) -> BacktestResults:
        results: BacktestResults = {}
        for strategy in self.strategies:
            raw_signal = strategy.generate_signal(self.ctx)
            metrics = self._calculate_metrics(
                raw_signal,
                transaction_cost,
                name=strategy.name,
                description=strategy.description,
            )
            results[strategy.name] = metrics
        return results

    def _calculate_metrics(
        self, raw_signals: pd.Series, cost: float, name: str, description: str
    ) -> BacktestResult:
        positions = raw_signals.ffill().fillna(0)
        shifted_positions = positions.shift(1).fillna(0)
        strategy_returns = shifted_positions * self.returns

        position_changes = positions.diff()
        position_changes.iloc[0] = positions.iloc[0]
        trades_count = position_changes.abs()
        costs = trades_count * cost
        net_returns = strategy_returns - costs

        trade_starts = (shifted_positions != 0) & (shifted_positions.shift(1) == 0)
        trade_ids = trade_starts.cumsum()
        active_mask = shifted_positions != 0
        active_returns = net_returns[active_mask]
        active_trade_ids = trade_ids[active_mask]

        if not active_returns.empty:
            per_trade_pnl = active_returns.groupby(active_trade_ids).sum()
        else:
            per_trade_pnl = pd.Series(dtype=float)

        total_trades_count = len(per_trade_pnl)
        if total_trades_count > 0:
            winning_trades = (per_trade_pnl > 0).sum()
            trade_win_rate = winning_trades / total_trades_count
        else:
            trade_win_rate = 0.0

        gross_profit = per_trade_pnl[per_trade_pnl > 0].sum()
        gross_loss = per_trade_pnl[per_trade_pnl < 0].sum()
        if abs(gross_loss) > 1e-9:
            profit_factor = gross_profit / abs(gross_loss)
        else:
            profit_factor = float("inf") if gross_profit > 0 else 0.0

        cumulative = net_returns.cumsum().apply(np.exp)
        if not cumulative.empty:
            total_ret = cumulative.iloc[-1] - 1.0
            rolling_max = cumulative.cummax()
            drawdown = (cumulative - rolling_max) / rolling_max
            max_dd = drawdown.min()
        else:
            total_ret = 0.0
            max_dd = 0.0

        excess_returns = net_returns - self.daily_rf
        std_excess = excess_returns.std()
        if std_excess > 1e-6:
            sharpe = (excess_returns.mean() / std_excess) * np.sqrt(252)
        else:
            sharpe = 0.0

        return BacktestResult(
            strategy_name=name,
            strategy_description=description,
            total_return=total_ret,
            win_rate=trade_win_rate,
            max_drawdown=max_dd,
            sharpe_ratio=sharpe,
            total_trades=total_trades_count,
            profit_factor=profit_factor,
            daily_returns=net_returns,
        )
