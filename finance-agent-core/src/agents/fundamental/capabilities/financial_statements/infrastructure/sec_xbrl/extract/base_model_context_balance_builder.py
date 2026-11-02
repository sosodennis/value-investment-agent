from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, TypeVar

from src.agents.fundamental.domain.shared.contracts.traceable import (
    ManualProvenance,
    TraceableField,
    XBRLProvenance,
)

from .extractor import SearchConfig, SECReportExtractor

T = TypeVar("T")
BuildConfigFn = Callable[
    [str, list[str] | None, str | None, list[str] | None], SearchConfig
]
ResolveConfigsFn = Callable[[str], list[SearchConfig]]


class ExtractFieldFn(Protocol):
    def __call__(
        self,
        extractor: SECReportExtractor,
        configs: list[SearchConfig],
        name: str,
        target_type: type[T],
    ) -> TraceableField[T]: ...


@dataclass(slots=True)
class ContextBalanceFields:
    ticker: TraceableField[str]
    cik: TraceableField[str]
    company_name: TraceableField[str]
    sic_code: TraceableField[str]
    fiscal_year: TraceableField[str]
    fiscal_period: TraceableField[str]
    shares_outstanding: TraceableField[float]
    weighted_average_shares_basic: TraceableField[float]
    weighted_average_shares_diluted: TraceableField[float]
    total_assets: TraceableField[float]
    total_liabilities: TraceableField[float]
    total_equity: TraceableField[float]
    cash_and_equivalents: TraceableField[float]
    current_assets: TraceableField[float]
    current_liabilities: TraceableField[float]


