"""Scoped aggregate disclosures; never instrument inventory or exact dilution."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re
from typing import Final

from .arelle_parser import ParsedXbrlFactV1

AWARD_DISCLOSURE_SCOPE: Final = "restricted_stock_nonvested_aggregate"
AWARD_DISCLOSURE_POLICY = "standard-restricted-stock-aggregate-disclosures-v1"
AWARD_DISCLOSURE_DIMENSIONS = (
    ("us-gaap:AwardTypeAxis", "us-gaap:RestrictedStockMember"),
)


@dataclass(frozen=True)
class AwardDisclosureRole:
    concept: str
    unit: str
    currency: str | None


AWARD_DISCLOSURE_ROLES = {
    "restricted_stock_nonvested_aggregate_quantity": AwardDisclosureRole(
        "us-gaap:ShareBasedCompensationArrangementByShareBasedPaymentAwardEquityInstrumentsOtherThanOptionsNonvestedNumber",
        "xbrli:shares",
        None,
    ),
    "restricted_stock_nonvested_aggregate_unrecognized_compensation": AwardDisclosureRole(
        "us-gaap:EmployeeServiceShareBasedCompensationNonvestedAwardsTotalCompensationCostNotYetRecognized",
        "iso4217:USD",
        "USD",
    ),
}
AWARD_DISCLOSURE_FIELDS = tuple(AWARD_DISCLOSURE_ROLES)


def matches_award_disclosure(
    fact: ParsedXbrlFactV1, *, role: str, issuer_id: str
) -> bool:
    """Recognize only the certified 2025 standard award-type disclosure scope.

    RestrictedStockMember may include performance conditions. Neither quantity
    nor aggregate cost establishes settlement, issued shares or completeness.
    """
    definition = AWARD_DISCLOSURE_ROLES.get(role)
    try:
        value = Decimal(fact.value)
    except InvalidOperation:
        return False
    return (
        definition is not None
        and fact.concept == definition.concept
        and fact.unit == definition.unit
        and fact.namespace_uri == "http://fasb.org/us-gaap/2025"
        and fact.is_numeric
        and value.is_finite()
        and value >= 0
        and fact.dimensions == AWARD_DISCLOSURE_DIMENSIONS
        and fact.dimension_namespace_uris
        == (
            (
                "us-gaap:AwardTypeAxis",
                "http://fasb.org/us-gaap/2025",
                "http://fasb.org/us-gaap/2025",
            ),
        )
        and fact.consolidation_scope == "segmented"
        and fact.security_scope == "segmented"
        and fact.entity_scheme == "http://www.sec.gov/CIK"
        and re.fullmatch(r"[0-9]{1,10}", fact.entity_identifier or "") is not None
        and (fact.entity_identifier or "").lstrip("0") == issuer_id.lstrip("0")
        and fact.instant is not None
        and fact.period_start is None
        and fact.period_end is None
        and re.fullmatch(r"-?[0-9]+", fact.decimals or "") is not None
    )
