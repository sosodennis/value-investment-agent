from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias, TypedDict

import pandas as pd


@dataclass
class BacktestResult:
    strategy_name: str
    strategy_description: str
    total_return: float
    win_rate: float
    max_drawdown: float
    sharpe_ratio: float
    total_trades: int
    profit_factor: float
    daily_returns: pd.Series | None = None


BacktestResults: TypeAlias = dict[str, BacktestResult]


class WfaSelectionRecord(TypedDict):
    date: str
    selected: str
    train_sharpe: float


class WalkForwardResult(TypedDict):
    wfa_sharpe: float
    wfa_total_return: float
    wfa_max_drawdown: float
    wfa_equity_curve: pd.Series
    selection_log: list[WfaSelectionRecord]
    full_backtest_results: BacktestResults


@dataclass(frozen=True)
class BacktestSummary:
    strategy_name: str | None
    win_rate: float
    profit_factor: float
    sharpe_ratio: float
    max_drawdown: float
    total_trades: int


@dataclass(frozen=True)
class WfaSummary:
    wfa_sharpe: float
    wfe_ratio: float
    wfa_max_drawdown: float
    period_count: int
