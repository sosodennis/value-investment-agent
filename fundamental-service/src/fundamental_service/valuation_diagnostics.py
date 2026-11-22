"""Request-local, opt-in timings without valuation inputs or error messages."""

from __future__ import annotations

import json
import logging
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
from time import monotonic, thread_time
from typing import ParamSpec, TypeVar

from .operations import RequestLogContext

LOGGER = logging.getLogger("fundamental_service")
P = ParamSpec("P")
T = TypeVar("T")

_DIAGNOSTIC_ERROR_CODES = frozenset(
    {
        "CALCULATION_BUDGET_EXCEEDED",
        "FACT_MAPPING_UNRESOLVED",
        "REQUEST_DEADLINE_EXCEEDED",
        "request_deadline_exceeded",
    }
)


def diagnostic_error_code(code: object) -> str | None:
    return code if isinstance(code, str) and code in _DIAGNOSTIC_ERROR_CODES else None


class ValuationDiagnosticSink:
    """Bound optional logging; a slow or failed handler never owns a worker."""

    def __init__(self, *, capacity: int = 128) -> None:
        if not 1 <= capacity <= 1024:
            raise ValueError("diagnostic capacity must be between 1 and 1024")
        self._queue: Queue[tuple[str, str, dict[str, object] | None]] = Queue(capacity)
        self._lock = Lock()
        self._stopped = Event()
        self._worker: Thread | None = None
        self._dropped = 0
        self._failed = 0
        self._delivered = 0

    def submit(
        self, event: str, payload: str, *, extra: dict[str, object] | None = None
    ) -> None:
        # Bound both queue length and record bytes.
        with self._lock:
            if self._stopped.is_set() or len(payload.encode("utf-8")) > 131072:
                self._dropped += 1
                return
            if self._worker is None:
                self._worker = Thread(
                    target=self._run, name="valuation-diagnostics", daemon=True
                )
                try:
                    self._worker.start()
                except Exception:
                    self._failed += 1
                    self._dropped += 1
                    self._stopped.set()
                    return
            try:
                self._queue.put_nowait((event, payload, extra))
            except Full:
                self._dropped += 1

    def _run(self) -> None:
        while not self._stopped.is_set():
            try:
                event, payload, extra = self._queue.get(timeout=0.05)
            except Empty:
                continue
            try:
                LOGGER.info("%s %s", event, payload, extra=extra)
            except Exception:
                with self._lock:
                    self._failed += 1
            else:
                with self._lock:
                    self._delivered += 1
            finally:
                self._queue.task_done()

    def status(self) -> dict[str, int]:
        with self._lock:
            return {
                "dropped": self._dropped,
                "failed": self._failed,
                "delivered": self._delivered,
                "pending": self._queue.unfinished_tasks,
            }

    def close(self) -> None:
        self._stopped.set()
        # Never join a handler: a deployment sink can block indefinitely.
        with self._lock:
            while True:
                try:
                    self._queue.get_nowait()
                except Empty:
                    break
                self._queue.task_done()
                self._dropped += 1


@dataclass
class _TimingContext:
    request_log_context: RequestLogContext
    sink: ValuationDiagnosticSink
    started: float = field(default_factory=monotonic)
    next_span: int = 0
    stack: list[int] = field(default_factory=list)


_TIMING: ContextVar[_TimingContext | None] = ContextVar(
    "valuation_timing", default=None
)


@contextmanager
def valuation_diagnostic_scope(
    request_log_context: RequestLogContext | None,
    sink: ValuationDiagnosticSink | None = None,
) -> Iterator[None]:
    token = _TIMING.set(
        _TimingContext(request_log_context, sink)
        if request_log_context is not None and sink
        else None
    )
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
        context.sink.submit(
            "fundamental_valuation_stage",
            json.dumps(
                {
                    "request_log_id": context.request_log_context.request_log_id,
                    "route_template": context.request_log_context.route_template,
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
