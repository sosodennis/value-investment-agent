from __future__ import annotations

from ..extractor import SearchType
from ..mapping import (
    BS_STATEMENT_TOKENS,
    IS_STATEMENT_TOKENS,
    USD_UNITS,
    FieldSpec,
    XbrlMappingRegistry,
)


def register_real_estate_fields(registry: XbrlMappingRegistry) -> None:
    # ---- Real estate extension ----
    registry.register(
        "real_estate_assets",
        FieldSpec(
            name="Real Estate Assets (at cost)",
            configs=[
                SearchType.CONSOLIDATED(
                    "us-gaap:RealEstateInvestmentPropertyNet",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
            ],
        ),
    )

    registry.register(
        "accumulated_depreciation",
        FieldSpec(
            name="Accumulated Depreciation",
            configs=[
                SearchType.CONSOLIDATED(
                    "us-gaap:RealEstateInvestmentPropertyAccumulatedDepreciation",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
            ],
        ),
    )

    registry.register(
        "real_estate_dep_amort",
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
                    "us-gaap:DepreciationDepletionAndAmortization",
                    statement_types=IS_STATEMENT_TOKENS,
                    period_type="duration",
                    unit_whitelist=USD_UNITS,
                ),
            ],
        ),
    )

    registry.register(
        "gain_on_sale",
        FieldSpec(
            name="Gain on Sale of Properties",
            configs=[
                SearchType.CONSOLIDATED(
                    "us-gaap:GainLossOnSaleOfRealEstateInvestmentProperty",
                    statement_types=IS_STATEMENT_TOKENS,
                    period_type="duration",
                    unit_whitelist=USD_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:GainLossOnSaleOfProperties",
                    statement_types=IS_STATEMENT_TOKENS,
                    period_type="duration",
                    unit_whitelist=USD_UNITS,
                ),
            ],
        ),
    )
