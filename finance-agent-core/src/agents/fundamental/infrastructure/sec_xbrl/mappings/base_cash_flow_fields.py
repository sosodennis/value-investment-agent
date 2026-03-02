from __future__ import annotations

from ..extractor import SearchType
from ..mapping import CF_STATEMENT_TOKENS, USD_UNITS, FieldSpec, XbrlMappingRegistry


def register_base_cash_flow_fields(registry: XbrlMappingRegistry) -> None:
    registry.register(
        "operating_cash_flow",
        FieldSpec(
            name="Operating Cash Flow",
            configs=[
                SearchType.CONSOLIDATED(
                    "us-gaap:NetCashProvidedByUsedInOperatingActivities",
                    statement_types=CF_STATEMENT_TOKENS,
                    period_type="duration",
                    unit_whitelist=USD_UNITS,
                ),
            ],
        ),
    )

    registry.register(
        "dividends_paid",
        FieldSpec(
            name="Dividends Paid",
            configs=[
                SearchType.CONSOLIDATED(
                    "us-gaap:PaymentsOfDividends",
                    statement_types=CF_STATEMENT_TOKENS,
                    period_type="duration",
                    unit_whitelist=USD_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:PaymentsOfDividendsCommonStock",
                    statement_types=CF_STATEMENT_TOKENS,
                    period_type="duration",
                    unit_whitelist=USD_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:DividendsCommonStockCash",
                    statement_types=CF_STATEMENT_TOKENS,
                    period_type="duration",
                    unit_whitelist=USD_UNITS,
                ),
                SearchType.CONSOLIDATED(
                    "us-gaap:DividendsPaid",
                    statement_types=CF_STATEMENT_TOKENS,
                    period_type="duration",
                    unit_whitelist=USD_UNITS,
                ),
            ],
        ),
    )
