from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from src.agents.fundamental.shared.contracts.traceable import TraceableField

from .value_extraction_common_service import (
    MarketFloatOp,
    SharesSourceResolver,
    ValueOrMissingOp,
    extract_current_price,
    extract_required_values,
    resolve_filing_shares_source,
)


@dataclass(frozen=True)
class CapitalStructureValues:
    shares_outstanding: float | None
    cash: float | None
    total_debt: float | None
    preferred_stock: float | None


@dataclass(frozen=True)
class FilingCapitalStructureMarketValues:
    shares_outstanding: float | None
    cash: float | None
    total_debt: float | None
    preferred_stock: float | None
    current_price: float | None
    shares_source: str


def extract_capital_structure_values(
    *,
    value_or_missing: ValueOrMissingOp,
    missing: list[str],
    shares_tf: TraceableField[float] | None,
    cash_tf: TraceableField[float] | None,
    debt_tf: TraceableField[float] | None,
    preferred_tf: TraceableField[float] | None,
) -> CapitalStructureValues:
    extracted_values = extract_required_values(
        value_or_missing=value_or_missing,
        missing=missing,
        fields={
            "shares_outstanding": shares_tf,
            "cash": cash_tf,
            "total_debt": debt_tf,
            "preferred_stock": preferred_tf,
        },
    )
    return CapitalStructureValues(
        shares_outstanding=extracted_values["shares_outstanding"],
        cash=extracted_values["cash"],
        total_debt=extracted_values["total_debt"],
        preferred_stock=extracted_values["preferred_stock"],
    )


def extract_filing_capital_structure_market_values(
    *,
    value_or_missing: ValueOrMissingOp,
    missing: list[str],
    shares_tf: TraceableField[float] | None,
    cash_tf: TraceableField[float] | None,
    debt_tf: TraceableField[float] | None,
    preferred_tf: TraceableField[float] | None,
    market_float: MarketFloatOp,
    market_snapshot: Mapping[str, object] | None,
) -> FilingCapitalStructureMarketValues:
    return _extract_capital_structure_market_values(
        value_or_missing=value_or_missing,
        missing=missing,
        shares_tf=shares_tf,
        cash_tf=cash_tf,
        debt_tf=debt_tf,
        preferred_tf=preferred_tf,
        market_float=market_float,
        market_snapshot=market_snapshot,
        shares_source_resolver=resolve_filing_shares_source,
    )


def _extract_capital_structure_market_values(
    *,
    value_or_missing: ValueOrMissingOp,
    missing: list[str],
    shares_tf: TraceableField[float] | None,
    cash_tf: TraceableField[float] | None,
    debt_tf: TraceableField[float] | None,
    preferred_tf: TraceableField[float] | None,
    market_float: MarketFloatOp,
    market_snapshot: Mapping[str, object] | None,
    shares_source_resolver: SharesSourceResolver,
) -> FilingCapitalStructureMarketValues:
    capital_structure_values = extract_capital_structure_values(
        value_or_missing=value_or_missing,
        missing=missing,
        shares_tf=shares_tf,
        cash_tf=cash_tf,
        debt_tf=debt_tf,
        preferred_tf=preferred_tf,
    )
    current_price = extract_current_price(
        market_float=market_float,
        market_snapshot=market_snapshot,
    )
    shares_source = shares_source_resolver(
        market_snapshot=market_snapshot,
        market_float=market_float,
    )
    return FilingCapitalStructureMarketValues(
        shares_outstanding=capital_structure_values.shares_outstanding,
        cash=capital_structure_values.cash,
        total_debt=capital_structure_values.total_debt,
        preferred_stock=capital_structure_values.preferred_stock,
        current_price=current_price,
        shares_source=shares_source,
    )
