from __future__ import annotations

from ..mapping import XbrlMappingRegistry
from .base_cash_flow_fields import register_base_cash_flow_fields
from .base_core_fields import register_base_core_fields
from .base_debt_fields import register_base_debt_fields
from .base_income_fields import register_base_income_fields


def register_base_fields(registry: XbrlMappingRegistry) -> None:
    register_base_core_fields(registry)
    register_base_debt_fields(registry)
    register_base_income_fields(registry)
    register_base_cash_flow_fields(registry)
