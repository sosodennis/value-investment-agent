from __future__ import annotations

from enum import Enum


class CalculatorModelType(str, Enum):
    SAAS = "saas"
    BANK = "bank"
    REIT_FFO = "reit_ffo"
    EV_REVENUE = "ev_revenue"
    EV_EBITDA = "ev_ebitda"
    RESIDUAL_INCOME = "residual_income"
    EVA = "eva"


MODEL_TYPE_BY_SELECTION: dict[str, CalculatorModelType] = {
    "dcf_growth": CalculatorModelType.SAAS,
    "dcf_standard": CalculatorModelType.SAAS,
    "ddm": CalculatorModelType.BANK,
    "ffo": CalculatorModelType.REIT_FFO,
    "ev_revenue": CalculatorModelType.EV_REVENUE,
    "ev_ebitda": CalculatorModelType.EV_EBITDA,
    "residual_income": CalculatorModelType.RESIDUAL_INCOME,
    "eva": CalculatorModelType.EVA,
}
