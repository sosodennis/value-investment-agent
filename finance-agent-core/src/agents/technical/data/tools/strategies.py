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

import numpy as np
import pandas as pd

from src.shared.kernel.tools.logger import get_logger

logger = get_logger(__name__)


@dataclass
class StrategyContext:
    """
    Container for all data required by trading strategies.

    This encapsulates the market data and indicators needed for signal generation,
    making it easy to pass to different strategy implementations.
    """

    prices: pd.Series
    z_score: pd.Series
    stat_strength: pd.Series
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
        # Initialize as NaN (Hold / No Action)
        signal = pd.Series(np.nan, index=ctx.prices.index)

        # Entry (Short)
        signal[ctx.z_score > 2.5] = -1  # Enter Short

        # Exit (Flat)
        exit_mask = ctx.z_score < 0.5
        signal[exit_mask] = 0  # Exit to Cash

        # [Logging]
        logger.info(
            f"Strategy [{self.name}] Analysis: "
            f"Z={ctx.z_score.iloc[-1]:.2f} | "
            f"Signals Generated: Entries={(signal == -1).sum()}, Exits={(signal == 0).sum()}"
        )
        return signal


class MomentumExhaustionStrategy(BaseStrategy):
    """
    Momentum exhaustion strategy with Statistical Strength confluence.

    Only shorts when BOTH price is statistically high (Z>2) AND
    probability is extremely overbought (CDF>95%). This filters out
    strong trending moves.
    """

    @property
    def name(self) -> str:
        return "Momentum Exhaustion"

    @property
    def description(self) -> str:
        return "Shorting when Price Z-Score > 2.0 AND Probability is extremely overbought (CDF>95%)."

    def generate_signal(self, ctx: StrategyContext) -> pd.Series:
        # Initialize as NaN (Hold / No Action)
        signal = pd.Series(np.nan, index=ctx.prices.index)

        # Entry (Short)
        # [Update] Use CDF > 95.0 (approx 1.65 sigma) for exhaustion
        entry_mask = (ctx.z_score > 2.0) & (ctx.stat_strength > 95.0)
        signal[entry_mask] = -1  # Enter Short

        # Exit (Flat)
        exit_mask = ctx.z_score < 0.5
        signal[exit_mask] = 0  # Exit to Cash

        # [Logging]
        logger.info(
            f"Strategy [{self.name}] Analysis: "
            f"Z={ctx.z_score.iloc[-1]:.2f}, Prob={ctx.stat_strength.iloc[-1]:.1f}% | "
            f"Signals Generated: Entries={entry_mask.sum()}, Exits={(signal == 0).sum()}"
        )
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
        # Initialize as NaN (Hold / No Action)
        signal = pd.Series(np.nan, index=ctx.prices.index)

        # Entry (Short): Statistical Extreme + Volatility Breakout + Volume Divergence
        entry_mask = (
            (ctx.z_score > 2.0) & (ctx.prices > ctx.bb_upper) & (ctx.obv_z < -0.5)
        )
        signal[entry_mask] = -1  # Enter Short

        # Exit (Flat)
        exit_mask = ctx.z_score < 0.0
        signal[exit_mask] = 0  # Stricter exit for this setup

        # [Logging]
        logger.info(
            f"Strategy [{self.name}] Analysis: "
            f"Z={ctx.z_score.iloc[-1]:.2f}, OBV_Z={ctx.obv_z.iloc[-1]:.2f}, Price={ctx.prices.iloc[-1]:.2f} | "
            f"Signals Generated: Entries={entry_mask.sum()}, Exits={exit_mask.sum()}"
        )
        return signal


class HealthyTrendFollowingStrategy(BaseStrategy):
    """
    Trend following strategy for healthy momentum.

    Captures steady trends in stable stocks by entering when momentum
    is positive but not overheated, and structure is robust.
    """

    @property
    def name(self) -> str:
        return "Healthy Trend Following"

    @property
    def description(self) -> str:
        return "Buying when price shows mild momentum (Z 0.5~2.0) without overheating."

    def generate_signal(self, ctx: StrategyContext) -> pd.Series:
        # Initialize as NaN (Hold / No Action)
        signal = pd.Series(np.nan, index=ctx.prices.index)

        # [Fix] Calculate MA20 directly from prices for structural trend detection
        ma20 = ctx.prices.rolling(window=20).mean()

        # Entry (Long):
        # 1. Z-Score in healthy range (0.5 ~ 2.0) - trending but not extreme
        # 2. Probability in strong confirmed trend range (60% ~ 90%)
        #    - > 50% means trend is positive
        #    - < 90% means not yet overextended (approx 1.3 sigma)
        # 3. Price > 20-day MA - structural uptrend
        entry_mask = (
            (ctx.z_score > 0.5)
            & (ctx.z_score < 2.0)
            & (ctx.stat_strength > 60.0)
            & (ctx.stat_strength < 90.0)
            & (ctx.prices > ma20)
        )

        signal[entry_mask] = 1  # Enter Long

        # [Fix] Exit Conditions (Explicitly set 0 for Flat)
        # 1. Trend reversal (Z < 0)
        # 2. Overheating (Probability > 97.7% / +2 Sigma)
        exit_mask = (ctx.z_score < 0) | (ctx.stat_strength > 97.7)
        signal[exit_mask] = 0  # Exit to Cash

        # [Logging] Show latest metrics for debugging
        latest_price = ctx.prices.iloc[-1]
        latest_z = ctx.z_score.iloc[-1]
        latest_prob = ctx.stat_strength.iloc[-1]
        latest_ma = ma20.iloc[-1]

        # Statistics for historical activity
        total_entries = entry_mask.sum()
        total_exits = exit_mask.sum()

        logger.info(
            f"Strategy [{self.name}] Analysis: "
            f"Price={latest_price:.2f}, Z={latest_z:.2f}, Prob={latest_prob:.1f}%, MA20={latest_ma:.2f} | "
            f"Signals Generated: Entries={total_entries}, Exits={total_exits}"
        )

        return signal


# Registry of all available strategies
ALL_STRATEGIES = [
    MeanReversionStrategy(),
    MomentumExhaustionStrategy(),
    PerfectStormStrategy(),
    HealthyTrendFollowingStrategy(),
]
