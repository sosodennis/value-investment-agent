"""
Trading Strategy Definitions for Technical Analysis.

This module implements the Strategy Pattern, separating signal generation logic
from the backtesting execution engine.

Benefits:
1. Scalability: Easy to add new strategies without modifying the backtester
2. Testability: Each strategy can be unit tested independently
3. Separation of Concerns: Strategies focus on signal logic, backtester focuses on performance calculation
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

import pandas as pd


@dataclass
class StrategyContext:
    """
    Container for all data required by trading strategies.

    This encapsulates the market data and indicators needed for signal generation,
    making it easy to pass to different strategy implementations.
    """

    prices: pd.Series
    z_score: pd.Series
    rsi: pd.Series
    obv_z: pd.Series
    bb_upper: pd.Series
    bb_lower: pd.Series


class BaseStrategy(ABC):
    """
    Abstract base class for all trading strategies.

    Each strategy must implement:
    - name: Human-readable strategy name
    - description: Explanation of the strategy logic for LLM
    - generate_signal: Core logic that produces trading signals
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Strategy name for display and identification."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable explanation of strategy logic for LLM interpretation."""
        pass

    @abstractmethod
    def generate_signal(self, ctx: StrategyContext) -> pd.Series:
        """
        Generate trading signals based on market context.

        Args:
            ctx: StrategyContext containing prices and indicators

        Returns:
            pd.Series with values:
                -1: Short position
                 0: Flat (no position)
                +1: Long position (not currently used)
        """
        pass


# --- Concrete Strategy Implementations ---


class MeanReversionStrategy(BaseStrategy):
    """
    Pure statistical mean reversion strategy.

    Shorts when price reaches extreme statistical deviations (Z>2.5),
    covers when price returns near equilibrium (Z<0.5).
    """

    @property
    def name(self) -> str:
        return "Pure Mean Reversion"

    @property
    def description(self) -> str:
        return "Shorting simply when Price Z-Score > 2.5 (Statistical Extreme)."

    def generate_signal(self, ctx: StrategyContext) -> pd.Series:
        signal = pd.Series(0, index=ctx.prices.index)
        signal[ctx.z_score > 2.5] = -1  # Enter Short
        signal[ctx.z_score < 0.5] = 0  # Exit
        return signal


class MomentumExhaustionStrategy(BaseStrategy):
    """
    Momentum exhaustion strategy with RSI confluence.

    Only shorts when BOTH price is statistically high (Z>2) AND
    momentum is extremely overbought (RSI>90). This filters out
    strong trending moves.
    """

    @property
    def name(self) -> str:
        return "Momentum Exhaustion"

    @property
    def description(self) -> str:
        return (
            "Shorting when Price Z-Score > 2.0 AND RSI is extremely overbought (>90)."
        )

    def generate_signal(self, ctx: StrategyContext) -> pd.Series:
        signal = pd.Series(0, index=ctx.prices.index)
        entry_mask = (ctx.z_score > 2.0) & (ctx.rsi > 90)
        signal[entry_mask] = -1  # Enter Short
        signal[ctx.z_score < 0.5] = 0  # Exit
        return signal


class PerfectStormStrategy(BaseStrategy):
    """
    Smart Money Divergence strategy (highest probability setup).

    Shorts when price breaks out (Z>2, >BB Upper) BUT Smart Money
    is fleeing (OBV divergence). This captures false breakouts and
    bull traps.
    """

    @property
    def name(self) -> str:
        return "Perfect Storm (Smart Money Divergence)"

    @property
    def description(self) -> str:
        return "Shorting when Price breaks out (Z>2, >BB Upper) BUT Smart Money Volume is fleeing (OBV Divergence)."

    def generate_signal(self, ctx: StrategyContext) -> pd.Series:
        signal = pd.Series(0, index=ctx.prices.index)

        # Entry: Statistical Extreme + Volatility Breakout + Volume Divergence
        entry_mask = (
            (ctx.z_score > 2.0) & (ctx.prices > ctx.bb_upper) & (ctx.obv_z < -0.5)
        )
        signal[entry_mask] = -1  # Enter Short
        signal[ctx.z_score < 0.0] = 0  # Stricter exit for this setup
        return signal


# Registry of all available strategies
ALL_STRATEGIES = [
    MeanReversionStrategy(),
    MomentumExhaustionStrategy(),
    PerfectStormStrategy(),
]
