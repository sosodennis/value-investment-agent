from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .contracts import BacktestSummary, WfaSummary

_POLICY_VERSION = "technical_verification_baseline_v1_2026_03_12"


@dataclass(frozen=True)
class VerificationBaselineThresholds:
    min_trades: int = 15
    min_profit_factor: float = 1.1
    min_sharpe: float = 0.5
    max_drawdown_floor: float = -0.35
    min_wfa_sharpe: float = 0.3
    min_wfe_ratio: float = 0.5
    min_wfa_periods: int = 3


@dataclass(frozen=True)
class VerificationGateIssue:
    code: str
    message: str
    blocking: bool
    metric: str | None = None
    actual: float | int | None = None
    threshold: float | int | None = None


@dataclass(frozen=True)
class VerificationGateResult:
    status: Literal["pass", "warn", "block"]
    policy_version: str
    blocking_count: int
    warning_count: int
    issues: tuple[VerificationGateIssue, ...]


def evaluate_verification_baseline(
    *,
    backtest_summary: BacktestSummary | None,
    wfa_summary: WfaSummary | None,
    thresholds: VerificationBaselineThresholds | None = None,
) -> VerificationGateResult:
    policy = thresholds or VerificationBaselineThresholds()
    issues: list[VerificationGateIssue] = []

    if backtest_summary is None:
        issues.append(
            _issue(
                code="BACKTEST_MISSING",
                message="Backtest summary is unavailable",
                blocking=True,
            )
        )
    else:
        if backtest_summary.total_trades < policy.min_trades:
            issues.append(
                _issue(
                    code="BACKTEST_LOW_SAMPLE",
                    message="Backtest sample size below baseline",
                    blocking=False,
                    metric="total_trades",
                    actual=backtest_summary.total_trades,
                    threshold=policy.min_trades,
                )
            )
        if backtest_summary.profit_factor < policy.min_profit_factor:
            issues.append(
                _issue(
                    code="BACKTEST_LOW_PROFIT_FACTOR",
                    message="Backtest profit factor below baseline",
                    blocking=False,
                    metric="profit_factor",
                    actual=backtest_summary.profit_factor,
                    threshold=policy.min_profit_factor,
                )
            )
        if backtest_summary.sharpe_ratio < policy.min_sharpe:
            issues.append(
                _issue(
                    code="BACKTEST_LOW_SHARPE",
                    message="Backtest Sharpe below baseline",
                    blocking=False,
                    metric="sharpe_ratio",
                    actual=backtest_summary.sharpe_ratio,
                    threshold=policy.min_sharpe,
                )
            )
        if backtest_summary.max_drawdown < policy.max_drawdown_floor:
            issues.append(
                _issue(
                    code="BACKTEST_MAX_DRAWDOWN",
                    message="Backtest drawdown exceeds baseline",
                    blocking=False,
                    metric="max_drawdown",
                    actual=backtest_summary.max_drawdown,
                    threshold=policy.max_drawdown_floor,
                )
            )

    if wfa_summary is None:
        issues.append(
            _issue(
                code="WFA_MISSING",
                message="Walk-forward summary is unavailable",
                blocking=False,
            )
        )
    else:
        if wfa_summary.wfa_sharpe < policy.min_wfa_sharpe:
            issues.append(
                _issue(
                    code="WFA_LOW_SHARPE",
                    message="WFA Sharpe below baseline",
                    blocking=False,
                    metric="wfa_sharpe",
                    actual=wfa_summary.wfa_sharpe,
                    threshold=policy.min_wfa_sharpe,
                )
            )
        if wfa_summary.wfe_ratio < policy.min_wfe_ratio:
            issues.append(
                _issue(
                    code="WFA_LOW_EFFICIENCY",
                    message="Walk-forward efficiency below baseline",
                    blocking=False,
                    metric="wfe_ratio",
                    actual=wfa_summary.wfe_ratio,
                    threshold=policy.min_wfe_ratio,
                )
            )
        if wfa_summary.period_count < policy.min_wfa_periods:
            issues.append(
                _issue(
                    code="WFA_LOW_PERIODS",
                    message="WFA period count below baseline",
                    blocking=False,
                    metric="period_count",
                    actual=wfa_summary.period_count,
                    threshold=policy.min_wfa_periods,
                )
            )

    blocking_count = sum(1 for issue in issues if issue.blocking)
    warning_count = len(issues) - blocking_count
    status: Literal["pass", "warn", "block"] = "pass"
    if blocking_count:
        status = "block"
    elif warning_count:
        status = "warn"

    return VerificationGateResult(
        status=status,
        policy_version=_POLICY_VERSION,
        blocking_count=blocking_count,
        warning_count=warning_count,
        issues=tuple(issues),
    )


def _issue(
    *,
    code: str,
    message: str,
    blocking: bool,
    metric: str | None = None,
    actual: float | int | None = None,
    threshold: float | int | None = None,
) -> VerificationGateIssue:
    return VerificationGateIssue(
        code=code,
        message=message,
        blocking=blocking,
        metric=metric,
        actual=actual,
        threshold=threshold,
    )
