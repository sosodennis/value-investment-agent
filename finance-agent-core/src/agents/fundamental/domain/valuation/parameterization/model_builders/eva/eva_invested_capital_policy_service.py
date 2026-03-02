from __future__ import annotations

from collections.abc import Callable

from src.shared.kernel.traceable import TraceableField


def resolve_eva_invested_capital_field(
    *,
    equity_tf: TraceableField[float],
    debt_tf: TraceableField[float],
    cash_tf: TraceableField[float],
    missing_field: Callable[[str, str], TraceableField[float]],
    computed_field: Callable[
        [str, float | list[float], str, str, dict[str, TraceableField]],
        TraceableField,
    ],
) -> TraceableField[float]:
    if equity_tf.value is None or debt_tf.value is None or cash_tf.value is None:
        return missing_field("Invested Capital", "Missing equity, debt, or cash")

    return computed_field(
        "Invested Capital",
        float(equity_tf.value) + float(debt_tf.value) - float(cash_tf.value),
        "INVESTED_CAPITAL",
        "TotalEquity + TotalDebt - Cash",
        {
            "Total Equity": equity_tf,
            "Total Debt": debt_tf,
            "Cash": cash_tf,
        },
    )
