from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from src.agents.fundamental.shared.contracts.traceable import TraceableField

from .extractor import SearchConfig, SearchType, SECReportExtractor
from .report_contracts import IndustrialExtension

T = TypeVar("T")


def build_industrial_extension(
    *,
    extractor: SECReportExtractor,
    resolve_configs_fn: Callable[..., list[SearchConfig]],
    extract_field_fn: Callable[
        [SECReportExtractor, list[SearchConfig], str, type[T]], TraceableField[T]
    ],
    sum_fields_fn: Callable[[str, list[TraceableField[float]]], TraceableField[float]],
    bs_statement_tokens: list[str],
    is_statement_tokens: list[str],
    cf_statement_tokens: list[str],
    usd_units: list[str],
) -> IndustrialExtension:
    def C(
        regex: str,
        statement_types: list[str] | None = None,
        period_type: str | None = None,
        unit_whitelist: list[str] | None = None,
    ) -> SearchConfig:
        return SearchType.CONSOLIDATED(
            regex,
            statement_types=statement_types,
            period_type=period_type,
            unit_whitelist=unit_whitelist,
        )

    def R(field_key: str) -> list[SearchConfig]:
        return resolve_configs_fn(
            field_key=field_key,
            industry="Industrial",
            issuer=extractor.ticker,
        )

    tf_inventory = extract_field_fn(
        extractor,
        R("inventory")
        or [
            C("us-gaap:InventoryNet", bs_statement_tokens, "instant", usd_units),
            C("us-gaap:InventoryGross", bs_statement_tokens, "instant", usd_units),
        ],
        "Inventory",
        float,
    )

    tf_ar = extract_field_fn(
        extractor,
        R("accounts_receivable")
        or [
            C(
                "us-gaap:AccountsReceivableNetCurrent",
                bs_statement_tokens,
                "instant",
                usd_units,
            )
        ],
        "Accounts Receivable",
        float,
    )

    tf_cogs = extract_field_fn(
        extractor,
        R("cogs")
        or [
            C(
                "us-gaap:CostOfGoodsAndServicesSold",
                is_statement_tokens,
                "duration",
                usd_units,
            ),
            C("us-gaap:CostOfRevenue", is_statement_tokens, "duration", usd_units),
        ],
        "Cost of Goods Sold (COGS)",
        float,
    )

    tf_rd = extract_field_fn(
        extractor,
        R("rd_expense")
        or [
            C(
                "us-gaap:ResearchAndDevelopmentExpense",
                is_statement_tokens,
                "duration",
                usd_units,
            )
        ],
        "R&D Expense",
        float,
    )

    tf_selling = extract_field_fn(
        extractor,
        R("selling_expense")
        or [
            C("us-gaap:SellingExpense", is_statement_tokens, "duration", usd_units),
            C(
                "us-gaap:SellingAndMarketingExpense",
                is_statement_tokens,
                "duration",
                usd_units,
            ),
        ],
        "Selling Expense",
        float,
    )
    tf_ga = extract_field_fn(
        extractor,
        R("ga_expense")
        or [
            C(
                "us-gaap:GeneralAndAdministrativeExpense",
                is_statement_tokens,
                "duration",
                usd_units,
            )
        ],
        "G&A Expense",
        float,
    )

    tf_sga_aggregate = extract_field_fn(
        extractor,
        R("sga_expense")
        or [
            C(
                "us-gaap:SellingGeneralAndAdministrativeExpense",
                is_statement_tokens,
                "duration",
                usd_units,
            )
        ],
        "SG&A Expense",
        float,
    )

    if tf_sga_aggregate.value is not None:
        tf_sga = tf_sga_aggregate
    else:
        tf_sga = sum_fields_fn("SG&A Expense (Calculated)", [tf_selling, tf_ga])

    tf_capex = extract_field_fn(
        extractor,
        R("capex")
        or [
            C(
                "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment",
                cf_statement_tokens,
                "duration",
                usd_units,
            )
        ],
        "Capital Expenditures (CapEx)",
        float,
    )

    return IndustrialExtension(
        inventory=tf_inventory,
        accounts_receivable=tf_ar,
        cogs=tf_cogs,
        rd_expense=tf_rd,
        sga_expense=tf_sga,
        selling_expense=tf_selling,
        ga_expense=tf_ga,
        capex=tf_capex,
    )
