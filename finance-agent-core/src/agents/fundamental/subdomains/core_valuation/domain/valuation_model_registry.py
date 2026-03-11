from .calculators.bank_calculator import calculate_bank_valuation
from .calculators.dcf_growth_calculator import calculate_dcf_growth_valuation
from .calculators.dcf_standard_calculator import calculate_dcf_standard_valuation
from .calculators.ev_ebitda_calculator import calculate_ev_ebitda_valuation
from .calculators.ev_revenue_calculator import calculate_ev_revenue_valuation
from .calculators.eva_calculator import calculate_eva_valuation
from .calculators.reit_ffo_calculator import calculate_reit_ffo_valuation
from .calculators.residual_income_calculator import (
    calculate_residual_income_valuation,
)
from .calculators.saas_calculator import calculate_saas_valuation
from .models.bank.contracts import BankParams
from .models.dcf_growth.contracts import DCFGrowthParams
from .models.dcf_standard.contracts import DCFStandardParams
from .models.ev_ebitda.contracts import EVEbitdaParams
from .models.ev_revenue.contracts import EVRevenueParams
from .models.eva.contracts import EvaParams
from .models.reit_ffo.contracts import ReitFfoParams
from .models.residual_income.contracts import ResidualIncomeParams
from .models.saas.contracts import SaaSParams
from .policies.valuation_audit_policy import (
    audit_bank_params,
    audit_dcf_growth_params,
    audit_dcf_standard_params,
    audit_ev_ebitda_params,
    audit_ev_revenue_params,
    audit_eva_params,
    audit_reit_ffo_params,
    audit_residual_income_params,
    audit_saas_params,
)


class ValuationModelRegistry:
    MODEL_RUNTIMES = {
        "dcf_standard": {
            "schema": DCFStandardParams,
            "calculator": calculate_dcf_standard_valuation,
            "auditor": audit_dcf_standard_params,
        },
        "dcf_growth": {
            "schema": DCFGrowthParams,
            "calculator": calculate_dcf_growth_valuation,
            "auditor": audit_dcf_growth_params,
        },
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
    def get_model_runtime(cls, name: str):
        return cls.MODEL_RUNTIMES.get(name)
