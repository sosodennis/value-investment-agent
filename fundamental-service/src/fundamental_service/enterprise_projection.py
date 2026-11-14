"""The shared enterprise stage of the released FCFF calculation graph."""

from decimal import Decimal

from .contracts import (
    CalculationNodeV1,
    ForecastAssumptionsV1,
    TraceV1,
    WaccAssumptionsV1,
)
from .numerical_policy import using_valuation_context
from .operating_projection import OperatingProjectionError, project_operating_nodes


def _node(
    node_id: str, formula: str, value: Decimal, unit: str, inputs: tuple[str, ...]
) -> CalculationNodeV1:
    return CalculationNodeV1(
        node_id=node_id,
        formula=formula,
        inputs=inputs,
        value=value,
        unit=unit,
        trace=TraceV1(expression=formula, inputs=inputs),
    )


@using_valuation_context
def project_enterprise_nodes(
    forecast: ForecastAssumptionsV1,
    *,
    wacc: WaccAssumptionsV1,
    terminal_growth: Decimal,
    historical_fact_ids: tuple[str, ...],
) -> tuple[CalculationNodeV1, ...]:
    """Evaluate the existing DCF subgraph without an equity bridge or share price."""
    if wacc.debt_weight + wacc.equity_weight != Decimal("1"):
        raise OperatingProjectionError(
            "WACC_WEIGHTS_INVALID", "capital weights must sum to one"
        )
    cost_equity = wacc.risk_free_rate + wacc.beta * wacc.equity_risk_premium
    after_tax_debt = wacc.pre_tax_cost_of_debt * (Decimal("1") - wacc.tax_rate)
    wacc_value = wacc.equity_weight * cost_equity + wacc.debt_weight * after_tax_debt
    if wacc_value <= terminal_growth or wacc_value <= 0:
        raise OperatingProjectionError(
            "DISCOUNT_RATE_INVALID", "WACC must exceed terminal growth and zero"
        )
    operating_nodes = project_operating_nodes(
        forecast,
        tax_rate=wacc.tax_rate,
        historical_fact_ids=historical_fact_ids,
    )
    nodes = [
        _node(
            "cost_of_equity",
            "risk_free_rate + beta * equity_risk_premium",
            cost_equity,
            "rate",
            ("wacc",),
        ),
        _node(
            "after_tax_debt",
            "pre_tax_cost_of_debt * (1 - tax_rate)",
            after_tax_debt,
            "rate",
            ("wacc",),
        ),
        _node(
            "wacc",
            "equity_weight * cost_of_equity + debt_weight * after_tax_debt",
            wacc_value,
            "rate",
            ("cost_of_equity", "after_tax_debt"),
        ),
    ]
    nodes.append(operating_nodes[0])
    present_value = Decimal("0")
    last_fcff = Decimal("0")
    for index in range(1, len(forecast.revenue_growth) + 1):
        revenue_node, fcff_node = operating_nodes[2 * index - 1 : 2 * index + 1]
        fcff = fcff_node.value
        assert fcff is not None
        discounted = fcff / ((Decimal("1") + wacc_value) ** index)
        present_value += discounted
        last_fcff = fcff
        nodes.extend(
            (
                revenue_node,
                fcff_node,
                _node(
                    f"discounted_fcff_{index}",
                    "fcff / (1 + wacc)^period",
                    discounted,
                    "currency",
                    (f"fcff_{index}", "wacc"),
                ),
            )
        )
    terminal_value = (
        last_fcff * (Decimal("1") + terminal_growth) / (wacc_value - terminal_growth)
    )
    terminal_pv = terminal_value / (
        (Decimal("1") + wacc_value) ** len(forecast.revenue_growth)
    )
    nodes.append(
        _node(
            "discounted_terminal_value",
            "terminal_value / (1 + wacc)^forecast_periods",
            terminal_pv,
            "currency",
            ("terminal_value", "wacc"),
        )
    )
    enterprise = present_value + terminal_pv
    nodes.extend(
        (
            _node(
                "terminal_value",
                "last_fcff * (1 + terminal_growth) / (wacc - terminal_growth)",
                terminal_value,
                "currency",
                (f"fcff_{len(forecast.revenue_growth)}", "wacc"),
            ),
            _node(
                "enterprise_value",
                "sum(discounted_fcff) + discounted_terminal_value",
                enterprise,
                "currency",
                tuple(
                    [
                        f"discounted_fcff_{index}"
                        for index in range(1, len(forecast.revenue_growth) + 1)
                    ]
                    + ["discounted_terminal_value"]
                ),
            ),
        )
    )
    return tuple(nodes)
