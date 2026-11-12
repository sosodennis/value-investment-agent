"""The shared, undiscounted operating stage of the #352 calculation graph."""

from decimal import Decimal

from .contracts import CalculationNodeV1, ForecastAssumptionsV1, TraceV1
from .numerical_policy import VALUATION_NUMERICAL_POLICY, using_valuation_context
from .policies import ModelSpecV1, initial_model_specs

OPERATING_FORMULA_GRAPH = "calculator-v2-fcff"


class OperatingProjectionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def resolve_operating_model(model_id: str, model_version: str) -> ModelSpecV1:
    """Bind a requested version to the specification of this executable graph."""
    spec = next(
        (item for item in initial_model_specs() if item.model_id == model_id), None
    )
    if spec is None:
        raise OperatingProjectionError(
            "MODEL_UNSUPPORTED", f"model {model_id} has no executable operating graph"
        )
    if model_version != spec.model_version:
        raise OperatingProjectionError(
            "MODEL_VERSION_UNSUPPORTED",
            f"model {model_id} requires executable version {spec.model_version}",
        )
    if (
        spec.formula_graph != OPERATING_FORMULA_GRAPH
        or spec.numerical_policy != VALUATION_NUMERICAL_POLICY
    ):
        raise OperatingProjectionError(
            "MODEL_SPEC_EXECUTION_MISMATCH",
            "model specification differs from the executable operating graph",
        )
    return spec


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
