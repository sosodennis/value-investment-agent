from ..models.ev_ebitda.contracts import EVEbitdaParams
from .ev_multiple_variant_calculator import (
    calculate_ev_multiple_variant_valuation,
)


def calculate_ev_ebitda_valuation(
    params: EVEbitdaParams,
) -> dict[str, float | str | dict[str, object]]:
    return calculate_ev_multiple_variant_valuation(
        params,
        target_metric=params.ebitda,
        multiple=params.ev_ebitda_multiple,
    )
