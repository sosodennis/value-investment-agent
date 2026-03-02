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
