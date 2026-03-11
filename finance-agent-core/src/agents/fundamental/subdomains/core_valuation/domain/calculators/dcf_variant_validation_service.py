from __future__ import annotations

from .dcf_variant_contracts import DcfVariantParams


def coerce_float_list(value: float | list[float], *, field_name: str) -> list[float]:
    if isinstance(value, list):
        return [float(item) for item in value]
    raise ValueError(f"{field_name} must be a list[float]")


def validate_dcf_variant_projection_lengths(params: DcfVariantParams) -> str | None:
    years = len(params.growth_rates)
    if years == 0:
        return "growth_rates cannot be empty"

    series_lengths = {
        "operating_margins": len(params.operating_margins),
        "da_rates": len(params.da_rates),
        "capex_rates": len(params.capex_rates),
        "wc_rates": len(params.wc_rates),
        "sbc_rates": len(params.sbc_rates),
    }
    for name, length in series_lengths.items():
        if length != years:
            return f"{name} length must equal growth_rates length ({years})"

    if params.shares_outstanding <= 0:
        return "shares_outstanding must be positive"
    if params.wacc <= 0:
        return "wacc must be positive"
    if params.terminal_growth >= params.wacc:
        return "terminal_growth must be lower than wacc"
    return None
