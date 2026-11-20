"""Diagnostic timing preserves outcomes and keeps request data out of logs."""

import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

import pytest

from fundamental_service.valuation_diagnostics import (
    ValuationDiagnosticSink,
    diagnostic_error_code,
    timed_valuation_stage,
    valuation_diagnostic_scope,
    valuation_stage,
)
from fundamental_service.operations import RequestLogContext


def test_diagnostic_error_code_only_exposes_allowlisted_codes():
    assert diagnostic_error_code("REQUEST_DEADLINE_EXCEEDED") == (
        "REQUEST_DEADLINE_EXCEEDED"
    )
    assert diagnostic_error_code("FACT_MAPPING_UNRESOLVED") == (
        "FACT_MAPPING_UNRESOLVED"
    )
    assert diagnostic_error_code("private-input-derived-code") is None
    assert diagnostic_error_code(None) is None


@pytest.fixture
def diagnostic_sink():
    sink = ValuationDiagnosticSink()
    yield sink
    sink.close()


def wait_for_diagnostics(sink):
    deadline = monotonic() + 2
    while sink.status()["pending"] and monotonic() < deadline:
        sleep(0.001)
    assert sink.status()["pending"] == 0


def _events(caplog):
    prefix = "fundamental_valuation_stage "
    return [
        json.loads(record.getMessage()[len(prefix) :])
        for record in caplog.records
        if record.getMessage().startswith(prefix)
    ]


def test_stage_timings_are_opt_in_and_keep_nested_failure_without_error_text(
    caplog, diagnostic_sink
):
    error = ValueError("sensitive-input-must-not-be-logged")

    @timed_valuation_stage("test.outer")
    def operation():
        with valuation_stage("test.inner"):
            raise error

    with caplog.at_level("INFO", logger="fundamental_service"):
        with pytest.raises(ValueError) as disabled:
            operation()
        assert disabled.value is error
        assert not _events(caplog)
        with pytest.raises(ValueError) as enabled:
            with valuation_diagnostic_scope(
                RequestLogContext(str(uuid4()), "/v1/valuation/uncertainty"),
                diagnostic_sink,
            ):
                operation()
        assert enabled.value is error
        with valuation_stage("outside.request"):
            pass
        wait_for_diagnostics(diagnostic_sink)

    inner, outer = _events(caplog)
    assert inner["parent_span_id"] == outer["span_id"]
    assert outer["parent_span_id"] is None
    assert inner["outcome"] == outer["outcome"] == "failed"
    assert outer["duration_ms"] >= inner["duration_ms"] >= 0
    assert outer["thread_cpu_ms"] >= inner["thread_cpu_ms"] >= 0
    assert "sensitive-input" not in caplog.text
    assert all(event["timing_scope"] == "inclusive" for event in (inner, outer))


def test_concurrent_worker_scopes_keep_request_ids_and_span_sequences_separate(
    caplog, diagnostic_sink
):
    request_contexts = {
        name: RequestLogContext(str(uuid4()), "/v1/valuation/uncertainty")
        for name in ("first", "second", "worker", "async")
    }

    def operation(request_context, result):
        with valuation_diagnostic_scope(request_context, diagnostic_sink):
            with valuation_stage("test.worker"):
                with valuation_stage("test.inner"):
                    return result

    async def exercise():
        # to_thread copies request context just as the service's AnyIO worker does.
        with valuation_diagnostic_scope(request_contexts["async"], diagnostic_sink):
            result = await asyncio.to_thread(
                operation, request_contexts["worker"], "worker-request"
            )
            with valuation_stage("test.async"):
                return result

    with caplog.at_level("INFO", logger="fundamental_service"):
        with ThreadPoolExecutor(max_workers=2) as workers:
            assert list(
                workers.map(
                    lambda item: operation(*item),
                    (
                        (request_contexts["first"], "first"),
                        (request_contexts["second"], "second"),
                    ),
                )
            ) == [
                "first",
                "second",
            ]
        assert asyncio.run(exercise()) == "worker-request"
        wait_for_diagnostics(diagnostic_sink)
    events = _events(caplog)
    for name in ("first", "second", "worker"):
        request_id = request_contexts[name].request_log_id
        spans = [e for e in events if e["request_log_id"] == request_id]
        assert len(spans) == 2
        assert {e["span_id"] for e in spans} == {1, 2}
    async_span = next(
        e
        for e in events
        if e["request_log_id"] == request_contexts["async"].request_log_id
    )
    assert async_span["span_id"] == 1
    assert async_span["parent_span_id"] is None
    assert "worker-request" not in caplog.text


def test_failing_handler_cannot_replace_success_or_original_error(diagnostic_sink):
    class FailingHandler(logging.Handler):
        def emit(self, record):
            raise OSError("sink failure")

    logger = logging.getLogger("fundamental_service")
    handler = FailingHandler()
    previous_level = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    error = ValueError("valuation failure")
    try:
        with valuation_diagnostic_scope(
            RequestLogContext(str(uuid4()), "/v1/valuation/uncertainty"),
            diagnostic_sink,
        ):
            with valuation_stage("success"):
                result = 42
            with pytest.raises(ValueError) as raised:
                with valuation_stage("failure"):
                    raise error
        wait_for_diagnostics(diagnostic_sink)
        assert result == 42
        assert raised.value is error
        assert diagnostic_sink.status()["failed"] == 2
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)


def test_blocked_handler_bounds_queue_and_does_not_hold_operation_or_shutdown():
    entered, release, operation_finished = Event(), Event(), Event()

    class BlockedHandler(logging.Handler):
        def emit(self, record):
            entered.set()
            release.wait(5)

    logger = logging.getLogger("fundamental_service")
    handler = BlockedHandler()
    previous_level = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    sink = ValuationDiagnosticSink(capacity=1)

    def operation():
        with valuation_diagnostic_scope(
            RequestLogContext(str(uuid4()), "/v1/valuation/uncertainty"), sink
        ):
            with valuation_stage("in-flight"):
                pass
            assert entered.wait(2)
            for _ in range(10):
                with valuation_stage("queued"):
                    pass
        sink.close()
        operation_finished.set()

    try:
        with ThreadPoolExecutor(max_workers=1) as worker:
            future = worker.submit(operation)
            try:
                assert operation_finished.wait(2)
                assert not release.is_set()
                assert sink.status()["dropped"] == 10
                assert sink.status()["pending"] == 1
            finally:
                release.set()
            future.result(timeout=2)
        wait_for_diagnostics(sink)
    finally:
        release.set()
        sink.close()
        logger.removeHandler(handler)
        logger.setLevel(previous_level)


@pytest.mark.parametrize("capacity", [0, -1, 1025])
def test_sink_rejects_unbounded_capacity(capacity):
    with pytest.raises(ValueError):
        ValuationDiagnosticSink(capacity=capacity)
