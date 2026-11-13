"""The released FCFF numerical policy, isolated from caller Decimal state."""

from collections.abc import Callable
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    localcontext,
)
from functools import wraps
from typing import ParamSpec, TypeVar

VALUATION_NUMERICAL_POLICY = "decimal-50-end-of-year-v1"

_P = ParamSpec("_P")
_R = TypeVar("_R")


def using_valuation_context(function: Callable[_P, _R]) -> Callable[_P, _R]:
    """Execute one synchronous numeric boundary in a fresh, fixed context."""

    @wraps(function)
    def evaluate(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        with localcontext(
            Context(
                prec=50,
                rounding=ROUND_HALF_EVEN,
                Emin=-999999,
                Emax=999999,
                capitals=1,
                clamp=0,
                flags=[],
                traps=[InvalidOperation, DivisionByZero, Overflow],
            )
        ):
            return function(*args, **kwargs)

    return evaluate
