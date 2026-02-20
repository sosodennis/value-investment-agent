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


def register_industrial_fields(registry: XbrlMappingRegistry) -> None:
    # ---- Industrial extension ----
    registry.register(
        "inventory",
        FieldSpec(
            name="Inventory",
            configs=[
                SearchType.CONSOLIDATED(
                    "us-gaap:InventoryNet",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:InventoryGross",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
            ],
        ),
    )

    registry.register(
        "accounts_receivable",
        FieldSpec(
            name="Accounts Receivable",
            configs=[
                SearchType.CONSOLIDATED(
                    "us-gaap:AccountsReceivableNetCurrent",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
            ],
        ),
    )

    registry.register(
        "cogs",
        FieldSpec(
            name="Cost of Goods Sold",
            configs=[
                SearchType.CONSOLIDATED(
                    "us-gaap:CostOfGoodsAndServicesSold",
                    statement_types=IS_STATEMENT_TOKENS,
                    period_type="duration",
                    unit_whitelist=USD_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:CostOfRevenue",
                    statement_types=IS_STATEMENT_TOKENS,
                    period_type="duration",
                    unit_whitelist=USD_UNITS,
                ),
            ],
        ),
    )

    registry.register(
        "rd_expense",
        FieldSpec(
            name="R&D Expense",
            configs=[
                SearchType.CONSOLIDATED(
                    "us-gaap:ResearchAndDevelopmentExpense",
                    statement_types=IS_STATEMENT_TOKENS,
                    period_type="duration",
                    unit_whitelist=USD_UNITS,
                ),
            ],
        ),
    )

    registry.register(
        "sga_expense",
        FieldSpec(
            name="SG&A Expense",
            configs=[
                SearchType.CONSOLIDATED(
                    "us-gaap:SellingGeneralAndAdministrativeExpense",
                    statement_types=IS_STATEMENT_TOKENS,
                    period_type="duration",
                    unit_whitelist=USD_UNITS,
                )
            ],
        ),
    )

    registry.register(
        "selling_expense",
        FieldSpec(
            name="Selling Expense",
            configs=[
                SearchType.CONSOLIDATED(
                    "us-gaap:SellingExpense",
                    statement_types=IS_STATEMENT_TOKENS,
                    period_type="duration",
                    unit_whitelist=USD_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:SellingAndMarketingExpense",
                    statement_types=IS_STATEMENT_TOKENS,
                    period_type="duration",
                    unit_whitelist=USD_UNITS,
                ),
            ],
        ),
    )

    registry.register(
        "ga_expense",
        FieldSpec(
            name="G&A Expense",
            configs=[
                SearchType.CONSOLIDATED(
                    "us-gaap:GeneralAndAdministrativeExpense",
                    statement_types=IS_STATEMENT_TOKENS,
                    period_type="duration",
                    unit_whitelist=USD_UNITS,
                ),
            ],
        ),
    )

    registry.register(
        "capex",
        FieldSpec(
            name="CapEx",
            configs=[
                SearchType.CONSOLIDATED(
                    "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment",
                    statement_types=CF_STATEMENT_TOKENS,
                    period_type="duration",
                    unit_whitelist=USD_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:PaymentsToAcquireProductiveAssets",
                    statement_types=CF_STATEMENT_TOKENS,
                    period_type="duration",
                    unit_whitelist=USD_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:PaymentsToAcquirePropertyAndEquipment",
                    statement_types=CF_STATEMENT_TOKENS,
                    period_type="duration",
                    unit_whitelist=USD_UNITS,
                ),
            ],
        ),
    )
