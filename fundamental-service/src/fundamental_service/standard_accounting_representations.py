"""Typed dispatch for standard source-bound accounting representations."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from .accounting_roles import AccountingRoleRules
from .arelle_parser import ParsedXbrlFactV1
from .award_disclosures import AWARD_DISCLOSURE_ROLES
from .award_disclosure_mapping import select_award_disclosure
from .common_stock_mapping import (
    COMMON_STOCK,
    common_stock_component_present,
    select_common_stock,
)
from .current_debt_mapping import (
    CURRENT_DEBT,
    current_debt_components_present,
    select_current_debt,
)
from .lease_liability_mapping import lease_liability_concept, select_lease_liability
from .original_issuer import OriginalIssuerEvidenceV1


class AccountingSelection(Protocol):
    @property
    def rules(self) -> AccountingRoleRules | None: ...
    @property
    def selected(self) -> tuple[ParsedXbrlFactV1, ...]: ...
    @property
    def reason_codes(self) -> tuple[str, ...]: ...


@dataclass(frozen=True)
class AccountingRepresentation:
    source_concept: str
    select: Callable[[OriginalIssuerEvidenceV1, str | None], AccountingSelection]
    direct_overlap_exclusion: bool = False


def standard_accounting_representation(
    original: OriginalIssuerEvidenceV1, normalized_field: str
) -> AccountingRepresentation | None:
    if normalized_field in AWARD_DISCLOSURE_ROLES:
        return AccountingRepresentation(
            f"classified:{normalized_field}",
            lambda evidence, security: select_award_disclosure(
                evidence, normalized_field, security_id=security
            ),
        )
    if (
        normalized_field == "current_interest_bearing_debt"
        and current_debt_components_present(original)
    ):
        return AccountingRepresentation(
            CURRENT_DEBT,
            lambda evidence, security: select_current_debt(
                evidence, security_id=security
            ),
        )
    if (
        normalized_field == "common_shares_outstanding"
        and common_stock_component_present(original)
    ):
        return AccountingRepresentation(
            COMMON_STOCK,
            lambda evidence, security: select_common_stock(
                evidence, security_id=security
            ),
        )
    lease = lease_liability_concept(original, normalized_field)
    if lease is not None:
        return AccountingRepresentation(
            lease,
            lambda evidence, security: select_lease_liability(
                evidence,
                normalized_field,
                security_id=security,
            ),
            direct_overlap_exclusion=True,
        )
    return None
