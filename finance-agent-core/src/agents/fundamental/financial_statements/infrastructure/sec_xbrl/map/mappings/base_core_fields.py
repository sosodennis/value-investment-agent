from __future__ import annotations

from ...extract.extractor import SearchType
from ..mapping import (
    BS_STATEMENT_TOKENS,
    IS_STATEMENT_TOKENS,
    SHARES_UNITS,
    USD_UNITS,
    FieldSpec,
    XbrlMappingRegistry,
)


def register_base_core_fields(registry: XbrlMappingRegistry) -> None:
    registry.register(
        "shares_outstanding",
        FieldSpec(
            name="Shares Outstanding",
            configs=[
                SearchType.CONSOLIDATED(
                    "dei:EntityCommonStockSharesOutstanding",
                    unit_whitelist=SHARES_UNITS,
                    respect_anchor_date=False,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:CommonStockSharesOutstanding",
                    unit_whitelist=SHARES_UNITS,
                    respect_anchor_date=False,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:WeightedAverageNumberOfSharesOutstandingBasic",
                    statement_types=IS_STATEMENT_TOKENS,
                    period_type="duration",
                    unit_whitelist=SHARES_UNITS,
                    respect_anchor_date=False,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding",
                    statement_types=IS_STATEMENT_TOKENS,
                    period_type="duration",
                    unit_whitelist=SHARES_UNITS,
                    respect_anchor_date=False,
                ),
            ],
        ),
    )

    registry.register(
        "weighted_average_shares_basic",
        FieldSpec(
            name="Weighted Average Shares Outstanding (Basic)",
            configs=[
                SearchType.CONSOLIDATED(
                    "us-gaap:WeightedAverageNumberOfSharesOutstandingBasic",
                    statement_types=IS_STATEMENT_TOKENS,
                    period_type="duration",
                    unit_whitelist=SHARES_UNITS,
                    respect_anchor_date=False,
                ),
            ],
        ),
    )

    registry.register(
        "weighted_average_shares_diluted",
        FieldSpec(
            name="Weighted Average Shares Outstanding (Diluted)",
            configs=[
                SearchType.CONSOLIDATED(
                    "us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding",
                    statement_types=IS_STATEMENT_TOKENS,
                    period_type="duration",
                    unit_whitelist=SHARES_UNITS,
                    respect_anchor_date=False,
                ),
            ],
        ),
    )

    registry.register(
        "total_assets",
        FieldSpec(
            name="Total Assets",
            configs=[
                SearchType.CONSOLIDATED(
                    "us-gaap:Assets",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
            ],
        ),
    )

    registry.register(
        "total_liabilities",
        FieldSpec(
            name="Total Liabilities",
            configs=[
                SearchType.CONSOLIDATED(
                    "us-gaap:Liabilities",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
            ],
        ),
    )

    registry.register(
        "total_equity",
        FieldSpec(
            name="Total Equity",
            configs=[
                SearchType.CONSOLIDATED(
                    "us-gaap:StockholdersEquity",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
            ],
        ),
    )

    registry.register(
        "cash_and_equivalents",
        FieldSpec(
            name="Cash & Cash Equivalents",
            configs=[
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
                SearchType.CONSOLIDATED(
                    "us-gaap:CashAndCashEquivalentsRestrictedCashAndCashEquivalents",
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
                    "us-gaap:CashEquivalentsAtCarryingValue",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
            ],
        ),
    )

    registry.register(
        "current_assets",
        FieldSpec(
            name="Current Assets",
            configs=[
                SearchType.CONSOLIDATED(
                    "us-gaap:AssetsCurrent",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
            ],
        ),
    )

    registry.register(
        "current_liabilities",
        FieldSpec(
            name="Current Liabilities",
            configs=[
                SearchType.CONSOLIDATED(
                    "us-gaap:LiabilitiesCurrent",
                    statement_types=BS_STATEMENT_TOKENS,
                    period_type="instant",
                    unit_whitelist=USD_UNITS,
                ),
            ],
        ),
    )