def build_context_balance_fields(
    *,
    extractor: SECReportExtractor,
    resolve_configs: ResolveConfigsFn,
    build_config: BuildConfigFn,
    extract_field_fn: ExtractFieldFn,
    bs_statement_tokens: list[str],
    is_statement_tokens: list[str],
    usd_units: list[str],
    shares_units: list[str],
) -> ContextBalanceFields:
    ticker_val = extractor.ticker
    cik_results = extractor.search(build_config("dei:EntityCentralIndexKey"))
    cik_val = cik_results[0].value if cik_results else None

    name_results = extractor.search(build_config("dei:EntityRegistrantName"))
    name_val = name_results[0].value if name_results else None

    tf_ticker = TraceableField(
        name="Ticker",
        value=ticker_val,
        provenance=ManualProvenance(description="Input Ticker"),
    )
    tf_cik = TraceableField(
        name="CIK",
        value=cik_val,
        provenance=XBRLProvenance(concept="dei:EntityCentralIndexKey", period="Current")
        if cik_val
        else ManualProvenance(description="Missing"),
    )
    tf_name = TraceableField(
        name="Company Name",
        value=name_val,
        provenance=XBRLProvenance(concept="dei:EntityRegistrantName", period="Current")
        if name_val
        else ManualProvenance(description="Missing"),
    )
    tf_sic = TraceableField(
        name="SIC Code",
        value=str(extractor.sic_code()),
        provenance=ManualProvenance(description="From Company Profile"),
    )

    tf_shares = extract_field_fn(
        extractor,
        resolve_configs("shares_outstanding")
        or [
            build_config(
                "dei:EntityCommonStockSharesOutstanding",
                unit_whitelist=shares_units,
            ),
            build_config(
                "us-gaap:CommonStockSharesOutstanding", unit_whitelist=shares_units
            ),
        ],
        "Shares Outstanding",
        target_type=float,
    )
    tf_weighted_average_shares_basic = extract_field_fn(
        extractor,
        resolve_configs("weighted_average_shares_basic")
        or [
            build_config(
                "us-gaap:WeightedAverageNumberOfSharesOutstandingBasic",
                is_statement_tokens,
                "duration",
                shares_units,
            )
        ],
        "Weighted Average Shares Outstanding (Basic)",
        target_type=float,
    )
    tf_weighted_average_shares_diluted = extract_field_fn(
        extractor,
        resolve_configs("weighted_average_shares_diluted")
        or [
            build_config(
                "us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding",
                is_statement_tokens,
                "duration",
                shares_units,
            )
        ],
        "Weighted Average Shares Outstanding (Diluted)",
        target_type=float,
    )

    tf_fiscal_year = extract_field_fn(
        extractor,
        [build_config("dei:DocumentFiscalYearFocus")],
        "Fiscal Year",
        target_type=str,
    )
    tf_fiscal_period = extract_field_fn(
        extractor,
        [build_config("dei:DocumentFiscalPeriodFocus")],
        "Fiscal Period",
        target_type=str,
    )

    tf_assets = extract_field_fn(
        extractor,
        resolve_configs("total_assets")
        or [build_config("us-gaap:Assets", bs_statement_tokens, "instant", usd_units)],
        "Total Assets",
        target_type=float,
    )
    tf_liabilities = extract_field_fn(
        extractor,
        resolve_configs("total_liabilities")
        or [
            build_config(
                "us-gaap:Liabilities", bs_statement_tokens, "instant", usd_units
            )
        ],
        "Total Liabilities",
        target_type=float,
    )
    tf_equity = extract_field_fn(
        extractor,
        resolve_configs("total_equity")
        or [
            build_config(
                "us-gaap:StockholdersEquity",
                bs_statement_tokens,
                "instant",
                usd_units,
            ),
            build_config(
                "us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                bs_statement_tokens,
                "instant",
                usd_units,
            ),
        ],
        "Total Equity",
        target_type=float,
    )
    tf_cash = extract_field_fn(
        extractor,
        resolve_configs("cash_and_equivalents")
        or [
            build_config(
                "us-gaap:CashAndCashEquivalentsAtCarryingValue",
                bs_statement_tokens,
                "instant",
                usd_units,
            ),
            build_config(
                "us-gaap:CashAndCashEquivalents",
                bs_statement_tokens,
                "instant",
                usd_units,
            ),
            build_config(
                "us-gaap:CashAndCashEquivalentsRestrictedCashAndCashEquivalents",
                bs_statement_tokens,
                "instant",
                usd_units,
            ),
            build_config("us-gaap:Cash", bs_statement_tokens, "instant", usd_units),
            build_config(
                "us-gaap:CashAndDueFromBanks",
                bs_statement_tokens,
                "instant",
                usd_units,
            ),
            build_config(
                "us-gaap:CashAndDueFromBanksAndInterestBearingDeposits",
                bs_statement_tokens,
                "instant",
                usd_units,
            ),
            build_config(
                "us-gaap:CashEquivalentsAtCarryingValue",
                bs_statement_tokens,
                "instant",
                usd_units,
            ),
        ],
        "Cash & Cash Equivalents",
        target_type=float,
    )
    tf_current_assets = extract_field_fn(
        extractor,
        resolve_configs("current_assets")
        or [
            build_config(
                "us-gaap:AssetsCurrent", bs_statement_tokens, "instant", usd_units
            )
        ],
        "Current Assets",
        target_type=float,
    )
    tf_current_liabilities = extract_field_fn(
        extractor,
        resolve_configs("current_liabilities")
        or [
            build_config(
                "us-gaap:LiabilitiesCurrent",
                bs_statement_tokens,
                "instant",
                usd_units,
            )
        ],
        "Current Liabilities",
        target_type=float,
    )

    return ContextBalanceFields(
        ticker=tf_ticker,
        cik=tf_cik,
        company_name=tf_name,
        sic_code=tf_sic,
        fiscal_year=tf_fiscal_year,
        fiscal_period=tf_fiscal_period,
        shares_outstanding=tf_shares,
        weighted_average_shares_basic=tf_weighted_average_shares_basic,
        weighted_average_shares_diluted=tf_weighted_average_shares_diluted,
        total_assets=tf_assets,
        total_liabilities=tf_liabilities,
        total_equity=tf_equity,
        cash_and_equivalents=tf_cash,
        current_assets=tf_current_assets,
        current_liabilities=tf_current_liabilities,
    )
