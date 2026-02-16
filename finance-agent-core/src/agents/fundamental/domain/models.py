from __future__ import annotations

from enum import Enum

from src.shared.cross_agent.domain.market_identity import CompanyProfile


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


__all__ = ["CompanyProfile", "ValuationModel"]
