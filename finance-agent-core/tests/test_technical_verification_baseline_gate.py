from __future__ import annotations

from src.agents.technical.subdomains.verification import (
    BacktestSummary,
    WfaSummary,
    evaluate_verification_baseline,
)


def test_verification_baseline_gate_passes_on_strong_metrics() -> None:
    backtest = BacktestSummary(
        strategy_name="trend",
        win_rate=0.6,
        profit_factor=1.6,
        sharpe_ratio=1.2,
        max_drawdown=-0.12,
        total_trades=25,
    )
    wfa = WfaSummary(
        wfa_sharpe=0.9,
        wfe_ratio=0.7,
        wfa_max_drawdown=-0.10,
        period_count=4,
    )

    gate = evaluate_verification_baseline(
        backtest_summary=backtest,
        wfa_summary=wfa,
    )

    assert gate.status == "pass"
    assert gate.blocking_count == 0
    assert gate.warning_count == 0


def test_verification_baseline_gate_blocks_without_backtest() -> None:
    gate = evaluate_verification_baseline(
        backtest_summary=None,
        wfa_summary=None,
    )

    assert gate.status == "block"
    assert gate.blocking_count >= 1
    assert any(issue.code == "BACKTEST_MISSING" for issue in gate.issues)
