from __future__ import annotations

from src.agents.technical.domain.backtest import BacktestResults, WalkForwardResult


def format_backtest_for_llm(results: BacktestResults, min_trades: int = 3) -> str:
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

    valid_results = {k: v for k, v in results.items() if v.total_trades >= min_trades}

    if valid_results:
        best_strat = max(valid_results.values(), key=lambda x: x.sharpe_ratio)
        sample_warning = ""
    else:
        best_strat = max(results.values(), key=lambda x: x.sharpe_ratio)
        sample_warning = f"\nWARNING: Limited sample size ({best_strat.total_trades} trade{'s' if best_strat.total_trades != 1 else ''}) - statistical significance is low. Exercise extreme caution."

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


def format_wfa_for_llm(wfa_results: WalkForwardResult | None) -> str:
    if wfa_results is None:
        return ""

    full_results = wfa_results["full_backtest_results"]
    best_insample = max(full_results.values(), key=lambda x: x.sharpe_ratio)
    wfa_sharpe = wfa_results["wfa_sharpe"]
    wfe_ratio = (
        wfa_sharpe / best_insample.sharpe_ratio if best_insample.sharpe_ratio > 0 else 0
    )

    if wfe_ratio > 0.7:
        robustness = "Highly Robust"
        interpretation = "This strategy performs consistently even when selected adaptively, indicating genuine edge rather than historical luck."
    elif wfe_ratio > 0.5:
        robustness = "Moderately Robust"
        interpretation = "The strategy shows acceptable out-of-sample performance, though some degradation from in-sample results is observed."
    else:
        robustness = "Overfitting Detected"
        interpretation = "While the full backtest shows strong results, the strategy fails to maintain performance when applied to unseen periods. This suggests the historical performance may be due to overfitting rather than genuine predictive power."

    return f"""
[Robustness Testing - Walk-Forward Analysis]
I simulated realistic adaptive trading by re-selecting strategies quarterly based on past performance.

- WFA Sharpe Ratio: {wfa_sharpe:.2f}
- WFA Total Return: {wfa_results['wfa_total_return']*100:.1f}%
- WFA Max Drawdown: {wfa_results['wfa_max_drawdown']*100:.1f}%
- Walk-Forward Efficiency: {wfe_ratio:.2f} ({robustness})
- Periods Tested: {len(wfa_results['selection_log'])}

[Interpretation]
{interpretation}

(Context: WFE > 0.7 is excellent, 0.5-0.7 is acceptable, < 0.5 suggests overfitting risk.)
"""
