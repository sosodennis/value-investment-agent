from __future__ import annotations

from collections.abc import Callable, Mapping

from src.shared.kernel.traceable import ManualProvenance, TraceableField


def resolve_reit_ffo_multiple(
    *,
    market_snapshot: Mapping[str, object] | None,
    ffo: float | None,
    shares_outstanding: float | None,
    current_price: float | None,
    market_float: Callable[[Mapping[str, object] | None, str], float | None],
    assumptions: list[str],
) -> tuple[float | None, TraceableField[float] | None]:
    market_multiple = market_float(market_snapshot, "ffo_multiple")
    if market_multiple is not None and market_multiple > 0:
        assumptions.append("ffo_multiple sourced from market data override")
        return (
            market_multiple,
            TraceableField(
                name="FFO Multiple",
                value=market_multiple,
                provenance=ManualProvenance(
                    description="FFO multiple provided by market snapshot override",
                    author="MarketDataService",
                ),
            ),
        )

    if (
        ffo is not None
        and ffo > 0
        and shares_outstanding is not None
        and shares_outstanding > 0
        and current_price is not None
        and current_price > 0
    ):
        ffo_per_share = ffo / shares_outstanding
        if ffo_per_share > 0:
            implied_multiple = current_price / ffo_per_share
            assumptions.append("ffo_multiple implied from market price and FFO/share")
            return (
                implied_multiple,
                TraceableField(
                    name="FFO Multiple",
                    value=implied_multiple,
                    provenance=ManualProvenance(
                        description=(
                            "Implied from market current_price / (ffo / shares_outstanding)"
                        ),
                        author="ValuationPolicy",
                    ),
                ),
            )

    return None, None
