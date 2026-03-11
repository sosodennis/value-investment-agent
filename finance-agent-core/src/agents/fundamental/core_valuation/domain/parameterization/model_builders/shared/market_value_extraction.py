from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from src.agents.fundamental.shared.contracts.traceable import TraceableField

MarketFloatOp = Callable[[Mapping[str, object] | None, str], float | None]
ValueOrMissingOp = Callable[
    [TraceableField[float] | None, str, list[str]],
    float | None,
]


class SharesSourceResolver(Protocol):
    def __call__(
        self,
        *,
        market_snapshot: Mapping[str, object] | None,
        market_float: MarketFloatOp,
    ) -> str: ...


def _resolve_shares_source(
    *,
    market_snapshot: Mapping[str, object] | None,
    market_float: MarketFloatOp,
    filing_source: str,
) -> str:
    market_shares = market_float(market_snapshot, "shares_outstanding")
    if market_shares is not None and market_shares > 0:
        if _is_market_shares_stale(market_snapshot):
            return f"{filing_source}_market_stale_fallback"
        return "market_data"
    return filing_source


def resolve_filing_shares_source(
    *,
    market_snapshot: Mapping[str, object] | None,
    market_float: MarketFloatOp,
) -> str:
    return _resolve_shares_source(
        market_snapshot=market_snapshot,
        market_float=market_float,
        filing_source="filing",
    )


def resolve_xbrl_filing_shares_source(
    *,
    market_snapshot: Mapping[str, object] | None,
    market_float: MarketFloatOp,
) -> str:
    return _resolve_shares_source(
        market_snapshot=market_snapshot,
        market_float=market_float,
        filing_source="xbrl_filing",
    )


def extract_required_values(
    *,
    value_or_missing: ValueOrMissingOp,
    missing: list[str],
    fields: Mapping[str, TraceableField[float] | None],
) -> dict[str, float | None]:
    return {
        field_name: value_or_missing(trace_field, field_name, missing)
        for field_name, trace_field in fields.items()
    }


def extract_market_value(
    *,
    market_float: MarketFloatOp,
    market_snapshot: Mapping[str, object] | None,
    field_name: str,
) -> float | None:
    return market_float(market_snapshot, field_name)


def extract_current_price(
    *,
    market_float: MarketFloatOp,
    market_snapshot: Mapping[str, object] | None,
) -> float | None:
    return extract_market_value(
        market_float=market_float,
        market_snapshot=market_snapshot,
        field_name="current_price",
    )


def _is_market_shares_stale(market_snapshot: Mapping[str, object] | None) -> bool:
    if market_snapshot is None:
        return False
    snapshot_is_stale = market_snapshot.get("shares_outstanding_is_stale")
    if isinstance(snapshot_is_stale, bool):
        return snapshot_is_stale

    market_datums_raw = market_snapshot.get("market_datums")
    if not isinstance(market_datums_raw, Mapping):
        return False
    shares_datum_raw = market_datums_raw.get("shares_outstanding")
    if not isinstance(shares_datum_raw, Mapping):
        return False
    staleness_raw = shares_datum_raw.get("staleness")
    if not isinstance(staleness_raw, Mapping):
        return False
    datum_is_stale = staleness_raw.get("is_stale")
    return bool(datum_is_stale) if isinstance(datum_is_stale, bool) else False


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
