from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from src.agents.fundamental.shared.contracts.traceable import TraceableField

from .value_extraction_common_service import (
    MarketFloatOp,
    SharesSourceResolver,
    ValueOrMissingOp,
    extract_current_price,
    resolve_filing_shares_source,
    resolve_xbrl_filing_shares_source,
)


@dataclass(frozen=True)
class FilingEquityMarketValues:
    shares_outstanding: float | None
    current_price: float | None
    shares_source: str


def extract_filing_equity_market_values(
    *,
    value_or_missing: ValueOrMissingOp,
    missing: list[str],
    shares_tf: TraceableField[float] | None,
    market_float: MarketFloatOp,
    market_snapshot: Mapping[str, object] | None,
) -> FilingEquityMarketValues:
    return _extract_equity_market_values(
        value_or_missing=value_or_missing,
        missing=missing,
        shares_tf=shares_tf,
        market_float=market_float,
        market_snapshot=market_snapshot,
        shares_source_resolver=resolve_filing_shares_source,
    )


def extract_xbrl_filing_equity_market_values(
    *,
    value_or_missing: ValueOrMissingOp,
    missing: list[str],
    shares_tf: TraceableField[float] | None,
    market_float: MarketFloatOp,
    market_snapshot: Mapping[str, object] | None,
) -> FilingEquityMarketValues:
    return _extract_equity_market_values(
        value_or_missing=value_or_missing,
        missing=missing,
        shares_tf=shares_tf,
        market_float=market_float,
        market_snapshot=market_snapshot,
        shares_source_resolver=resolve_xbrl_filing_shares_source,
    )


def _extract_equity_market_values(
    *,
    value_or_missing: ValueOrMissingOp,
    missing: list[str],
    shares_tf: TraceableField[float] | None,
    market_float: MarketFloatOp,
    market_snapshot: Mapping[str, object] | None,
    shares_source_resolver: SharesSourceResolver,
) -> FilingEquityMarketValues:
    shares_outstanding = value_or_missing(shares_tf, "shares_outstanding", missing)
    current_price = extract_current_price(
        market_float=market_float,
        market_snapshot=market_snapshot,
    )
    shares_source = shares_source_resolver(
        market_snapshot=market_snapshot,
        market_float=market_float,
    )
    return FilingEquityMarketValues(
        shares_outstanding=shares_outstanding,
        current_price=current_price,
        shares_source=shares_source,
    )
