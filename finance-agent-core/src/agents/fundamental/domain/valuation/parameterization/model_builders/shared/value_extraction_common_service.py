from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol

from src.shared.kernel.traceable import TraceableField

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
