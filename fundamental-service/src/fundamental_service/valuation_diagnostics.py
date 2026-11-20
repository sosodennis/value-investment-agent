"""Request-local, opt-in timings without valuation inputs or error messages."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
from time import monotonic, thread_time
from typing import ParamSpec, TypeVar

LOGGER = logging.getLogger("fundamental_service")
P = ParamSpec("P")
T = TypeVar("T")


@dataclass
class _TimingContext:
    correlation_id: str
    started: float = field(default_factory=monotonic)
    next_span: int = 0
    stack: list[int] = field(default_factory=list)


_TIMING: ContextVar[_TimingContext | None] = ContextVar(
    "valuation_timing", default=None
)


@contextmanager
def valuation_diagnostic_scope(correlation_id: str | None) -> Iterator[None]:
    token = _TIMING.set(_TimingContext(correlation_id) if correlation_id else None)
    try:
        yield
    finally:
        _TIMING.reset(token)


@contextmanager
def valuation_stage(stage: str) -> Iterator[None]:
    context = _TIMING.get()
    if context is None:
        yield
        return
    context.next_span += 1
    span_id = context.next_span
    parent_span_id = context.stack[-1] if context.stack else None
    context.stack.append(span_id)
    started, cpu_started = monotonic(), thread_time()
    outcome = "completed"
    try:
        yield
    except BaseException:
        outcome = "failed"
        raise
    finally:
        duration, cpu = monotonic() - started, thread_time() - cpu_started
        context.stack.pop()
        LOGGER.info(
            "fundamental_valuation_stage %s",
            json.dumps(
                {
                    "correlation_id": context.correlation_id,
                    "stage": stage,
                    "span_id": span_id,
                    "parent_span_id": parent_span_id,
                    "started_ms": round((started - context.started) * 1000, 3),
                    "duration_ms": round(duration * 1000, 3),
                    "thread_cpu_ms": round(cpu * 1000, 3),
                    "outcome": outcome,
                    "timing_scope": "inclusive",
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
        )


def timed_valuation_stage(stage: str) -> Callable[[Callable[P, T]], Callable[P, T]]:
    def decorate(operation: Callable[P, T]) -> Callable[P, T]:
        @wraps(operation)
        def measured(*args: P.args, **kwargs: P.kwargs) -> T:
            with valuation_stage(stage):
                return operation(*args, **kwargs)

        return measured

    return decorate
