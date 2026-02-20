from __future__ import annotations

from ..extractor import SearchType
from ..mapping import (
    BS_STATEMENT_TOKENS,
    CF_STATEMENT_TOKENS,
    IS_STATEMENT_TOKENS,
    USD_UNITS,
    FieldSpec,
    XbrlMappingRegistry,
)


def register_overrides(registry: XbrlMappingRegistry) -> None:
    # ---- Industry overrides ----
    # Financial Services: prioritize bank-specific cash definitions
    registry.register_override(
        "Financial Services",
        "cash_and_equivalents",
        FieldSpec(
            name="Cash & Cash Equivalents",
            configs=[
                SearchType.CONSOLIDATED(
                    "us-gaap:CashAndDueFromBanks",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:CashAndDueFromBanksAndInterestBearingDeposits",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:Cash",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:CashAndCashEquivalentsAtCarryingValue",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:CashAndCashEquivalents",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
            ],
        ),
    )

    # Real Estate (REIT): prioritize real-estate specific D&A
    registry.register_override(
        "Real Estate",
        "depreciation_and_amortization",
        FieldSpec(
            name="Depreciation & Amortization",
            configs=[
                SearchType.CONSOLIDATED(
                    "us-gaap:DepreciationAndAmortizationInRealEstate",
                    statement_types=IS_STATEMENT_TOKENS,
                    period_type="duration",
                    unit_whitelist=USD_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:DepreciationAndAmortization",
                    statement_types=IS_STATEMENT_TOKENS,
                    period_type="duration",
                    unit_whitelist=USD_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:DepreciationAndAmortization",
                    statement_types=CF_STATEMENT_TOKENS,
                    period_type="duration",
                    unit_whitelist=USD_UNITS,
                ),
            ],
        ),
    )
