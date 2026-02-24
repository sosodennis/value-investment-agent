from __future__ import annotations

from ..valuation_saas.tools import calculate_saas_valuation
from .schemas import DCFStandardParams


def calculate_dcf_standard_valuation(
    params: DCFStandardParams,
) -> dict[str, float | str | dict[str, object]]:
    # Transitional implementation:
    # reuse existing FCFF graph while keeping an explicit dcf_standard skill boundary.
    return calculate_saas_valuation(params)
