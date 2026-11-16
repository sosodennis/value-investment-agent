"""OIM numeric duplicate consistency using the pinned Arelle interval owner."""

from collections.abc import Iterable
from decimal import (
    Context,
    Decimal,
    DecimalException,
    Inexact,
    ROUND_HALF_EVEN,
    Rounded,
    localcontext,
)

from arelle import ValidateXbrlCalcs


def numeric_duplicate_issue(
    observations: Iterable[tuple[Decimal, int | None]],
) -> str | None:
    """Check the whole set before discarding any lower-precision observation."""
    values = tuple(observations)
    if len(values) < 2:
        return None
    if any(not value.is_finite() for value, _ in values):
        return "FACT_CONFLICT"
    if any(decimals is None for _, decimals in values):
        # The canonical contract cannot distinguish INF from missing precision.
        return (
            None
            if len({value for value, _ in values}) == 1
            else "FACT_PRECISION_UNAVAILABLE"
        )
    reported: dict[int, Decimal] = {}
    lower, upper = Decimal("-Infinity"), Decimal("Infinity")
    ValidateXbrlCalcs.init()
    try:
        with localcontext(
            Context(prec=28, rounding=ROUND_HALF_EVEN, Emin=-999999, Emax=999999)
        ) as context:
            context.traps[Inexact] = True
            context.traps[Rounded] = True
            for value, decimals in values:
                assert decimals is not None
                if decimals in reported and reported[decimals] != value:
                    return "FACT_CONFLICT"
                reported[decimals] = value
                start, end, _, _ = ValidateXbrlCalcs.rangeValue(value, decimals)
                lower, upper = max(lower, start), min(upper, end)
                if lower > upper:
                    return "FACT_CONFLICT"
    except (DecimalException, OverflowError, ValueError):
        return "FACT_PRECISION_UNAVAILABLE"
    return None
