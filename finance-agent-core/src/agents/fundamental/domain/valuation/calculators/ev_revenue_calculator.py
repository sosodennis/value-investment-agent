from ..models.ev_revenue.contracts import EVRevenueParams
from .ev_multiple_variant_calculator import (
    calculate_ev_multiple_variant_valuation,
)


def calculate_ev_revenue_valuation(
    params: EVRevenueParams,
) -> dict[str, float | str | dict[str, object]]:
    return calculate_ev_multiple_variant_valuation(
        params,
        target_metric=params.revenue,
        multiple=params.ev_revenue_multiple,
    )
