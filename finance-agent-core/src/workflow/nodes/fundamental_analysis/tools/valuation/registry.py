from .skills.auditor.rules import (
    audit_bank_params,
    audit_ev_ebitda_params,
    audit_ev_revenue_params,
    audit_eva_params,
    audit_reit_ffo_params,
    audit_residual_income_params,
    audit_saas_params,
)
from .skills.valuation_bank.schemas import BankParams
from .skills.valuation_bank.tools import calculate_bank_valuation
from .skills.valuation_ev_ebitda.schemas import EVEbitdaParams
from .skills.valuation_ev_ebitda.tools import calculate_ev_ebitda_valuation
from .skills.valuation_ev_revenue.schemas import EVRevenueParams
from .skills.valuation_ev_revenue.tools import calculate_ev_revenue_valuation
from .skills.valuation_eva.schemas import EvaParams
from .skills.valuation_eva.tools import calculate_eva_valuation
from .skills.valuation_reit_ffo.schemas import ReitFfoParams
from .skills.valuation_reit_ffo.tools import calculate_reit_ffo_valuation
from .skills.valuation_residual_income.schemas import ResidualIncomeParams
from .skills.valuation_residual_income.tools import (
    calculate_residual_income_valuation,
)
from .skills.valuation_saas.schemas import SaaSParams
from .skills.valuation_saas.tools import calculate_saas_valuation


class SkillRegistry:
    SKILLS = {
        "saas": {
            "schema": SaaSParams,
            "calculator": calculate_saas_valuation,
            "auditor": audit_saas_params,
        },
        "bank": {
            "schema": BankParams,
            "calculator": calculate_bank_valuation,
            "auditor": audit_bank_params,
        },
        "ev_revenue": {
            "schema": EVRevenueParams,
            "calculator": calculate_ev_revenue_valuation,
            "auditor": audit_ev_revenue_params,
        },
        "ev_ebitda": {
            "schema": EVEbitdaParams,
            "calculator": calculate_ev_ebitda_valuation,
            "auditor": audit_ev_ebitda_params,
        },
        "reit_ffo": {
            "schema": ReitFfoParams,
            "calculator": calculate_reit_ffo_valuation,
            "auditor": audit_reit_ffo_params,
        },
        "residual_income": {
            "schema": ResidualIncomeParams,
            "calculator": calculate_residual_income_valuation,
            "auditor": audit_residual_income_params,
        },
        "eva": {
            "schema": EvaParams,
            "calculator": calculate_eva_valuation,
            "auditor": audit_eva_params,
        },
    }

    @classmethod
    def get_skill(cls, name: str):
        return cls.SKILLS.get(name)
