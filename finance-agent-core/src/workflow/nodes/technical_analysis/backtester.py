"""
Vectorized Backtesting Engine for TA Agent.

This module performs fast, vectorized simulations of trading strategies
to provide statistical evidence (Confidence Score) for the LLM.

Key Features:
1. Pure Vectorization: No loops, runs in milliseconds.
2. Multi-Factor Strategies: Tests Pure Z, Momentum, and Confluence setups.
3. Transaction Costs: Simulates slippage and commissions for realism.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.utils.logger import get_logger

from .strategies import ALL_STRATEGIES, StrategyContext

logger = get_logger(__name__)


@dataclass
class BacktestResult:
    """Container for backtest metrics."""

    strategy_name: str
    strategy_description: str  # Human-readable explanation for LLM
    total_return: float  # e.g., 0.15 for 15%
    win_rate: float  # e.g., 0.65 for 65% (per trade)
    max_drawdown: float  # e.g., -0.12 for -12%
    sharpe_ratio: float  # Risk-adjusted return
    total_trades: int
    profit_factor: float  # Total profit / Absolute total loss


class CombinedBacktester:
    """
    Executes multiple strategies simultaneously on historical data.
    """

    def __init__(
        self,
        price_series: pd.Series,
        z_score_series: pd.Series,
        rsi_dict: dict,
        obv_dict: dict,
        bollinger_dict: dict,
    ):
        """
        Initialize with full historical series from tools.py.

        Args:
            price_series: Adjusted Close prices.
            z_score_series: FracDiff Z-Score history.
            rsi_dict: Output from calculate_fd_rsi_metrics (must contain 'series_value').
            obv_dict: Output from calculate_fd_obv (must contain 'series_z').
            bollinger_dict: Output from calculate_fd_bollinger (must contain 'series_upper'/'lower').
        """
        self.prices = price_series
        # Calculate Log Returns for vectorization efficiency
        self.returns = np.log(self.prices / self.prices.shift(1)).fillna(0)

        # Unpack indicators
        # [Defensive] Use .get() and fallback to zeros if series missing
        self.z = z_score_series
        self.rsi = rsi_dict.get("series_value", pd.Series(50, index=self.prices.index))
        self.obv_z = obv_dict.get("series_z", pd.Series(0, index=self.prices.index))
        self.bb_upper = bollinger_dict.get(
            "series_upper", pd.Series(float("inf"), index=self.prices.index)
        )

        # Align indices (Crucial for vectorization)
        # Ensure all series share the exact same index as prices
        self.z = self.z.reindex(self.prices.index).ffill()
        self.rsi = self.rsi.reindex(self.prices.index).ffill()
        self.obv_z = self.obv_z.reindex(self.prices.index).ffill()
        self.bb_upper = self.bb_upper.reindex(self.prices.index).ffill()
        self.bb_lower = bollinger_dict.get(
            "series_lower", pd.Series(float("-inf"), index=self.prices.index)
        )
        self.bb_lower = self.bb_lower.reindex(self.prices.index).ffill()

        # Package context for strategies
        self.ctx = StrategyContext(
            prices=self.prices,
            z_score=self.z,
            rsi=self.rsi,
            obv_z=self.obv_z,
            bb_upper=self.bb_upper,
            bb_lower=self.bb_lower,
        )

        # Register strategies (easy to extend by adding to ALL_STRATEGIES)
        self.strategies = ALL_STRATEGIES

    def run(self, transaction_cost: float = 0.001) -> dict:
        """
        Run all registered strategies and return metrics.

        Args:
            transaction_cost: Estimated cost per trade (slippage + comms).
                              0.001 = 0.1% (Conservative for US equities).
        """
        results = {}

        for strategy in self.strategies:
            # 1. Generate signal using strategy logic
            raw_signal = strategy.generate_signal(self.ctx)

            # 2. Calculate performance metrics
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
        """
        Core vectorized calculation engine.
        Includes fixes for Trade Counting and Initial Position handling.
        """
        # 1. Position Management
        # Forward fill signals to simulate holding positions
        positions = raw_signals.replace(0, np.nan).ffill().fillna(0)

        # 2. Shift Positions (Correctly handling Look-Ahead Bias)
        # Shift(1) means we trade at Close(t) but realize PnL at Close(t+1)
        # This effectively models a "Next Day Open" entry if Open ~ Close
        shifted_positions = positions.shift(1).fillna(0)

        # 3. Calculate Strategy Returns
        strategy_returns = shifted_positions * self.returns

        # 4. Apply Transaction Costs
        # [Fix] Correctly count the first trade if it starts immediately
        position_changes = positions.diff()
        position_changes.iloc[0] = positions.iloc[0]  # Fix for Issue #2

        trades_count = position_changes.abs()
        costs = trades_count * cost

        # Note: Subtracting linear cost from log return is an approximation
        net_returns = strategy_returns - costs

        # --- Vectorized Trade Grouping ---
        # Find the day when a trade starts (yesterday flat, today holding)
        trade_starts = (shifted_positions != 0) & (shifted_positions.shift(1) == 0)
        trade_ids = trade_starts.cumsum()

        # Filter active days
        active_mask = shifted_positions != 0
        active_returns = net_returns[active_mask]
        active_trade_ids = trade_ids[active_mask]

        # Calculate PnL per trade
        if not active_returns.empty:
            per_trade_pnl = active_returns.groupby(active_trade_ids).sum()
        else:
            per_trade_pnl = pd.Series(dtype=float)

        # --- 5. Compute Metrics ---

        # A. True Trade Win Rate
        total_trades_count = len(per_trade_pnl)
        if total_trades_count > 0:
            winning_trades = (per_trade_pnl > 0).sum()
            trade_win_rate = winning_trades / total_trades_count
        else:
            trade_win_rate = 0.0

        # B. Profit Factor
        gross_profit = per_trade_pnl[per_trade_pnl > 0].sum()
        gross_loss = per_trade_pnl[per_trade_pnl < 0].sum()

        if abs(gross_loss) > 1e-9:  # Avoid division by zero
            profit_factor = gross_profit / abs(gross_loss)
        else:
            profit_factor = float("inf") if gross_profit > 0 else 0.0

        # C. Traditional Metrics
        cumulative = net_returns.cumsum().apply(np.exp)

        # [Defensive] Handle empty returns
        if not cumulative.empty:
            total_ret = cumulative.iloc[-1] - 1.0
            rolling_max = cumulative.cummax()
            drawdown = (cumulative - rolling_max) / rolling_max
            max_dd = drawdown.min()
        else:
            total_ret = 0.0
            max_dd = 0.0

        # Sharpe Ratio
        std = net_returns.std()
        if std > 1e-6:
            sharpe = (net_returns.mean() / std) * np.sqrt(252)
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
        )


def format_backtest_for_llm(results: dict, min_trades: int = 3) -> str:
    """
    Format backtest results for LLM consumption.
    Handles cases with NO valid trades gracefully.

    Args:
        results: Dictionary of BacktestResult objects from CombinedBacktester.run()
        min_trades: Minimum number of trades required for statistical significance (default: 3)

    Returns:
        Formatted string for LLM prompt
    """
    # 1. Check if ANY strategy generated trades
    total_trades_all = sum(r.total_trades for r in results.values())

    if total_trades_all == 0:
        return """
