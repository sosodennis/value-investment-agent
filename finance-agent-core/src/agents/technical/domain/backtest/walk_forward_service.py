from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from src.shared.kernel.tools.logger import get_logger, log_event

from .contracts import WalkForwardResult, WfaSelectionRecord
from .engine_service import CombinedBacktester

logger = get_logger(__name__)


class WalkForwardOptimizer:
    def __init__(self, backtester: CombinedBacktester):
        self.bt = backtester

    def run(
        self, train_window: int = 252, test_window: int = 63
    ) -> WalkForwardResult | None:
        log_event(
            logger,
            event="technical_wfa_started",
            message="technical walk-forward analysis started",
            fields={"train_window": train_window, "test_window": test_window},
        )

        full_results = self.bt.run()
        valid_strategies = {k: v for k, v in full_results.items() if v.total_trades > 0}
        if not valid_strategies:
            log_event(
                logger,
                event="technical_wfa_no_trades",
                message="technical walk-forward analysis aborted due to zero trades",
                level=logging.WARNING,
                error_code="TECHNICAL_WFA_NO_TRADES",
            )
            return None

        full_dates = self.bt.prices.index
        n_days = len(full_dates)

        if n_days < train_window + test_window:
            log_event(
                logger,
                event="technical_wfa_insufficient_data",
                message="technical walk-forward analysis aborted due to insufficient data",
                level=logging.WARNING,
                error_code="TECHNICAL_WFA_INSUFFICIENT_DATA",
                fields={
                    "required_days": train_window + test_window,
                    "available_days": n_days,
                },
            )
            return None

        wfa_returns = pd.Series(0.0, index=full_dates)
        selection_log: list[WfaSelectionRecord] = []

        for i in range(train_window, n_days, test_window):
            train_start_idx = i - train_window
            train_end_idx = i
            test_end_idx = min(i + test_window, n_days)

            if train_end_idx >= n_days:
                break

            best_score = -float("inf")
            best_strat_name = None

            for name, res in valid_strategies.items():
                train_returns = res.daily_returns.iloc[train_start_idx:train_end_idx]
                if train_returns.std() > 1e-6:
                    score = train_returns.mean() / train_returns.std()
                else:
                    score = 0

                if score > best_score:
                    best_score = score
                    best_strat_name = name

            if best_strat_name:
                future_returns = valid_strategies[best_strat_name].daily_returns.iloc[
                    train_end_idx:test_end_idx
                ]
                wfa_returns.iloc[train_end_idx:test_end_idx] = future_returns
                selection_log.append(
                    {
                        "date": str(full_dates[train_end_idx]),
                        "selected": best_strat_name,
                        "train_sharpe": float(best_score),
                    }
                )

        wfa_cumulative = wfa_returns.cumsum().apply(np.exp)
        rolling_max = wfa_cumulative.cummax()
        drawdown = (wfa_cumulative - rolling_max) / rolling_max
        max_dd = drawdown.min()

        total_ret = wfa_cumulative.iloc[-1] - 1.0 if not wfa_cumulative.empty else 0.0
        rf_series = self.bt.daily_rf
        wfa_excess_returns = wfa_returns - rf_series

        std_excess = wfa_excess_returns.std()
        if std_excess > 1e-6:
            sharpe = (wfa_excess_returns.mean() / std_excess) * np.sqrt(252)
        else:
            sharpe = 0.0

        log_event(
            logger,
            event="technical_wfa_completed",
            message="technical walk-forward analysis completed",
            fields={
                "wfa_sharpe": float(sharpe),
                "wfa_total_return": float(total_ret),
                "wfa_max_drawdown": float(max_dd),
                "selection_count": len(selection_log),
            },
        )

        return {
            "wfa_sharpe": sharpe,
            "wfa_total_return": total_ret,
            "wfa_max_drawdown": max_dd,
            "wfa_equity_curve": wfa_cumulative,
            "selection_log": selection_log,
            "full_backtest_results": full_results,
        }
