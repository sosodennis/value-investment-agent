from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.shared.kernel.tools.logger import get_logger, log_event

logger = get_logger(__name__)


@dataclass
class StrategyContext:
    prices: pd.Series
    z_score: pd.Series
    stat_strength: pd.Series
    obv_z: pd.Series
    bb_upper: pd.Series
    bb_lower: pd.Series


class BaseStrategy(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        pass

    @abstractmethod
    def generate_signal(self, ctx: StrategyContext) -> pd.Series:
        pass


class MeanReversionStrategy(BaseStrategy):
    @property
    def name(self) -> str:
        return "Pure Mean Reversion"

    @property
    def description(self) -> str:
        return "Shorting simply when Price Z-Score > 2.5 (Statistical Extreme)."

    def generate_signal(self, ctx: StrategyContext) -> pd.Series:
        signal = pd.Series(np.nan, index=ctx.prices.index)
        signal[ctx.z_score > 2.5] = -1
        exit_mask = ctx.z_score < 0.5
        signal[exit_mask] = 0
        log_event(
            logger,
            event="technical_strategy_signal_generated",
            message="technical strategy generated signals",
            fields={
                "strategy": self.name,
                "latest_z_score": float(ctx.z_score.iloc[-1]),
                "entry_count": int((signal == -1).sum()),
                "exit_count": int((signal == 0).sum()),
            },
        )
        return signal


class MomentumExhaustionStrategy(BaseStrategy):
    @property
    def name(self) -> str:
        return "Momentum Exhaustion"

    @property
    def description(self) -> str:
        return "Shorting when Price Z-Score > 2.0 AND Probability is extremely overbought (CDF>95%)."

    def generate_signal(self, ctx: StrategyContext) -> pd.Series:
        signal = pd.Series(np.nan, index=ctx.prices.index)
        entry_mask = (ctx.z_score > 2.0) & (ctx.stat_strength > 95.0)
        signal[entry_mask] = -1
        exit_mask = ctx.z_score < 0.5
        signal[exit_mask] = 0
        log_event(
            logger,
            event="technical_strategy_signal_generated",
            message="technical strategy generated signals",
            fields={
                "strategy": self.name,
                "latest_z_score": float(ctx.z_score.iloc[-1]),
                "latest_probability": float(ctx.stat_strength.iloc[-1]),
                "entry_count": int(entry_mask.sum()),
                "exit_count": int((signal == 0).sum()),
            },
        )
        return signal


class PerfectStormStrategy(BaseStrategy):
    @property
    def name(self) -> str:
        return "Perfect Storm (Smart Money Divergence)"

    @property
    def description(self) -> str:
        return "Shorting when Price breaks out (Z>2, >BB Upper) BUT Smart Money Volume is fleeing (OBV Divergence)."

    def generate_signal(self, ctx: StrategyContext) -> pd.Series:
        signal = pd.Series(np.nan, index=ctx.prices.index)
        entry_mask = (
            (ctx.z_score > 2.0) & (ctx.prices > ctx.bb_upper) & (ctx.obv_z < -0.5)
        )
        signal[entry_mask] = -1
        exit_mask = ctx.z_score < 0.0
        signal[exit_mask] = 0
        log_event(
            logger,
            event="technical_strategy_signal_generated",
            message="technical strategy generated signals",
            fields={
                "strategy": self.name,
                "latest_z_score": float(ctx.z_score.iloc[-1]),
                "latest_obv_z": float(ctx.obv_z.iloc[-1]),
                "latest_price": float(ctx.prices.iloc[-1]),
                "entry_count": int(entry_mask.sum()),
                "exit_count": int(exit_mask.sum()),
            },
        )
        return signal


class HealthyTrendFollowingStrategy(BaseStrategy):
    @property
    def name(self) -> str:
        return "Healthy Trend Following"

    @property
    def description(self) -> str:
        return "Buying when price shows mild momentum (Z 0.5~2.0) without overheating."

    def generate_signal(self, ctx: StrategyContext) -> pd.Series:
        signal = pd.Series(np.nan, index=ctx.prices.index)
        ma20 = ctx.prices.rolling(window=20).mean()

        entry_mask = (
            (ctx.z_score > 0.5)
            & (ctx.z_score < 2.0)
            & (ctx.stat_strength > 60.0)
            & (ctx.stat_strength < 90.0)
            & (ctx.prices > ma20)
        )
        signal[entry_mask] = 1

        exit_mask = (ctx.z_score < 0) | (ctx.stat_strength > 97.7)
        signal[exit_mask] = 0

        latest_price = ctx.prices.iloc[-1]
        latest_z = ctx.z_score.iloc[-1]
        latest_prob = ctx.stat_strength.iloc[-1]
        latest_ma = ma20.iloc[-1]

        log_event(
            logger,
            event="technical_strategy_signal_generated",
            message="technical strategy generated signals",
            fields={
                "strategy": self.name,
                "latest_price": float(latest_price),
                "latest_z_score": float(latest_z),
                "latest_probability": float(latest_prob),
                "latest_ma20": float(latest_ma) if pd.notna(latest_ma) else None,
                "entry_count": int(entry_mask.sum()),
                "exit_count": int(exit_mask.sum()),
            },
        )
        return signal


ALL_STRATEGIES = [
    MeanReversionStrategy(),
    MomentumExhaustionStrategy(),
    PerfectStormStrategy(),
    HealthyTrendFollowingStrategy(),
]
