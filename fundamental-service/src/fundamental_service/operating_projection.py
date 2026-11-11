"""The shared, undiscounted operating stage of the #352 calculation graph."""

from decimal import Decimal

from .contracts import CalculationNodeV1, ForecastAssumptionsV1, TraceV1
from .numerical_policy import using_valuation_context


class OperatingProjectionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@using_valuation_context
def project_operating_nodes(
    forecast: ForecastAssumptionsV1,
    *,
    tax_rate: Decimal,
    historical_fact_ids: tuple[str, ...],
) -> tuple[CalculationNodeV1, ...]:
    """Evaluate operating targets without requiring capital or discount inputs."""

    if forecast.base_revenue is None or forecast.base_revenue <= 0:
        raise OperatingProjectionError(
            "BASE_REVENUE_MISSING", "a positive base revenue fact is required"
        )
    if not forecast.revenue_growth or not (
        len(forecast.revenue_growth)
        == len(forecast.operating_margin)
        == len(forecast.reinvestment_rate)
    ):
        raise OperatingProjectionError(
            "FORECAST_INVALID", "forecast arrays must be non-empty and equal length"
        )

    def node(
        node_id: str, formula: str, value: Decimal, inputs: tuple[str, ...]
    ) -> CalculationNodeV1:
        return CalculationNodeV1(
            node_id=node_id,
            formula=formula,
            inputs=inputs,
            value=value,
            unit="currency",
            trace=TraceV1(expression=formula, inputs=inputs),
        )

    revenue = forecast.base_revenue
    nodes = [
        node("base_revenue", "historical revenue fact", revenue, historical_fact_ids)
    ]
    for index, (growth, margin, reinvestment) in enumerate(
        zip(
            forecast.revenue_growth,
            forecast.operating_margin,
            forecast.reinvestment_rate,
            strict=True,
        ),
        start=1,
    ):
        revenue *= Decimal("1") + growth
        fcff = (
            revenue * margin * (Decimal("1") - tax_rate) * (Decimal("1") - reinvestment)
        )
        nodes.extend(
            (
                node(
                    f"revenue_{index}",
                    "prior_revenue * (1 + growth)",
                    revenue,
                    (f"revenue_{index - 1}" if index > 1 else "base_revenue",),
                ),
                node(
                    f"fcff_{index}",
                    "revenue * margin * (1 - tax_rate) * (1 - reinvestment_rate)",
                    fcff,
                    (f"revenue_{index}",),
                ),
            )
        )
    return tuple(nodes)
