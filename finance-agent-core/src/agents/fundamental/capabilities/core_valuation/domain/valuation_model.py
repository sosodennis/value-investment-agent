from __future__ import annotations

from enum import Enum


class ValuationModel(str, Enum):
    """Available valuation models based on industry characteristics."""

    DCF_GROWTH = "dcf_growth"
    DCF_STANDARD = "dcf_standard"
    DDM = "ddm"
    FFO = "ffo"
    EV_REVENUE = "ev_revenue"
    EV_EBITDA = "ev_ebitda"
    RESIDUAL_INCOME = "residual_income"
    EVA = "eva"


__all__ = ["ValuationModel"]
