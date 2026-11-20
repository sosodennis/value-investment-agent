"""Diagnostic timing preserves outcomes and keeps request data out of logs."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from fundamental_service.valuation_diagnostics import (
    timed_valuation_stage,
    valuation_diagnostic_scope,
    valuation_stage,
)


def _events(caplog):
    prefix = "fundamental_valuation_stage "
    return [
        json.loads(record.getMessage()[len(prefix) :])
        for record in caplog.records
        if record.getMessage().startswith(prefix)
    ]


def test_stage_timings_are_opt_in_and_keep_nested_failure_without_error_text(caplog):
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
            with valuation_diagnostic_scope("request-one"):
                operation()
        assert enabled.value is error
        with valuation_stage("outside.request"):
            pass

    inner, outer = _events(caplog)
    assert inner["parent_span_id"] == outer["span_id"]
    assert outer["parent_span_id"] is None
    assert inner["outcome"] == outer["outcome"] == "failed"
    assert outer["duration_ms"] >= inner["duration_ms"] >= 0
    assert outer["thread_cpu_ms"] >= inner["thread_cpu_ms"] >= 0
    assert "sensitive-input" not in caplog.text
    assert all(event["timing_scope"] == "inclusive" for event in (inner, outer))


def test_concurrent_worker_scopes_keep_correlation_and_span_sequences_separate(caplog):
    def operation(correlation):
        with valuation_diagnostic_scope(correlation):
            with valuation_stage("test.worker"):
                with valuation_stage("test.inner"):
                    return correlation

    async def exercise():
        # to_thread copies request context just as the service's AnyIO worker does.
        with valuation_diagnostic_scope("async-request"):
            result = await asyncio.to_thread(operation, "worker-request")
            with valuation_stage("test.async"):
                return result

    with caplog.at_level("INFO", logger="fundamental_service"):
        with ThreadPoolExecutor(max_workers=2) as workers:
            assert list(workers.map(operation, ("first", "second"))) == [
                "first",
                "second",
            ]
        assert asyncio.run(exercise()) == "worker-request"
    events = _events(caplog)
    for correlation in ("first", "second", "worker-request"):
        spans = [e for e in events if e["correlation_id"] == correlation]
        assert len(spans) == 2
        assert {e["span_id"] for e in spans} == {1, 2}
    async_span = next(e for e in events if e["correlation_id"] == "async-request")
    assert async_span["span_id"] == 1
    assert async_span["parent_span_id"] is None