[Statistical Verification]
I have simulated 5 years of trading, but **NO historical setups were triggered** for this asset under strict institutional criteria.

- Observation: This asset is statistically extremely stable (low volatility profile).
- Conclusion: The current strategies (Shorting on Z>2.5) are too aggressive for this specific stock's volatility characteristics.
- Recommendation: The asset remains within its historical equilibrium range. Monitor for Z-Score extremes (>2.5) for potential mean reversion opportunities, but avoid aggressive positioning given the neutral consolidation.

(Context: A lack of historical triggers indicates the asset rarely deviates from its long-term memory structure - this is actually a sign of structural stability, not a flaw in the analysis.)
"""

    # 2. Filter out strategies with insufficient sample size (< min_trades)
    # This prevents overfitting and ensures statistical validity
    valid_results = {k: v for k, v in results.items() if v.total_trades >= min_trades}

    # Select best strategy from valid results, or fall back to best overall if none are valid
    if valid_results:
        best_strat = max(valid_results.values(), key=lambda x: x.sharpe_ratio)
        sample_warning = ""
    else:
        # All strategies have low sample size - select best but add warning
        best_strat = max(results.values(), key=lambda x: x.sharpe_ratio)
        sample_warning = f"\n⚠️ WARNING: Limited sample size ({best_strat.total_trades} trade{'s' if best_strat.total_trades != 1 else ''}) - statistical significance is low. Exercise extreme caution."

    # Determine strategy interpretation based on metrics
    if best_strat.profit_factor > 2.0 and best_strat.win_rate < 0.4:
        interpretation = "This strategy has low accuracy but wins BIG when it works (Trend Following)."
    elif best_strat.win_rate > 0.65 and best_strat.profit_factor < 1.2:
        interpretation = "High accuracy but profits are thin. Be careful of slippage."
    elif best_strat.profit_factor > 1.5 and best_strat.win_rate > 0.5:
        interpretation = "Balanced strategy with good accuracy and profit potential."
    else:
        interpretation = "Strategy shows mixed results. Exercise caution."

    return f"""
[Statistical Verification]
I have simulated 5 years of trading to validate this setup.
The best performing logic was: "{best_strat.strategy_name}"

- Logic: {best_strat.strategy_description}
- Win Rate: {best_strat.win_rate*100:.1f}% (Per Trade)
- Profit Factor: {best_strat.profit_factor:.2f} (Gross Profit / Gross Loss)
- Sharpe Ratio: {best_strat.sharpe_ratio:.2f}
- Total Trades: {best_strat.total_trades}{sample_warning}

[Interpretation Guide]
{interpretation}

(Context: A Profit Factor > 1.5 implies the strategy is robust. A high Sharpe Ratio > 1.0 means returns are stable.)
"""
