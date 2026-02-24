from __future__ import annotations

from ..valuation_saas.tools import calculate_saas_valuation
from .schemas import DCFGrowthParams


def calculate_dcf_growth_valuation(
    params: DCFGrowthParams,
) -> dict[str, float | str | dict[str, object]]:
    # Transitional implementation:
    # reuse existing FCFF graph while keeping an explicit dcf_growth skill boundary.
    return calculate_saas_valuation(params)
