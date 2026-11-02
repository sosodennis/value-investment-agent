from __future__ import annotations

from ..mapping import XbrlMappingRegistry
from .base import register_base_fields
from .financial_services import register_financial_services_fields
from .industrial import register_industrial_fields
from .overrides import register_overrides
from .real_estate import register_real_estate_fields


def register_all_mappings(registry: XbrlMappingRegistry) -> None:
    register_base_fields(registry)
    register_industrial_fields(registry)
    register_financial_services_fields(registry)
    register_real_estate_fields(registry)
    register_overrides(registry)
