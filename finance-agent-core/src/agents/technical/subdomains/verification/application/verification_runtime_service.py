from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

import pandas as pd

from src.agents.technical.subdomains.features.domain import (
    BollingerIndicator,
    ObvIndicator,
    StatisticalStrengthSeries,
)
from src.agents.technical.subdomains.verification.domain import (
    BacktestResults,
    BacktestSummary,
    CombinedBacktester,
    VerificationBaselineThresholds,
    VerificationGateResult,
    WalkForwardOptimizer,
    WalkForwardResult,
    WfaSummary,
    evaluate_verification_baseline,
)
from src.shared.kernel.tools.logger import get_logger, log_event

logger = get_logger(__name__)


@dataclass(frozen=True)
class VerificationRuntimeRequest:
    ticker: str
    as_of: str
    price_series: pd.Series
    z_score_series: pd.Series
    stat_strength_dict: StatisticalStrengthSeries
    obv_dict: ObvIndicator
    bollinger_dict: BollingerIndicator
    rf_series: pd.Series | None = None


@dataclass(frozen=True)
class VerificationRuntimeResult:
    backtest_summary: BacktestSummary | None
    wfa_summary: WfaSummary | None
    baseline_gates: VerificationGateResult
    robustness_flags: list[str] = field(default_factory=list)
    degraded_reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class VerificationRuntimeService:
    transaction_cost: float = 0.0005
    train_window: int = 252
    test_window: int = 63
    thresholds: VerificationBaselineThresholds = field(
        default_factory=VerificationBaselineThresholds
    )
    backtester_factory: Callable[..., CombinedBacktester] = CombinedBacktester
    wfa_optimizer_factory: Callable[[CombinedBacktester], WalkForwardOptimizer] = (
        WalkForwardOptimizer
    )

    def compute(self, request: VerificationRuntimeRequest) -> VerificationRuntimeResult:
        log_event(
            logger,
            event="technical_verification_compute_started",
            message="technical verification compute started",
            fields={"ticker": request.ticker},
        )

        backtester = self.backtester_factory(
            price_series=request.price_series,
            z_score_series=request.z_score_series,
            stat_strength_dict=request.stat_strength_dict,
            obv_dict=request.obv_dict,
            bollinger_dict=request.bollinger_dict,
            rf_series=request.rf_series,
        )

        backtest_results = backtester.run(transaction_cost=self.transaction_cost)
        backtest_summary = _summarize_backtest(backtest_results)

        wfa_summary = None
        wfa_result = None
        try:
            wfa_optimizer = self.wfa_optimizer_factory(backtester)
            wfa_result = wfa_optimizer.run(
                train_window=self.train_window,
                test_window=self.test_window,
            )
        except Exception as exc:
            log_event(
                logger,
                event="technical_verification_wfa_failed",
                message="technical verification walk-forward failed",
                level=logging.WARNING,
                error_code="TECHNICAL_VERIFICATION_WFA_FAILED",
                fields={"ticker": request.ticker, "exception": str(exc)},
            )

        if wfa_result is not None:
            wfa_summary = _summarize_wfa(wfa_result, backtest_results)

        baseline_gates = evaluate_verification_baseline(
            backtest_summary=backtest_summary,
            wfa_summary=wfa_summary,
            thresholds=self.thresholds,
        )
        robustness_flags = _flags_from_gate(baseline_gates)
        degraded_reasons = _degraded_reasons(baseline_gates)

        if degraded_reasons:
            log_event(
                logger,
                event="technical_verification_compute_degraded",
                message="technical verification compute completed with degraded quality",
                level=logging.WARNING,
                error_code="TECHNICAL_VERIFICATION_DEGRADED",
                fields={
                    "ticker": request.ticker,
                    "baseline_status": baseline_gates.status,
                    "degraded_reasons": degraded_reasons,
                },
            )

        log_event(
            logger,
            event="technical_verification_compute_completed",
            message="technical verification compute completed",
            fields={
                "ticker": request.ticker,
                "status": "done",
                "baseline_status": baseline_gates.status,
                "is_degraded": bool(degraded_reasons),
                "artifact_written": False,
            },
        )

        return VerificationRuntimeResult(
            backtest_summary=backtest_summary,
            wfa_summary=wfa_summary,
            baseline_gates=baseline_gates,
            robustness_flags=robustness_flags,
            degraded_reasons=degraded_reasons,
        )


def _summarize_backtest(results: BacktestResults) -> BacktestSummary | None:
    if not results:
        return None
    total_trades = sum(result.total_trades for result in results.values())
    if total_trades == 0:
        return None

    valid = [result for result in results.values() if result.total_trades > 0]
    candidates = valid or list(results.values())
    best = max(candidates, key=lambda item: item.sharpe_ratio)

    return BacktestSummary(
        strategy_name=best.strategy_name,
        win_rate=best.win_rate,
        profit_factor=best.profit_factor,
        sharpe_ratio=best.sharpe_ratio,
        max_drawdown=best.max_drawdown,
        total_trades=best.total_trades,
    )


def _summarize_wfa(
    wfa_result: WalkForwardResult,
    backtest_results: BacktestResults,
) -> WfaSummary:
    wfa_sharpe = float(wfa_result.get("wfa_sharpe", 0.0))
    wfa_max_drawdown = float(wfa_result.get("wfa_max_drawdown", 0.0))
    selection_log = wfa_result.get("selection_log", [])
    period_count = len(selection_log) if isinstance(selection_log, list) else 0

    best_sharpe = 0.0
    if backtest_results:
        best_sharpe = max(result.sharpe_ratio for result in backtest_results.values())
    wfe_ratio = wfa_sharpe / best_sharpe if best_sharpe > 0 else 0.0

    return WfaSummary(
        wfa_sharpe=wfa_sharpe,
        wfe_ratio=wfe_ratio,
        wfa_max_drawdown=wfa_max_drawdown,
        period_count=period_count,
    )


def _flags_from_gate(gates: VerificationGateResult) -> list[str]:
    flags: list[str] = []
    for issue in gates.issues:
        if issue.code == "BACKTEST_LOW_SAMPLE":
            flags.append("LOW_SAMPLE")
        elif issue.code == "BACKTEST_LOW_SHARPE":
            flags.append("LOW_SHARPE")
        elif issue.code == "BACKTEST_LOW_PROFIT_FACTOR":
            flags.append("LOW_PROFIT_FACTOR")
        elif issue.code == "BACKTEST_MAX_DRAWDOWN":
            flags.append("HIGH_DRAWDOWN")
        elif issue.code == "WFA_LOW_EFFICIENCY":
            flags.append("LOW_WFE")
        elif issue.code == "WFA_LOW_SHARPE":
            flags.append("LOW_WFA_SHARPE")
        elif issue.code == "WFA_LOW_PERIODS":
            flags.append("LOW_WFA_PERIODS")
        elif issue.code == "BACKTEST_MISSING":
            flags.append("BACKTEST_MISSING")
        elif issue.code == "WFA_MISSING":
            flags.append("WFA_MISSING")
    return flags


def _degraded_reasons(gates: VerificationGateResult) -> list[str]:
    if gates.status == "pass":
        return []
    return [issue.code for issue in gates.issues]
