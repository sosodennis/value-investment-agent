from __future__ import annotations

from enum import Enum


class CalculatorModelType(str, Enum):
    DCF_STANDARD = "dcf_standard"
    DCF_GROWTH = "dcf_growth"
    SAAS = "saas"
    BANK = "bank"
    REIT_FFO = "reit_ffo"
    EV_REVENUE = "ev_revenue"
    EV_EBITDA = "ev_ebitda"
    RESIDUAL_INCOME = "residual_income"
    EVA = "eva"


MODEL_TYPE_BY_SELECTION: dict[str, CalculatorModelType] = {
    "dcf_growth": CalculatorModelType.DCF_GROWTH,
    "dcf_standard": CalculatorModelType.DCF_STANDARD,
    "ddm": CalculatorModelType.BANK,
    "ffo": CalculatorModelType.REIT_FFO,
    "ev_revenue": CalculatorModelType.EV_REVENUE,
    "ev_ebitda": CalculatorModelType.EV_EBITDA,
    "residual_income": CalculatorModelType.RESIDUAL_INCOME,
    "eva": CalculatorModelType.EVA,
}
