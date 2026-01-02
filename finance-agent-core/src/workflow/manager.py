from ..skills.auditor.rules import audit_bank_params, audit_saas_params
from ..skills.valuation_bank.schemas import BankParams
from ..skills.valuation_bank.tools import calculate_bank_valuation
from ..skills.valuation_saas.schemas import SaaSParams
from ..skills.valuation_saas.tools import calculate_saas_valuation


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
    }

    @classmethod
    def get_skill(cls, name: str):
        return cls.SKILLS.get(name)
